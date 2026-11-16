"""PDF 解析器：抽文字层，识别"字段/值"两列排版与键值对行。

PDF 有三种常见形态，都要照顾到：
1. 原生导出、一行一个字段（"Part no: CVR-310"）→ 直接切 kv；
2. 表格排版：标签一列、值一列，抽出来是交替的两行（"Part no" / "CVR-310"）→ 成对配对；
3. 没有文字层（扫描件）→ 必须明确报 needs_ocr，不能返回空表当没事。
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import ParseResult, parse_kv_line

try:  # pypdf 在项目依赖里；缺了也要给出可理解的错误
    from pypdf import PdfReader
except ImportError:  # pragma: no cover
    PdfReader = None  # type: ignore[assignment]

# 标签长度上限：超过这个长度更像是整句说明，不是字段名
MAX_LABEL_LEN = 40
# 值长度上限：太长说明配错了对，退回去按普通文本处理
MAX_VALUE_LEN = 80


def _is_field_value_header(lines: list[str], i: int) -> bool:
    return (
        i + 1 < len(lines)
        and lines[i].strip().lower() == "field"
        and lines[i + 1].strip().lower() == "value"
    )


def _needs_ocr(page_text: str, structured_blocks: int, has_images: bool, min_chars: int = 20) -> bool:
    """这一页该不该走 OCR。

    三种"结构读不出"的情况（题目里的表头认不出 / 字段覆盖不足 / 行内字段不足）
    在这一页上的表现就是：没有键值对、没有表格行、也没有任何件号。
    """
    if not has_images:
        return False
    if len(page_text) < min_chars:
        return True
    if structured_blocks > 0:
        return False

    from .ocr_rows import PART_RE

    return not PART_RE.search(page_text)


def parse_pdf(path: str | Path) -> ParseResult:
    if PdfReader is None:
        return ParseResult(ok=False, error="pypdf_not_installed")

    result = ParseResult()
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        return ParseResult(ok=False, error=f"{type(exc).__name__}: {exc}")

    ordinal = 0
    text_pages = 0
    total_pages = len(reader.pages)
    pages_without_text: list[int] = []
    page_texts: dict[int, str] = {}
    MIN_TEXT_CHARS = 20  # 少于这个长度基本等于没有文字层（只剩页码/标题）

    for page_no, page in enumerate(reader.pages, start=1):
        try:
            text = page.extract_text() or ""
        except Exception as exc:  # 单页坏了不影响其它页
            result.warnings.append(f"page_extract_failed: page {page_no}: {exc}")
            pages_without_text.append(page_no)
            continue

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        page_texts[page_no] = " ".join(lines)
        if len(" ".join(lines)) < MIN_TEXT_CHARS:
            # 这一页几乎是图：留给 OCR，不要因为"有 3 个字符"就当成有文字层
            pages_without_text.append(page_no)
            continue
        text_pages += 1

        # ---- 形态 2：Field / Value 两列 ----
        header_idx = next((i for i in range(len(lines)) if _is_field_value_header(lines, i)), None)
        consumed = 0
        if header_idx is not None:
            ordinal += 1
            result.add("kv", f"page {page_no} L{header_idx + 1}", ordinal, key="table_header", value="Field | Value")
            j = header_idx + 2
            while j + 1 < len(lines):
                label, value = lines[j], lines[j + 1]
                if len(label) > MAX_LABEL_LEN or len(value) > MAX_VALUE_LEN:
                    break
                ordinal += 1
                result.add("kv", f"page {page_no} L{j + 1}", ordinal, key=label, value=value)
                j += 2
            consumed = j

        # ---- 其余行：按大间距再切分，逐段判定 kv / text ----
        for line_no in range(consumed, len(lines)):
            line = lines[line_no]
            segments = [s.strip() for s in re.split(r"\s{2,}", line) if s.strip()]
            for seg_no, segment in enumerate(segments, start=1):
                ordinal += 1
                locator = f"page {page_no} L{line_no + 1}" + (f"#{seg_no}" if len(segments) > 1 else "")
                kv = parse_kv_line(segment)
                if kv:
                    result.add("kv", locator, ordinal, key=kv[0], value=kv[1])
                else:
                    result.add("text", locator, ordinal, value=segment)

    # 有文字层但"结构读不出"的页（没有键值/表格/件号）也当图读一次
    for page_no in range(1, total_pages + 1):
        if page_no in pages_without_text:
            continue
        try:
            has_images = bool(reader.pages[page_no - 1].images)
        except Exception:  # noqa: BLE001
            has_images = False
        structured = sum(
            1 for b in result.blocks
            if b.get("block_type") in {"kv", "table_row"}
            and str(b.get("locator", "")).startswith(f"page {page_no} ")
        )
        if _needs_ocr(page_texts.get(page_no, ""), structured, has_images):
            pages_without_text.append(page_no)

    # 逐页判断：没有文字层、或结构读不出的页面 → OCR
    if pages_without_text:
        used_ocr, ocr_warnings = _ocr_blocks(
            path, result, ordinal_start=ordinal, pages=set(pages_without_text)
        )
        result.warnings.extend(ocr_warnings)
        if used_ocr:
            result.warnings.append(
                "ocr_pages: " + ", ".join(str(p) for p in sorted(pages_without_text))
                + f" ({total_pages} pages total, {text_pages} with a text layer)"
            )
        else:
            result.warnings.append("needs_ocr: some pages have no text layer and OCR returned nothing; needs manual entry")
    return result


def _ocr_blocks(path: str | Path, result: ParseResult, ordinal_start: int,
                pages: set[int] | None = None) -> tuple[bool, list[str]]:
    """对"没有文字层"的页面做 OCR：逐行文本 + 按内容特征还原零件行。"""
    from .ocr import ocr_pdf
    from .ocr_rows import harvest

    lines, warnings = ocr_pdf(path, pages=pages)
    if not lines:
        return False, warnings

    ordinal = ordinal_start
    text_lines: list[str] = []
    for page_number, text in lines:
        ordinal += 1
        result.add("text", f"page {page_number} ocr", ordinal, value=text)
        text_lines.append(text)

    rows, row_warnings = harvest(text_lines)
    warnings.extend(row_warnings)
    for index, row in enumerate(rows, start=1):
        ordinal += 1
        result.add("table_row", f"ocr line {index}", ordinal, row=row)

    warnings.append(f"ocr_used: {len(text_lines)} lines read by Rekognition, {len(rows)} of them parsed into parts")
    return True, warnings
