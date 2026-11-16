"""P1 结构映射：表头认不出来时，让模型说"哪一列是什么"，代码按映射取值。

边界（很重要）：
- 模型只输出**列 → 字段**的映射，不输出任何零件数据；
- 映射要过五道校验，不过就当没映射，退回规则结果；
- 同一模板（指纹相同）第二次直接命中缓存，不再调用模型。
"""

from __future__ import annotations

import hashlib
import json
from typing import Callable

from .base import norm_cell
from .mapping_cache import default_cache

# 允许模型映射到的字段
TARGET_FIELDS = [
    "part_no", "description", "material", "qty", "tol", "mass", "cycle", "finish",
]

# 字段 → 我们内部用的表头文字（下游 normalise 认识这些名字）
FIELD_HEADERS = {
    "part_no": "Part no",
    "description": "Description",
    "material": "Material",
    "qty": "Qty",
    "tol": "Tolerance (mm)",
    "mass": "Mass (kg)",
    "cycle": "Cycle (min)",
    "finish": "Finish",
}

PROMPT = """You are mapping a supplier spreadsheet to our fixed schema.

Target fields: {fields}

Below are the first rows of the sheet (row number: cells, separated by " | ").
Identify which spreadsheet column holds which target field.

Rules:
- Use spreadsheet column letters (A, B, C, ...).
- Only use the target field names exactly as listed.
- Do not invent columns or values.
- If a field is not present, omit it.

Rows:
{rows}

Reply with JSON only:
{{"header_row": <1-based row number that holds the headers>,
  "columns": {{"<letter>": "<field>"}},
  "units": {{"<letter>": "<unit>"}},
  "reason": "<one sentence>",
  "confidence": <0-1>}}
"""



def letter_index(letter: str) -> int:
    """A → 0, AA → 26。"""
    index = 0
    for char in letter.strip().upper():
        index = index * 26 + (ord(char) - 64)
    return index - 1


def fingerprint(rows: list[list], kind: str = "xlsx") -> str:
    """模板指纹：前 6 行的文字 + 列数 + 文件类型。"""
    preview = []
    for row in rows[:6]:
        preview.append("|".join(norm_cell(cell) for cell in row))
    raw = f"{kind}::{len(rows[0]) if rows else 0}::" + "\n".join(preview)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def build_prompt(rows: list[list]) -> str:
    lines = []
    for i, row in enumerate(rows[:8], start=1):
        cells = " | ".join(norm_cell(cell) for cell in row)
        lines.append(f"{i}: {cells}")
    return PROMPT.format(fields=", ".join(TARGET_FIELDS), rows="\n".join(lines))


def _parse_json(text: str) -> dict | None:
    if not isinstance(text, str):
        return text if isinstance(text, dict) else None
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def validate_mapping(mapping: dict | None, rows: list[list], column_count: int) -> tuple[bool, list[str]]:
    """五道校验：列存在 / 字段合法且不重复 / 覆盖 part_no / 样本可解析 / 表头行合理。"""
    problems: list[str] = []
    if not mapping or not isinstance(mapping, dict):
        return False, ["not a mapping object"]

    columns = mapping.get("columns") or {}
    if not isinstance(columns, dict) or not columns:
        return False, ["no columns mapped"]

    seen: dict[str, str] = {}
    for letter, field in columns.items():
        idx = letter_index(str(letter))
        if idx < 0 or idx >= column_count:
            problems.append(f"column {letter} out of range")
            continue
        if field not in TARGET_FIELDS:
            problems.append(f"unknown field {field}")
            continue
        if field in seen:
            problems.append(f"field {field} mapped twice ({seen[field]}, {letter})")
            continue
        seen[field] = str(letter)

    if "part_no" not in seen:
        problems.append("part_no not mapped")
    if len(seen) < 3:
        problems.append(f"only {len(seen)} fields mapped")

    header_row = mapping.get("header_row")
    if not isinstance(header_row, int) or not (1 <= header_row <= len(rows)):
        problems.append("header_row out of range")

    # 样本值可解析性：数量列至少有 60% 能被 parse_qty 认出来
    qty_letter = seen.get("qty")
    if qty_letter:
        from ..quote.normalise import parse_qty

        qty_idx = letter_index(qty_letter)
        samples = [row[qty_idx] for row in rows[1:] if qty_idx < len(row) and norm_cell(row[qty_idx])]
        if samples:
            ok = sum(1 for value in samples if parse_qty(norm_cell(value)) is not None)
            if ok / len(samples) < 0.6:
                problems.append("qty column samples do not parse")

    return (not problems), problems


def headers_from_mapping(mapping: dict) -> list[str]:
    """把映射转成"按列位置排列的表头文字"，让下游 row_dict 直接可用。"""
    columns = mapping.get("columns") or {}
    size = max((letter_index(str(letter)) for letter in columns), default=-1) + 1
    headers = [""] * size
    for letter, field in columns.items():
        idx = letter_index(str(letter))
        if 0 <= idx < size:
            headers[idx] = FIELD_HEADERS.get(field, "")
    return headers


def map_columns(
    rows: list[list],
    llm: Callable[[str], str] | None = None,
    cache=None,
    kind: str = "xlsx",
) -> dict | None:
    """返回通过的映射；不通过或没有模型时返回 None。"""
    cache = cache if cache is not None else default_cache()
    column_count = max((len(row) for row in rows), default=0)
    if not rows or column_count == 0:
        return None

    fp = fingerprint(rows, kind)
    cached = cache.get(fp)
    if cached:
        ok, _ = validate_mapping(cached, rows, column_count)
        if ok:
            cached = dict(cached)
            cached["cached"] = True
            return cached

    if llm is None:
        return None

    try:
        raw = llm(build_prompt(rows))
    except Exception:  # noqa: BLE001  模型失败就当没有映射
        return None

    mapping = _parse_json(raw)
    ok, problems = validate_mapping(mapping, rows, column_count)
    if not ok:
        return None

    mapping["problems"] = problems
    mapping["fingerprint"] = fp
    mapping["cached"] = False
    cache.put(fp, mapping)
    return mapping
