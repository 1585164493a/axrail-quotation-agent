"""邮件正文解析器：把正文里的零件列切成人能核对的行。

真实询价邮件常常在正文里就把零件写全了（题目样例就是），附件只是补充。
所以正文和附件走同一套块结构，只是 locator 变成 "body line N"。

支持的写法（题目样例的形态）：

    1. BRK-100 Mounting bracket, AL6061, 500 pcs, tol +/-0.10 mm, 0.40 kg, approx 6 min, anodise
    - SHF-220 Drive shaft D20x150, SS304, 200 pcs, ...

解析器只负责"切字段"，不做归一化：材料别名、千分位、TBC 都由第三步处理。
"""

from __future__ import annotations

import re

from .base import ParseResult

# "1. BRK-100 ..." / "2) SHF-220 ..." / "- CVR-310 ..."
LINE_RE = re.compile(
    r"^\s*(?:[-*••]|\d+[.)])\s*"
    r"(?P<part>[A-Z]{2,6}-\d{2,5})\s+"
    r"(?P<rest>.+)$"
)

QTY_RE = re.compile(r"(?P<qty>[\d,]+)\s*(?:pcs|pc|件)\b", re.IGNORECASE)
# 公差：把 "tol" 后面到逗号/分号为止的整段都收下来，再交给 values.parse_tolerance 解释
# （能处理 ±0.10、0.004 inch、4 µm、IT7、+0.1/-0.05）
TOL_RE = re.compile(r"tol(?:erance)?\s*[:=]?\s*(?P<tol>[^,;]+?)\s*(?=,|;|$)", re.IGNORECASE)
MASS_RE = re.compile(r"(?P<mass>[\d.]+)\s*(?P<unit>kg|g|gram|grams)\b", re.IGNORECASE)
CYCLE_RE = re.compile(r"(?:approx\s*)?(?P<cycle>[\d.]+)\s*min", re.IGNORECASE)

FINISH_WORDS = ("anodise", "anodize", "anodized", "anodised", "clear anodise")
NO_FINISH_WORDS = ("no finish", "none", "n/a")


def _classify(segment: str) -> tuple[str, str] | None:
    """判断一个逗号分隔的片段属于哪个字段。返回 (字段名, 原值)。"""
    text = segment.strip()
    if not text:
        return None

    lowered = text.lower()

    tolerance = TOL_RE.search(text)
    if tolerance:
        return "Tolerance (mm)", tolerance.group("tol")

    mass = MASS_RE.search(text)
    if mass:
        unit = (mass.group("unit") or "kg").lower()
        value = mass.group("mass")
        # 克要换算成千克，让后续按 kg 计算
        if unit.startswith("g"):
            return "Mass (kg)", str(round(float(value) / 1000, 4))
        return "Mass (kg)", value

    if "min" in lowered:
        cycle = CYCLE_RE.search(text)
        if cycle:
            return "Cycle (min)", cycle.group("cycle")

    qty = QTY_RE.search(text)
    if qty:
        return "Qty", qty.group("qty")

    if any(word in lowered for word in NO_FINISH_WORDS):
        return "Finish", "None"
    if any(word in lowered for word in FINISH_WORDS):
        return "Finish", "Anodise"

    # 剩下的短片段当材料（AL6061 / SS304 / Ti Gr5 …）
    if len(text) <= 20 and not text[0].isdigit():
        return "Material", text
    return None


def parse_body(text: str) -> ParseResult:
    """把正文按行切块。没有零件行时返回空结果 + 告警，不抛异常。"""
    result = ParseResult()
    if not text:
        result.warnings.append("body_empty: the email has no text body")
        return result

    ordinal = 0
    for line_no, line in enumerate(text.splitlines(), start=1):
        match = LINE_RE.match(line)
        if not match:
            continue

        part_no = match.group("part").strip()
        rest = match.group("rest")

        # 第一段是描述，其余片段按字段归类。
        # 注意：按逗号切时要跳过千分位（"1,000 pcs" 里的逗号后面紧跟数字）
        segments = [s.strip() for s in re.split(r",(?!\d)", rest) if s.strip()]
        row: dict[str, str] = {"Part no": part_no}
        if segments:
            row["Description"] = segments[0]
        for segment in segments[1:]:
            classified = _classify(segment)
            if classified and classified[0] not in row:
                row[classified[0]] = classified[1]

        ordinal += 1
        result.add("table_row", f"body line {line_no}", ordinal, row=row)

    if not result.blocks:
        result.warnings.append("no_line_items_in_body: no part lines found in the email body")
    return result
