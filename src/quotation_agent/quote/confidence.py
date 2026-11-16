"""可信度打分：同一字段在不同来源里一致吗？来源本身可靠吗？

为什么要打分而不是"有值就用"：
题目要求 flag anything a person must check。判断"要不要人看"不能靠感觉，
得有一条可解释的规则，而且规则要能说给销售听。

权重（同一字段只有一个来源时，直接用它的权重）：
    结构化附件（xlsx / pptx / docx）  0.90   客户填的表格，字段明确
    PDF 图纸                          0.70   多是图，抽文字容易缺上下文
    邮件正文                          0.60   人随口写的，格式随意
    模型抽取（llm line）              0.45   二手转述，可能读错

规则：
    多来源且值一致 → 取最高权重 + 每个额外来源 +0.05（上限 0.99）
    多来源但不一致 → 0.30，并记一条冲突（必须人看）
    只有一个来源     → 该来源权重
    字段缺失        → 0.40（算"信息不全"，不是"信息矛盾"）
    行可信度 = 关键字段（数量/材料/公差）可信度的最小值
"""

from __future__ import annotations

# 来源类型 → 基础可信度
WEIGHTS = {
    "xlsx": 0.90,
    "pptx": 0.90,
    "docx": 0.90,
    "pdf": 0.70,
    "body": 0.60,
    "llm": 0.45,
    "unknown": 0.50,
}

CONFLICT_SCORE = 0.30
MISSING_SCORE = 0.40
KEY_FIELDS = ("qty", "material", "tol")


def source_kind(origin: str) -> str:
    """从 "part_list.xlsx @ Part list!A5" 这类出处里判断来源类型。"""
    text = (origin or "").lower()
    if "@ llm line" in text or text.startswith("llm"):
        return "llm"
    for suffix in ("xlsx", "pptx", "docx", "pdf"):
        if suffix in text:
            return suffix
    if "email body" in text or "body line" in text:
        return "body"
    return "unknown"


def document_of(origin: str) -> str:
    """出处属于哪一份**文件**。

    "email body @ body line 6" 与 "email body @ llm line 1" 是同一份文件的两个读法，
    不能算成两个独立来源 —— 模型重读一遍正文不是佐证。
    """
    text = (origin or "").strip().lower()
    if " @ " in text:
        return text.split(" @ ", 1)[0]
    return text


def weight_of(origin: str) -> float:
    return WEIGHTS[source_kind(origin)]


def score_field(values: list[tuple[object, str]]) -> tuple[float, str]:
    """一个字段的（可信度, 说明）。values 是 [(值, 出处), ...]。

    加分只在**不同文件之间**算：同一份正文被正则和模型各读一遍，仍然算一个来源。
    """
    if not values:
        return MISSING_SCORE, "missing"

    distinct = {value for value, _ in values}
    if len(distinct) > 1:
        return CONFLICT_SCORE, "conflict"

    # 每份文件取它最可靠的那个读法
    by_document: dict[str, float] = {}
    for _value, origin in values:
        document = document_of(origin)
        by_document[document] = max(by_document.get(document, 0.0), weight_of(origin))

    weights = sorted(by_document.values(), reverse=True)
    score = weights[0]
    if len(weights) > 1:
        score = min(0.99, score + 0.05 * (len(weights) - 1))
    return round(score, 2), "agreed" if len(weights) > 1 else "single"


def score_line(field_values: dict[str, list[tuple[object, str]]]) -> tuple[float, list[str], dict]:
    """整行打分，返回（可信度, 需要人看的原因, 每字段可信度）。"""
    confidences: dict[str, float] = {}
    flags: list[str] = []

    for name, values in field_values.items():
        # "TBC" 这类解析出来是 None 的值，按"没有信息"处理，不算一个来源
        known = [(value, origin) for value, origin in values if value not in (None, "")]
        score, status = score_field(known)
        confidences[name] = score
        if status == "conflict":
            flags.append(f"{name}: sources disagree")
        elif status == "missing" and name in KEY_FIELDS:
            flags.append(f"{name}: not stated")

    key_scores = [confidences.get(name, MISSING_SCORE) for name in KEY_FIELDS]
    return round(min(key_scores), 2), flags, confidences
