"""混合抽取：正则优先，模型兜底，两路交叉验证。

为什么这样设计：
- 正则覆盖整齐的正文（样例那种 "1. BRK-100 ... 500 pcs"），不花钱、可回归；
- 模型只在正则抽不全时介入，避免"每封都调模型"的成本和幻觉；
- 两路都给结果时，把两边都写成块——下游的 merge() 会自动逐字段比对，
  不一致就变成冲突清单，不需要在这里再写一套比对逻辑。
"""

from __future__ import annotations

from typing import Callable

from .parsers.body_parser import parse_body

# 判定"正则抽得够不够"的关键字段：缺任一就算不完整
KEY_FIELDS = ("Material", "Qty", "Tolerance (mm)")

# 模型返回的字段名统一成和表头一致，才能被 normalise 的别名表认出来
LLM_KEYS = ("part_no", "description", "material", "qty", "tol_mm", "mass_kg", "cycle_min", "finish")
HEADER_MAP = {
    "part_no": "Part no",
    "description": "Description",
    "material": "Material",
    "qty": "Qty",
    "tol_mm": "Tolerance (mm)",
    "mass_kg": "Mass (kg)",
    "cycle_min": "Cycle (min)",
    "finish": "Finish",
}

# 模型抽取函数的签名：正文 -> [{"part_no": ..., "material": ..., ...}, ...]
LLMExtractor = Callable[[str], list[dict]]


def regex_blocks(body_text: str) -> list[dict]:
    """走现有正则解析器。"""
    result = parse_body(body_text)
    return list(result.blocks)


UNKNOWN_QTY_MARKERS = ("tbc", "to follow", "to be confirmed", "tba", "待定", "待确认")


def is_complete(rows: list[dict], body_text: str = "") -> bool:
    """关键字段是否齐全：材料、数量、公差三样都要在。

    例外：正文里明写"数量待定"（TBC / to follow）的行，缺数量不算抽取失败——
    那是客户没给，不是解析器没读到。只有当"缺数量的行数"超过"待定标记数"时，
    才认为确实有信息被漏掉。
    """
    if not rows:
        return False

    def has(row: dict, field: str) -> bool:
        return row.get(field) not in (None, "")

    for row in rows:
        if not (has(row, "Material") and has(row, "Tolerance (mm)")):
            return False

    missing_qty = sum(1 for row in rows if not has(row, "Qty"))
    if missing_qty == 0:
        return True

    lowered = (body_text or "").lower()
    marked = sum(lowered.count(marker) for marker in UNKNOWN_QTY_MARKERS)
    return missing_qty <= marked


def _llm_rows_to_blocks(rows: list[dict], warnings: list[str]) -> list[dict]:
    """把模型返回的 dict 列表转成块，字段名转成表头写法。"""
    blocks: list[dict] = []
    ordinal = 0
    for index, row in enumerate(rows, start=1):
        part_no = str(row.get("part_no") or "").strip()
        if not part_no:
            warnings.append(f"llm_row_without_part_no: row {index} had no part number and was dropped")
            continue
        mapped: dict[str, object] = {"Part no": part_no}
        for key in LLM_KEYS[1:]:
            value = row.get(key)
            if value in (None, ""):
                continue
            mapped[HEADER_MAP[key]] = value
        ordinal += 1
        blocks.append({
            "block_type": "table_row",
            "locator": f"llm line {index}",
            "ordinal": ordinal,
            "row": mapped,
        })
    return blocks


def hybrid_blocks(
    body_text: str,
    llm: LLMExtractor | None = None,
) -> tuple[list[dict], list[str]]:
    """返回（块, 告警）。

    三档行为：
    1. 正则抽全了 → 只用正则，不调模型；
    2. 正则抽不全 → 调模型，把模型的结果也写成块（两路共存，交给 merge 交叉验证）；
    3. 没配模型 → 只返回正则结果 + 告警，不阻塞流程。
    """
    warnings: list[str] = []
    blocks = regex_blocks(body_text)
    rows = [b["row"] for b in blocks if b.get("row")]

    if is_complete(rows, body_text):
        return blocks, warnings

    if llm is None:
        warnings.append("llm_not_configured: rule extraction was incomplete and no model is available; continuing with what we have")
        return blocks, warnings

    warnings.append("llm_fallback_used: rule extraction was incomplete, so the model was asked to read the text")
    try:
        llm_rows = llm(body_text)
    except Exception as exc:  # 模型失败不能拖垮流程
        warnings.append(f"llm_failed: {type(exc).__name__}: {exc}")
        return blocks, warnings

    if not isinstance(llm_rows, list):
        warnings.append("llm_bad_shape: the model did not return a list; ignored")
        return blocks, warnings

    llm_blocks = _llm_rows_to_blocks(llm_rows, warnings)
    if not llm_blocks:
        warnings.append("llm_empty: the model did not extract any rows")
        return blocks, warnings

    return blocks + llm_blocks, warnings
