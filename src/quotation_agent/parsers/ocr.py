"""扫描件 / 图片的 OCR：把"没有文字层"的文件也读成文本。

为什么用 Rekognition DetectText 而不是 Textract：
- Textract 在这个账号被 SCP 明确拒绝（AccessDeniedException: explicit deny）;
- Rekognition DetectText 可用，按行返回文本 + 置信度，足够还原零件行。

边界：
- OCR 只还原文字，**不解释图表语义**（柱状图里的数值不会被推断）；
- 置信度过低的文字直接丢弃，宁可少读也不猜；
- 读不到就保持 needs_ocr 警告，交给人工。
"""

from __future__ import annotations

from pathlib import Path

MIN_CONFIDENCE = 80.0


def _default_client():
    import os

    import boto3

    return boto3.client("rekognition", region_name=os.environ.get("AWS_REGION", "ap-southeast-2"))


def binary_image(data: bytes, min_confidence: float = MIN_CONFIDENCE, client=None) -> list[str]:
    """一张图片 → 文本行（按从上到下、从左到右排序）。"""
    client = client or _default_client()
    response = client.detect_text(Image={"Bytes": data})
    detections = [
        d for d in response.get("TextDetections", [])
        if d.get("Type") == "LINE" and float(d.get("Confidence", 0)) >= min_confidence
    ]
    detections.sort(key=lambda d: (d.get("Geometry", {}).get("BoundingBox", {}).get("Top", 0),
                                   d.get("Geometry", {}).get("BoundingBox", {}).get("Left", 0)))
    return [d["DetectedText"].strip() for d in detections if d.get("DetectedText", "").strip()]


def pdf_page_images(path: str | Path) -> list[tuple[int, bytes]]:
    """从 PDF 里取出每页内嵌的图片（扫描件通常一页一张图）。"""
    from pypdf import PdfReader

    images: list[tuple[int, bytes]] = []
    reader = PdfReader(str(path))
    for page_number, page in enumerate(reader.pages, start=1):
        try:
            for image in page.images:
                images.append((page_number, image.data))
        except Exception:  # noqa: BLE001  某些页没有图片或格式特殊
            continue
    return images


def ocr_pdf(path: str | Path, pages: set[int] | None = None, client=None,
            min_confidence: float = MIN_CONFIDENCE) -> tuple[list[tuple[int, str]], list[str]]:
    """扫描版 PDF → [(页码, 文本行)], 警告。

    pages: 只 OCR 这些页（1-based）；None 表示全部。
    """
    warnings: list[str] = []
    all_pages = pdf_page_images(path)
    if pages is not None:
        all_pages = [(number, data) for number, data in all_pages if number in pages]
    if not all_pages:
        warnings.append("ocr_no_images: this PDF has no extractable image (vector art or a chart)")
        return [], warnings

    lines: list[tuple[int, str]] = []
    try:
        for page_number, data in all_pages:
            for text in binary_image(data, min_confidence=min_confidence, client=client):
                lines.append((page_number, text))
    except Exception as exc:  # noqa: BLE001  OCR 服务不可用时不要拖垮解析
        warnings.append(f"ocr_failed: {type(exc).__name__}: {str(exc)[:120]}")
        return [], warnings
    return lines, warnings


def ocr_image(path: str | Path, client=None, min_confidence: float = MIN_CONFIDENCE) -> tuple[list[str], list[str]]:
    """单张图片文件 → 文本行, 警告。"""
    data = Path(path).read_bytes()
    try:
        return binary_image(data, min_confidence=min_confidence, client=client), []
    except Exception as exc:  # noqa: BLE001
        return [], [f"ocr_failed: {type(exc).__name__}: {str(exc)[:120]}"]


def lines_to_text(lines: list[tuple[int, str]] | list[str]) -> str:
    """把 OCR 行拼成可被正文解析器处理的文本。"""
    if lines and isinstance(lines[0], tuple):
        return "\n".join(f"{text}" for _page, text in lines)  # type: ignore[misc]
    return "\n".join(str(line) for line in lines)
