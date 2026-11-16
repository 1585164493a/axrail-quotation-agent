"""第四步：定价。纯函数，不碰数据库、不调模型。

题目给的规则，逐条对应一行代码：

    单位成本 = 质量 × 材料价 + 工时 × 机时价 + 表面处理 + 装夹 / 数量
    材料价：AL6061 18.00、SS304 22.00 MYR/kg，其它材料无标准价
    机时价：公差 ≥0.05 → 三轴 2.00/min；0.02 ≤ 公差 <0.05 → 五轴 3.50/min；更紧 → 无费率
    装夹 250/行；阳极氧化 1.50/件
    毛利 25%（按毛利率：售价 = 成本 ÷ 0.75）
    数量折扣：≥500 件 5%，≥1000 件 8%

算不出来的，一律返回 hold + 原因，绝不返回一个编出来的数字。
"""

from __future__ import annotations

from .model import CanonicalLine, HeldLine, PricedLine, Trace

# ---------------- 规则表（改这里就是改政策，代码别处不动） ----------------

MATERIAL_PRICE: dict[str, float] = {
    "AL6061": 18.00,
    "SS304": 22.00,
}

# (上限, 下限, 工艺名, 每分钟单价)；tol 落在 [下限, 上限) 区间内用这一档
MACHINE_TIERS = [
    (float("inf"), 0.05, "CNC 3-axis", 2.00),
    (0.05, 0.02, "CNC 5-axis", 3.50),
]

SETUP_PER_LINE = 250.00
FINISH_PRICE = {"anodise": 1.50, "none": 0.00}
MARGIN = 0.25  # 毛利率：售价 = 成本 / (1 - MARGIN)

# 数量折扣档：(最低数量, 折扣率)
DISCOUNT_TIERS = [(1000, 0.08), (500, 0.05)]

# 审批阈值
APPROVAL_TOTAL_THRESHOLD = 50_000.00
POLICY_MAX_DISCOUNT = 0.08


def machine_rate(tol_mm: float) -> tuple[str, float] | None:
    """按公差选机床档位；超出最低档返回 None（无标准费率）。"""
    for upper, lower, name, rate in MACHINE_TIERS:
        # 区间：lower <= tol < upper（tol 越小要求越高、越贵）
        if lower <= tol_mm < upper:
            return name, rate
    return None


def material_price(material: str) -> float | None:
    return MATERIAL_PRICE.get(material)


def finish_cost(finish: str) -> float:
    return FINISH_PRICE.get(finish, 0.0)


def discount_rate(qty: int) -> float:
    for min_qty, rate in DISCOUNT_TIERS:
        if qty >= min_qty:
            return rate
    return 0.0


def explain_partial(line: CanonicalLine) -> dict:
    """一行算不出价时，把**已经知道的部分**摊开，并把缺的字段列出来。

    为什么需要：报不出价不等于什么都算不出。
    - 数量待定：材料费、机时费、表面处理都能算，只有"每件分摊的工装费"算不了；
    - 材料没价：数量、机时、表面处理都在，只缺材料单价。
    采购/工程拿到这张表，只要补一个数就能出价，不用重问客户。
    """
    known: dict[str, dict] = {}
    missing: list[str] = []

    if line.mass_kg is not None and line.material:
        unit = material_price(line.material)
        if unit is None:
            missing.append(f"material price for {line.material_raw or line.material}")
        else:
            known["material"] = {"amount": round(line.mass_kg * unit, 2),
                                 "detail": f"{line.mass_kg} kg x {unit:.2f}"}
    elif line.mass_kg is None:
        missing.append("part mass (kg)")
    elif not line.material:
        missing.append("material")

    rate = machine_rate(line.tol_mm) if line.tol_mm is not None else None
    if line.tol_mm is None:
        missing.append("tolerance (mm)")
    elif rate is None:
        missing.append(f"machine rate for tolerance +/-{line.tol_mm} mm")
    if line.cycle_min is None:
        missing.append("cycle time (min)")
    elif rate is not None:
        name, unit_rate = rate
        known["machining"] = {"amount": round(line.cycle_min * unit_rate, 2),
                              "detail": f"{line.cycle_min} min x {unit_rate:.2f} ({name})"}

    finish_amount = finish_cost(line.finish)
    known["finish"] = {"amount": finish_amount, "detail": f"finish = {line.finish or 'none'}"}

    qty = line.qty
    if qty is None or qty <= 0:
        missing.append("order quantity")
    else:
        known["setup"] = {"amount": round(SETUP_PER_LINE / qty, 2),
                          "detail": f"{SETUP_PER_LINE:.2f} / {qty} pcs"}

    subtotal = round(sum(item["amount"] for item in known.values()), 2)
    return {
        "known": known,
        "missing": missing,
        "known_subtotal": subtotal,
        "note": "Known components only; a final price also needs the missing items.",
    }


def price_line(line: CanonicalLine, qty_override: int | None = None) -> PricedLine | HeldLine:
    """算一行。返回 PricedLine（能算）或 HeldLine（算不出，附原因）。"""

    qty = qty_override if qty_override is not None else line.qty

    def hold(reason: str, detail: str) -> HeldLine:
        # 算不出价也要把"已知部分"带出去，方便采购/工程补数据
        return HeldLine(line, reason, detail, partial=explain_partial(line))

    # ---- 前置检查：缺任何一项就不能硬算 ----
    if qty is None or qty <= 0:
        return hold("hold_no_qty", "Order quantity is not confirmed (TBC), so setup cost cannot be spread.")

    if line.material and material_price(line.material) is None:
        return hold(
            "hold_no_material",
            f"Material {line.material_raw or line.material} has no standard price in the price list.",
        )

    if line.tol_mm is None:
        return hold("hold_no_tolerance", f"Tolerance could not be parsed: {line.tol_raw or 'empty'}")

    rate = machine_rate(line.tol_mm)
    if rate is None:
        return hold(
            "hold_no_rate",
            f"Tolerance ±{line.tol_mm} is tighter than ±0.02; no standard machine rate, engineering review required.",
        )

    if line.mass_kg is None or line.cycle_min is None:
        return hold("hold_no_mass_or_cycle", "Part mass or cycle time is missing, so material and machine cost cannot be calculated.")

    # ---- 成本 ----
    trace: list[Trace] = []
    material_unit = material_price(line.material) if line.material else None
    if material_unit is None:
        # 没有材料信息：不能假设，直接挂起
        return hold("hold_no_material", "No material identified, so material cost cannot be calculated.")

    mat_amount = round(line.mass_kg * material_unit, 2)
    trace.append(Trace(
        f"M-{line.material}",
        f"{line.mass_kg} kg × {material_unit:.2f}",
        mat_amount,
        line.refs[0] if line.refs else "",
    ))

    machine_name, machine_unit = rate
    mach_amount = round(line.cycle_min * machine_unit, 2)
    trace.append(Trace(
        "R-3AXIS" if machine_name == "CNC 3-axis" else "R-5AXIS",
        f"{line.cycle_min} min × {machine_unit:.2f} ({machine_name}, tol ±{line.tol_mm})",
        mach_amount,
        line.refs[0] if line.refs else "",
    ))

    fin_amount = round(finish_cost(line.finish), 2)
    trace.append(Trace(
        "F-ANODISE" if line.finish == "anodise" else "F-NONE",
        f"{line.finish or 'none'}",
        fin_amount,
        line.refs[0] if line.refs else "",
    ))

    setup_amount = round(SETUP_PER_LINE / qty, 2)
    trace.append(Trace("S-LINE", f"{SETUP_PER_LINE:.2f} / {qty} pcs", setup_amount))

    unit_cost = round(mat_amount + mach_amount + fin_amount + setup_amount, 2)
    trace.append(Trace("COST", "sum of the four components", unit_cost))

    # ---- 售价：毛利率口径 ----
    base_price = round(unit_cost / (1 - MARGIN), 2)
    trace.append(Trace("P-MARGIN", f"{unit_cost:.2f} ÷ (1 − {MARGIN:.0%})", base_price))

    rate_disc = discount_rate(qty)
    unit_price = round(base_price * (1 - rate_disc), 2)
    if rate_disc:
        trace.append(Trace(
            f"D-QTY-{int(rate_disc * 100)}",
            f"{base_price:.2f} × (1 − {rate_disc:.0%}) ({qty} pcs tier)",
            unit_price,
        ))

    line_total = round(unit_price * qty, 2)
    trace.append(Trace("TOTAL", f"{unit_price:.2f} × {qty} pcs", line_total))

    return PricedLine(
        line=line,
        unit_cost=unit_cost,
        base_price=base_price,
        discount_rate=rate_disc,
        unit_price=unit_price,
        line_total=line_total,
        trace=trace,
    )
