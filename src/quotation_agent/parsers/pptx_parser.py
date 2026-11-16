"""PowerPoint 解析器：幻灯片标题、表格行、正文段落、**演讲者备注**。

备注容易被忽略，但真实客户常把关键约束写在备注里
（样例里 "review the tolerance" 就在备注）。
"""

from __future__ import annotations

from pathlib import Path

from pptx import Presentation

from .base import ParseResult, norm_cell


def parse_pptx(path: str | Path) -> ParseResult:
    result = ParseResult()
    try:
        prs = Presentation(path)
    except Exception as exc:
        return ParseResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    ordinal = 0
    for slide_no, slide in enumerate(prs.slides, start=1):
        loc = f"slide {slide_no}"

        # 标题
        if slide.shapes.title is not None and slide.shapes.title.has_text_frame:
            title = slide.shapes.title.text_frame.text.strip()
            if title:
                ordinal += 1
                result.add("title", f"{loc} title", ordinal, value=title)

        # 表格与正文
        for shape_no, shape in enumerate(slide.shapes, start=1):
            if getattr(shape, "has_table", False) and shape.has_table:
                table = shape.table
                all_rows = list(table.rows)
                headers = [norm_cell(c.text) for c in all_rows[0].cells]
                ordinal += 1
                result.add(
                    "kv", f"{loc} table{shape_no} header", ordinal,
                    key="table_header", value=" | ".join(h for h in headers if h),
                )
                for r_idx, row in enumerate(all_rows[1:], start=2):
                    cells = [c.text for c in row.cells]
                    data = {}
                    for i, cell_text in enumerate(cells):
                        name = headers[i] if i < len(headers) else f"col{i + 1}"
                        text = norm_cell(cell_text)
                        if name and text:
                            data[name] = text
                    if data:
                        ordinal += 1
                        result.add("table_row", f"{loc} table{shape_no} row{r_idx}", ordinal, row=data)
                continue

            if getattr(shape, "has_text_frame", False) and shape.has_text_frame:
                text = shape.text_frame.text.strip()
                if text and (slide.shapes.title is None or shape != slide.shapes.title):
                    for line_no, line in enumerate(text.splitlines(), start=1):
                        line = line.strip()
                        if not line:
                            continue
                        ordinal += 1
                        result.add("text", f"{loc} shape{shape_no} L{line_no}", ordinal, value=line)

        # 演讲者备注
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
            if notes:
                for line_no, line in enumerate(notes.splitlines(), start=1):
                    line = line.strip()
                    if not line:
                        continue
                    ordinal += 1
                    result.add("text", f"{loc} notes L{line_no}", ordinal, value=line)

    if not result.blocks:
        result.warnings.append("no_blocks: parsed successfully but the file produced no content")
    return result
