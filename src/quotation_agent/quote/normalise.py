"""第三步：归一化。把不同格式的块合成同一份 CanonicalRFQ，并抓出冲突。

这一步只做"把话对齐"，不改数据：
- 表头/字段名归一（"Part no" / "Part number" 都当件号）
- 值归一（"1,000 pcs" → 1000，"±0.05 mm" → 0.05，"TBC" → 未知）
- 同一件号跨文件合并；同一字段不一致 → 冲突，不自动裁决
"""

from __future__ import annotations

import re
from collections import OrderedDict

from .confidence import score_line, weight_of
from .model import CanonicalLine, CanonicalRFQ, Conflict, RawLine
from .values import parse_mass as parse_mass_value
from .values import parse_tolerance

# 材料别名 → 价表键
MATERIAL_ALIASES = {
    "al6061": "AL6061", "6061": "AL6061", "al 6061": "AL6061", "aluminium 6061": "AL6061",
    "aluminum 6061": "AL6061", "铝合金6061": "AL6061", "al6061-t6": "AL6061",
    "ss304": "SS304", "304": "SS304", "stainless steel 304": "SS304", "304不锈钢": "SS304",
    "sus304": "SS304", "sus 304": "SS304", "aisi 304": "SS304", "1.4301": "SS304",
    "ss 304": "SS304", "304 ss": "SS304",
    "ti gr5": "Ti Gr5", "titanium gr5": "Ti Gr5", "ti-6al-4v": "Ti Gr5", "钛合金": "Ti Gr5",
}

FINISH_ALIASES = {
    "anodise": "anodise", "anodised": "anodise", "anodize": "anodise", "anodized": "anodise",
    "clear anodise": "anodise", "clear anodized": "anodise", "阳极氧化": "anodise",
    "none": "none", "no finish": "none", "n/a": "none", "无": "none", "": "none",
}

# 字段名 → 规范字段
FIELD_ALIASES = {
    "part no": "part_no", "part_no": "part_no", "part number": "part_no", "partno": "part_no",
    "件号": "part_no",
    "description": "description", "desc": "description", "描述": "description",
    "material": "material", "材料": "material",
    "qty": "qty", "quantity": "qty", "order quantity": "qty", "数量": "qty",
    "tolerance": "tol", "tolerance (mm)": "tol", "general tolerance": "tol", "公差": "tol",
    "mass": "mass", "mass (kg)": "mass", "mass (approx.)": "mass", "weight": "mass", "质量": "mass",
    "cycle": "cycle", "cycle (min)": "cycle", "工时": "cycle",
    "finish": "finish", "surface finish": "finish", "表面处理": "finish",
}

UNKNOWN_QTY_TOKENS = {"tbc", "to be confirmed", "to follow", "tba", "n/a", "待定", "待确认"}

# P2：规则解释不了时，可由外部注入一个"值解释器"（例如问模型），返回 (值, 说明)。
_VALUE_INTERPRETER = None


def set_value_interpreter(interpreter) -> None:
    """注入值解释器；传 None 关闭。签名：(text, kind) -> (value|None, note)。"""
    global _VALUE_INTERPRETER
    _VALUE_INTERPRETER = interpreter


def _norm_key(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().lower())


def canonical_field(name: str) -> str | None:
    key = _norm_key(name)
    if key in FIELD_ALIASES:
        return FIELD_ALIASES[key]
    for alias, field in FIELD_ALIASES.items():
        if alias and alias in key:
            return field
    return None


def parse_qty(value) -> int | None:
    """'1,000 pcs' → 1000；'TBC' / 'to follow' / 空 → None。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    text = _norm_key(value).replace(",", "")
    if text in UNKNOWN_QTY_TOKENS or not text:
        return None
    match = re.search(r"\d+(?:\.\d+)?", text)
    if not match:
        return None
    return int(float(match.group(0)))


def parse_tol(value) -> float | None:
    """'±0.05 mm' / '+/-0.02' / '0.005' / '0.004"' / 'IT7' → mm。

    P2：单位换算与 IT 等级由 values.parse_tolerance 负责（规则优先，模型兜底）。
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    parsed, _note = parse_tolerance(str(value))
    if parsed is None and _VALUE_INTERPRETER is not None:
        parsed, _note = _VALUE_INTERPRETER(str(value), "tol")
    return parsed


def parse_float(value) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group(0)) if match else None


def parse_mass(value) -> float | None:
    """P2：'620 g' → 0.62，'0.62 kg' → 0.62。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    parsed, _note = parse_mass_value(str(value))
    if parsed is None and _VALUE_INTERPRETER is not None:
        parsed, _note = _VALUE_INTERPRETER(str(value), "mass")
    return parsed


def _material_from_text(key: str) -> str | None:
    """从自由文本里认出材料牌号（模型返回的常是 "6061 aluminium" 这种）。

    只认价表里存在的牌号；认不出就返回 None，让它按"无材料价"挂起，
    绝不猜一个价格。
    """
    import re

    compact = re.sub(r"[\s_-]+", " ", key.lower())

    def has(pattern: str) -> bool:
        return bool(re.search(pattern, compact))

    grade = re.search(r"\b(6061|7075|5083)\b", compact)
    if grade and has(r"al(uminium|uminum)?|铝"):
        return f"AL{grade.group(1)}"

    grade = re.search(r"\b(304|316)\b", compact)
    if grade and has(r"stainless|ss\b|不锈钢|^ss\d"):
        return f"SS{grade.group(1)}"

    if has(r"titanium|\bti\b|钛") and has(r"gr ?5\b|grade ?5|6al ?4v"):
        return "Ti Gr5"

    return None


def parse_material(value) -> tuple[str, str]:
    raw = str(value or "").strip()
    key = _norm_key(raw)

    def priced(grade: str) -> bool:
        """只有价表里有的牌号才规范化；否则原样保留，交给定价去挂起。"""
        try:
            from .pricing import MATERIAL_PRICE

            return grade in MATERIAL_PRICE
        except Exception:  # 拿不到价表就认为可用
            return True

    if key in MATERIAL_ALIASES and priced(MATERIAL_ALIASES[key]):
        return MATERIAL_ALIASES[key], raw

    guessed = _material_from_text(key)
    if guessed and priced(guessed):
        return guessed, raw
    return raw, raw


def parse_finish(value) -> tuple[str, str]:
    raw = str(value or "").strip()
    return FINISH_ALIASES.get(_norm_key(raw), "none"), raw


def candidates_from_blocks(blocks: list[dict]) -> list[RawLine]:
    """把块变成候选行。

    - table_row：一行一个候选
    - kv：图纸那种"Part no / Order quantity"的键值组，攒成一个候选
    """
    out: list[RawLine] = []
    current: dict[str, object] = {}
    current_loc: dict[str, str] = {}

    def flush() -> None:
        nonlocal current, current_loc
        part_no = current.get("part_no")
        if part_no:
            out.append(
                RawLine(
                    part_no=str(part_no),
                    fields={k: v for k, v in current.items() if k != "part_no"},
                    source_file=current.get("_file", ""),
                    locator=current.get("_locator", ""),
                    locators={k: v for k, v in current_loc.items() if k != "part_no"},
                )
            )
        current = {}
        current_loc = {}

    for block in blocks:
        file_name = block.get("filename", "")
        locator = block.get("locator", "")
        if block["block_type"] == "table_row":
            row = block["row"]
            fields = {}
            for key, value in row.items():
                field = canonical_field(key)
                if field and field != "part_no":
                    fields[field] = value
            part_no = next(
                (str(row[k]) for k in row if canonical_field(k) == "part_no"), ""
            )
            if part_no:
                out.append(
                    RawLine(
                        part_no=part_no.strip(),
                        fields=fields,
                        source_file=file_name,
                        locator=locator,
                        locators={f: locator for f in fields},
                    )
                )
            continue

        if block["block_type"] == "kv" and block.get("key") and block.get("value"):
            field = canonical_field(block["key"])
            if field is None:
                continue
            if field == "part_no":
                flush()
                current = {"part_no": str(block["value"]).strip(), "_file": file_name, "_locator": locator}
                current_loc = {}
            else:
                if current:
                    current[field] = block["value"]
                    current_loc[field] = locator
    flush()
    return out



def merge(candidates: list[RawLine], rfq_no: str, customer: str) -> CanonicalRFQ:
    """按件号合并候选行，字段不一致的记成冲突。"""
    rfq = CanonicalRFQ(rfq_no=rfq_no, customer=customer)
    by_part: OrderedDict[str, list[RawLine]] = OrderedDict()
    for cand in candidates:
        by_part.setdefault(cand.part_no.upper(), []).append(cand)

    for part_key, cands in by_part.items():
        # 来源可信度高的排前面：结构化附件 > PDF > 正文 > 模型
        cands = sorted(cands, key=lambda c: -weight_of(f"{c.source_file} @ {c.locator}"))
        line = CanonicalLine(part_no=part_key)

        def gather(field: str) -> list[tuple[object, str]]:
            return [
                (c.fields.get(field), f"{c.source_file} @ {c.locators.get(field, c.locator)}")
                for c in cands
                if c.fields.get(field) not in (None, "")
            ]

        refs: list[str] = []
        for c in cands:
            for loc in (c.locators or {}).values() or [c.locator]:
                ref = f"{c.source_file} @ {loc}"
                if ref not in refs:
                    refs.append(ref)
        line.refs = refs

        # 记录每个字段最终取自哪个出处（第一个非空、且已按可信度排序）
        for field_name in ("description", "material", "qty", "tolerance", "mass", "cycle", "finish"):
            picked = gather(field_name)
            if picked:
                line.field_sources[field_name] = str(picked[0][1])

        # 描述/材料/数量/公差/质量/工时/表面处理：取第一个非空值，另外记冲突
        descriptions = gather("description")
        if descriptions:
            line.description = str(descriptions[0][0])

        materials = [(parse_material(v)[0], s) for v, s in gather("material")]
        if materials:
            line.material, line.material_raw = materials[0][0], str(gather("material")[0][0])
            if len({m for m, _ in materials}) > 1:
                rfq.conflicts.append(Conflict(part_key, "material", [(m, s) for m, s in materials]))

        quantities = [(parse_qty(v), s) for v, s in gather("qty")]
        quantities = [(q, s) for q, s in quantities if q is not None] + [
            (None, s) for q, s in quantities if q is None
        ]
        if quantities:
            line.qty = quantities[0][0]
            known = [(q, s) for q, s in quantities if q is not None]
            if len({q for q, _ in known}) > 1:
                rfq.conflicts.append(Conflict(part_key, "qty", [(str(q), s) for q, s in known]))

        tols = [(parse_tol(v), s) for v, s in gather("tol")]
        tols = [(t, s) for t, s in tols if t is not None]
        if tols:
            line.tol_mm = tols[0][0]
            line.tol_raw = str(gather("tol")[0][0])
            if len({t for t, _ in tols}) > 1:
                rfq.conflicts.append(Conflict(part_key, "tolerance", [(str(t), s) for t, s in tols]))

        masses = [(parse_mass(v), s) for v, s in gather("mass")]
        masses = [(m, s) for m, s in masses if m is not None]
        if masses:
            line.mass_kg = masses[0][0]
            if len({m for m, _ in masses}) > 1:
                rfq.conflicts.append(Conflict(part_key, "mass", [(str(m), s) for m, s in masses]))

        cycles = [(parse_float(v), s) for v, s in gather("cycle")]
        cycles = [(c, s) for c, s in cycles if c is not None]
        if cycles:
            line.cycle_min = cycles[0][0]

        finishes = [(parse_finish(v)[0], s) for v, s in gather("finish")]
        if finishes:
            line.finish, line.finish_raw = finishes[0][0], str(gather("finish")[0][0])

        # 可信度：关键字段（数量/材料/公差）里最低的那个决定整行
        score, flags, field_scores = score_line({
            "qty": [(parse_qty(v), s) for v, s in gather("qty")],
            "material": [(parse_material(v)[0], s) for v, s in gather("material")],
            "tol": [(parse_tol(v), s) for v, s in gather("tol")],
            "mass": [(parse_mass(v), s) for v, s in gather("mass")],
            "cycle": [(parse_float(v), s) for v, s in gather("cycle")],
        })
        line.confidence = score
        line.flags = flags
        line.field_confidence = field_scores

        rfq.lines.append(line)

    if rfq.conflicts:
        rfq.notes.append(
            f"{len(rfq.conflicts)} conflict(s) found; each line is quoted from its first source and flagged for confirmation"
        )
    return rfq
