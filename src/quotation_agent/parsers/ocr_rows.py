"""从 OCR 出来的"缺标点"文本里抓字段。

OCR 常见问题：逗号丢失、小数点变句点、空格不稳。
所以这里不用"逗号分段"，而是按内容特征独立抓：
    - 件号   XX-123
    - 数量   400 pcs / 150 pieces
    - 公差   tol +/-0.10 mm（到下一个字段前）
    - 质量   0.35 kg / 620 g
    - 工时   5 min
    - 材料   已知牌号（AL6061 / SS304 / Ti Gr5 …）
    - 表面   anodise / none
"""

from __future__ import annotations

import re

PART_RE = re.compile(r"\b([A-Z]{2,6}-\d{2,5})\b")
QTY_RE = re.compile(r"\b(\d[\d,]*)\s*(?:pcs|pc|pieces|units|off)\b", re.IGNORECASE)
TOL_RE = re.compile(r"tol(?:erance)?\s*[:=]?\s*([+\-/0-9.\s]*\d[0-9.]*)", re.IGNORECASE)
MASS_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(kg|g)\b", re.IGNORECASE)
CYCLE_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(?:min|mins|minutes)\b", re.IGNORECASE)
FINISH_RE = re.compile(r"\b(anodis(?:e|ed|ing)|anodiz(?:e|ed|ing)|no finish|none|zinc|powder coat)\b", re.IGNORECASE)
MATERIAL_RE = re.compile(
    r"\b(AL\s?6061(?:-T6)?|6061\s?(?:aluminium|aluminum)?|SS\s?304|SUS\s?304|304\s?stainless|"
    r"Ti\s?Gr\s?5|titanium\s?grade\s?5|AL\s?7075|SS\s?316)\b",
    re.IGNORECASE,
)


def harvest_row(line: str) -> dict | None:
    """一行 OCR 文本 → 规范化字段；没有件号就不算零件行。"""
    text = line.strip()
    part = PART_RE.search(text)
    if not part:
        return None

    row: dict[str, object] = {"Part no": part.group(1).upper()}

    qty = QTY_RE.search(text)
    if qty:
        row["Qty"] = qty.group(1).replace(",", "")

    material = MATERIAL_RE.search(text)
    if material:
        row["Material"] = material.group(1)

    tol = TOL_RE.search(text)
    if tol:
        row["Tolerance (mm)"] = tol.group(1).strip()

    mass = MASS_RE.search(text)
    if mass:
        value = float(mass.group(1))
        if mass.group(2).lower() == "g":
            value = round(value / 1000, 4)
        row["Mass (kg)"] = str(value)

    cycle = CYCLE_RE.search(text)
    if cycle:
        row["Cycle (min)"] = cycle.group(1)

    finish = FINISH_RE.search(text)
    if finish:
        row["Finish"] = finish.group(1)

    # 描述：件号之后、第一个已识别字段之前的文字
    tail = text[part.end():]
    cut = len(tail)
    for match in (QTY_RE.search(tail), MATERIAL_RE.search(tail), TOL_RE.search(tail), MASS_RE.search(tail)):
        if match and match.start() < cut:
            cut = match.start()
    description = re.sub(r"^[\s,.\-–]+", "", tail[:cut]).strip(" ,.-")
    description = re.sub(r"\s{2,}", " ", description)
    if description:
        row["Description"] = description

    return row


def harvest(text_lines: list[str]) -> tuple[list[dict], list[str]]:
    """多行 OCR 文本 → 行列表 + 说明。"""
    rows: list[dict] = []
    warnings: list[str] = []
    for line in text_lines:
        row = harvest_row(line)
        if row:
            rows.append(row)
        elif PART_RE.search(line):
            warnings.append(f"ocr_row_incomplete: {line[:60]}")
    return rows, warnings
