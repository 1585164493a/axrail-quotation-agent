"""Word 解析器：按文档顺序处理段落与表格。

python-docx 的 body 里段落和表格是混着排的，这里按 XML 顺序遍历，
保证"第几张表第几行"的出处和人在 Word 里看到的一致。
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.table import Table
from docx.text.paragraph import Paragraph

from .base import ParseResult, norm_cell, parse_kv_line


def _iter_body(doc):
    """按文档顺序产出 Paragraph / Table。"""
    body = doc.element.body
    for child in body.iterchildren():
        if child.tag.endswith("}p"):
            yield Paragraph(child, doc)
        elif child.tag.endswith("}tbl"):
            yield Table(child, doc)


def parse_docx(path: str | Path) -> ParseResult:
    result = ParseResult()
    try:
        doc = Document(path)
    except Exception as exc:
        return ParseResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    ordinal = 0
    table_no = 0
    para_no = 0

    for item in _iter_body(doc):
        if isinstance(item, Paragraph):
            para_no += 1
            text = item.text.strip()
            if not text:
                continue
            ordinal += 1
            kv = parse_kv_line(text)
            if kv:
                result.add("kv", f"para {para_no}", ordinal, key=kv[0], value=kv[1])
            elif item.style is not None and item.style.name.lower().startswith("heading"):
                result.add("title", f"para {para_no}", ordinal, value=text)
            else:
                result.add("text", f"para {para_no}", ordinal, value=text)
            continue

        table_no += 1
        rows = item.rows
        if not rows:
            continue
        headers = [norm_cell(c.text) for c in rows[0].cells]
        ordinal += 1
        result.add(
            "kv", f"table {table_no} header", ordinal,
            key="table_header", value=" | ".join(h for h in headers if h),
        )
        for r_idx, row in enumerate(rows[1:], start=2):
            data = {}
            for i, cell in enumerate(row.cells):
                name = headers[i] if i < len(headers) else f"col{i + 1}"
                text = norm_cell(cell.text)
                if name and text:
                    data[name] = text
            if data:
                ordinal += 1
                result.add("table_row", f"table {table_no} row{r_idx}", ordinal, row=data)

    if not result.blocks:
        result.warnings.append("no_blocks: parsed successfully but the file produced no content")
    return result
