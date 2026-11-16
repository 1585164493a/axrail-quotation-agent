"""图片附件（扫描件拍照、截图）解析：OCR 成文本，再尝试还原零件行。"""

from __future__ import annotations

from pathlib import Path

from .base import ParseResult
from .ocr import ocr_image


def parse_image(path: str | Path, client=None) -> ParseResult:
    result = ParseResult()
    lines, warnings = ocr_image(path, client=client)
    result.warnings.extend(warnings)
    if not lines:
        result.warnings.append("ocr_empty: no text found in the image (blurry photo, or a pure graphic)")
        return result

    from .ocr_rows import harvest

    ordinal = 0
    for line in lines:
        ordinal += 1
        result.add("text", f"image ocr L{ordinal}", ordinal, value=line)

    rows, row_warnings = harvest(lines)
    result.warnings.extend(row_warnings)
    for index, row in enumerate(rows, start=1):
        ordinal += 1
        result.add("table_row", f"image ocr row {index}", ordinal, row=row)

    result.warnings.append(f"ocr_used: {len(lines)} lines read by Rekognition, {len(rows)} of them parsed into parts")
    return result
