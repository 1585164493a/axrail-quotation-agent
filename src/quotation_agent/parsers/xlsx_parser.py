"""Excel 解析器：把每个 sheet 切成 标题/文本/表格行 三类块。

难点都在真实文件里：
- 表头不在第一行（上面有合并大标题、买家信息、空行）
- 数量写成 "1,000 pcs"、公差写成 "±0.05 mm"
- 中间夹空行、后面有备注行
- 数据行里的件号可能是文本，也可能是数字（Line 列）

策略：先扫所有行找出表头（命中 ≥3 个列名关键词），表头之上当文本，
表头之下当数据行；遇到连续空行后出现的非数据行，当备注文本。
"""

from __future__ import annotations

from pathlib import Path

from openpyxl import load_workbook

from .base import ParseResult, is_blank_row, looks_like_header, norm_cell, row_dict
from .table_mapper import headers_from_mapping, letter_index


def parse_xlsx(path: str | Path, mapper=None) -> ParseResult:
    """mapper: 可选的结构映射函数（表头认不出来时调用，P1）。"""
    result = ParseResult()
    try:
        wb = load_workbook(path, data_only=True)
    except Exception as exc:  # 文件坏了、不是 xlsx、加密
        return ParseResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    ordinal = 0
    for sheet in wb.worksheets:
        rows = [[c for c in row] for row in sheet.iter_rows(values_only=True)]
        if not rows:
            result.warnings.append(f"empty_sheet: {sheet.title}")
            continue

        header_idx = next(
            (i for i, row in enumerate(rows) if looks_like_header(list(row))),
            None,
        )

        if header_idx is None and mapper is not None:
            # 规则认不出表头：请结构映射帮忙，通过了就按映射取值
            mapping = mapper(rows)
            if mapping:
                headers = headers_from_mapping(mapping)
                header_row = int(mapping.get("header_row") or 1)
                for i, row in enumerate(rows[: header_row - 1], start=1):
                    text = " | ".join(norm_cell(v) for v in row if norm_cell(v))
                    if not text:
                        continue
                    ordinal += 1
                    result.add("title" if i == 1 else "text", f"{sheet.title}!A{i}", ordinal, value=text)

                ordinal += 1
                result.add(
                    "kv",
                    f"{sheet.title}!A{header_row}",
                    ordinal,
                    key="table_header",
                    value=" | ".join(norm_cell(h) for h in headers if norm_cell(h)),
                )
                result.warnings.append(
                    f"mapping_used: {sheet.title} ({'cache' if mapping.get('cached') else 'model'}, "
                    f"confidence {mapping.get('confidence', '?')})"
                )

                # 若映射出来的"件号"只是 1、2、3 这种行号，提醒一句（客户表里可能没给件号）
                part_letter = next(
                    (letter for letter, field in (mapping.get("columns") or {}).items() if field == "part_no"),
                    None,
                )
                if part_letter:
                    part_idx = letter_index(part_letter)
                    samples = [
                        norm_cell(row[part_idx])
                        for row in rows[header_row:header_row + 10]
                        if part_idx < len(row) and norm_cell(row[part_idx])
                    ]
                    if samples and all(s.isdigit() and len(s) <= 3 for s in samples):
                        result.warnings.append(
                            f"part_no_looks_like_row_index: {sheet.title}（表里没有真正的件号）"
                        )

                for i in range(header_row, len(rows)):
                    row = list(rows[i])
                    if is_blank_row(row):
                        continue
                    data = row_dict(headers, row)
                    if not data:
                        continue
                    ordinal += 1
                    result.add("table_row", f"{sheet.title}!A{i + 1}", ordinal, row=data)
                continue

        if header_idx is None:
            # 没有表头、也没有可用映射：退一步用"文本收割"——把整行拼成文字，
            # 按内容特征抓件号/数量/材料/公差（和 OCR 用的是同一套规则）。
            from .ocr_rows import harvest_row

            harvested: list[tuple[int, dict]] = []
            for i, row in enumerate(rows, start=1):
                flat = " | ".join(norm_cell(v) for v in row if norm_cell(v))
                if not flat:
                    continue
                found = harvest_row(flat)
                if found:
                    harvested.append((i, found))

            if harvested:
                result.warnings.append(f"harvest_fallback: {sheet.title} (header not recognised, fields harvested from the text)")
                for index, (row_number, found_row) in enumerate(harvested, start=1):
                    ordinal += 1
                    result.add("table_row", f"{sheet.title}!A{row_number}", ordinal, row=found_row)
                continue

            # 实在抓不到：整表当文本，交给人判断
            result.warnings.append(f"no_table_header: {sheet.title}")
            for i, row in enumerate(rows, start=1):
                text = " | ".join(norm_cell(v) for v in row if norm_cell(v))
                if text:
                    ordinal += 1
                    result.add("text", f"{sheet.title}!A{i}", ordinal, value=text)
            continue

        headers = list(rows[header_idx])

        # 表头之上的内容：标题、买家信息
        for i, row in enumerate(rows[:header_idx], start=1):
            text = " | ".join(norm_cell(v) for v in row if norm_cell(v))
            if not text:
                continue
            ordinal += 1
            result.add("title" if i == 1 else "text", f"{sheet.title}!A{i}", ordinal, value=text)

        # 表头本身也留一条，方便追溯列名从哪来
        ordinal += 1
        result.add(
            "kv",
            f"{sheet.title}!A{header_idx + 1}",
            ordinal,
            key="table_header",
            value=" | ".join(norm_cell(h) for h in headers if norm_cell(h)),
        )

        # 表头之下：数据行与备注
        for i in range(header_idx + 1, len(rows)):
            row = list(rows[i])
            locator = f"{sheet.title}!A{i + 1}"
            if is_blank_row(row):
                continue

            values = [norm_cell(v) for v in row]
            non_empty = [v for v in values if v]
            # 只有一列有内容、且不是数字开头 → 备注行
            if len(non_empty) == 1 and not non_empty[0][:1].isdigit():
                ordinal += 1
                result.add("text", locator, ordinal, value=non_empty[0])
                continue

            data = row_dict(headers, row)
            if not data:
                continue
            ordinal += 1
            result.add("table_row", locator, ordinal, row=data)

    if not result.blocks:
        result.warnings.append("no_blocks: parsed successfully but the file produced no content")
    return result
