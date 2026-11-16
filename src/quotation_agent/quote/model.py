"""第三步/第四步的数据模型：归一化报价单、定价结果、审批。

命名对齐题目里"每一笔价格都要能追溯到某一行表格和某一条规则"：
- CanonicalLine 记 refs（这个零件出现在哪些文件哪些位置）
- PricedLine 记 trace（这一笔钱由哪条规则、哪个数字算出）
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class RawLine:
    """从某个块里读出来的一行原始数据（还没合并、没归一）。"""

    part_no: str
    fields: dict
    source_file: str
    locator: str
    # 每个字段各自的出处：图纸里 "Part no" 和 "Order quantity" 在两行上
    locators: dict = field(default_factory=dict)


@dataclass
class CanonicalLine:
    """合并后的一行零件。"""

    part_no: str
    description: str = ""
    material: str = ""
    material_raw: str = ""
    qty: int | None = None
    tol_mm: float | None = None
    tol_raw: str = ""
    mass_kg: float | None = None
    cycle_min: float | None = None
    finish: str = ""
    finish_raw: str = ""
    field_sources: dict[str, str] = field(default_factory=dict)  # 字段 -> 出处，用来标出哪些字段是模型抽取的
    refs: list[str] = field(default_factory=list)  # 形如 "part_list.xlsx!A5"
    confidence: float = 1.0  # 0..1，关键字段的最低可信度
    flags: list[str] = field(default_factory=list)  # 需要人看一眼的原因
    field_confidence: dict = field(default_factory=dict)  # 字段 → 可信度

    @property
    def confidence_label(self) -> str:
        if self.confidence >= 0.85:
            return "high"
        if self.confidence >= 0.55:
            return "medium"
        return "low"


@dataclass
class Conflict:
    """同一件号、同一字段，在不同来源里不一致。"""

    part_no: str
    field_name: str
    values: list[tuple[str, str]]  # [(值, 出处), ...]

    def describe(self) -> str:
        """只描述"值 vs 值"，件号与字段名由调用方加，避免重复。"""
        return "; ".join(f"{v} ({src})" for v, src in self.values)


@dataclass
class CanonicalRFQ:
    """归一化后的询价单：一份 RFQ 只有这一份表示，与输入格式无关。"""

    rfq_no: str
    customer: str
    lines: list[CanonicalLine] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def line_by_part(self, part_no: str) -> CanonicalLine | None:
        for line in self.lines:
            if line.part_no == part_no:
                return line
        return None


@dataclass
class Trace:
    """一条定价依据：用哪条规则、用了什么数、结果多少、出处在哪。"""

    rule: str
    detail: str
    amount: float
    source: str = ""

    def as_text(self) -> str:
        origin = f"  [{self.source}]" if self.source else ""
        return f"{self.rule}: {self.detail} = {self.amount:.2f}{origin}"


@dataclass
class PricedLine:
    line: CanonicalLine
    unit_cost: float
    base_price: float
    discount_rate: float
    unit_price: float
    line_total: float
    trace: list[Trace] = field(default_factory=list)


@dataclass
class HeldLine:
    line: CanonicalLine
    reason: str
    detail: str
    partial: dict = field(default_factory=dict)  # 已经能算出来的成本部分与缺失项


@dataclass
class Approval:
    required: bool
    reasons: list[str] = field(default_factory=list)
    approver: str = "sales manager"

    def describe(self) -> str:
        if not self.required:
            return "No approval required (within delegated authority)"
        return f"Needs {self.approver} sign-off: " + "; ".join(self.reasons)


@dataclass
class Quote:
    rfq: CanonicalRFQ
    priced: list[PricedLine] = field(default_factory=list)
    held: list[HeldLine] = field(default_factory=list)
    approval: Approval = field(default_factory=lambda: Approval(required=False))
    quote_no: str = ""
    valid_days: int = 30

    @property
    def total(self) -> float:
        return round(sum(p.line_total for p in self.priced), 2)

    def to_payload(self) -> dict:
        """给 mart_rfq.payload_json 用的稳定结构。"""
        return {
            "quote_no": self.quote_no,
            "rfq_no": self.rfq.rfq_no,
            "customer": self.rfq.customer,
            "valid_days": self.valid_days,
            "lines": [
                {
                    "part_no": p.line.part_no,
                    "description": p.line.description,
                    "material": p.line.material,
                    "qty": p.line.qty,
                    "unit_cost": round(p.unit_cost, 2),
                    "list_price": round(p.base_price, 2),
                    "discount_rate": p.discount_rate,
                    "unit_price": round(p.unit_price, 2),
                    "line_total": round(p.line_total, 2),
                    "refs": p.line.refs,
                    "trace": [t.as_text() for t in p.trace],
                }
                for p in self.priced
            ],
            "held": [
                {"part_no": h.line.part_no, "reason": h.reason, "detail": h.detail, "refs": h.line.refs}
                for h in self.held
            ],
            "conflicts": [c.describe() for c in self.rfq.conflicts],
            "approval": {"required": self.approval.required, "reasons": self.approval.reasons},
            "total": self.total,
        }
