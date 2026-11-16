"""扫描件与图片的 OCR（用假的 Rekognition 客户端，不联网）。

真实情况：Textract 在本账号被 SCP 拒绝，Rekognition DetectText 可用，
所以 OCR 后端是 Rekognition。这里验证：能还原零件行、低置信度被丢弃、
OCR 失败时仍保留 needs_ocr 警告（不能假装读到了）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quotation_agent.parsers import ocr  # noqa: E402
from quotation_agent.parsers import dispatch  # noqa: E402

SCAN_PDF = ROOT / "tests" / "fixtures" / "attachments" / "scan_plate.pdf"
SCAN_PNG = ROOT / "tests" / "fixtures" / "attachments" / "scan_plate.png"
MIXED_PDF = ROOT / "tests" / "fixtures" / "attachments" / "mixed_text_and_scan.pdf"
TEXT_PDF = ROOT / "tests" / "fixtures" / "attachments" / "drawing_CVR-310_RevB.pdf"
NO_HEADER_XLSX = ROOT / "tests" / "fixtures" / "attachments" / "part_list_no_header.xlsx"

LINES = [
    ("PURCHASE REQUEST - SCAN", 99.0, 0.05),
    ("1. SCN-100 Bracket, AL6061, 400 pcs, tol +/-0.10 mm, 0.35 kg, approx 5 min, anodise", 98.0, 0.20),
    ("2. SCN-200 Shaft, SS304, 150 pcs, tol +/-0.02 mm, 0.50 kg, approx 7 min, no finish", 97.0, 0.40),
    ("blurry footnote", 35.0, 0.90),
]


class FakeRekognition:
    def __init__(self, lines=None, error: Exception | None = None) -> None:
        self.lines = lines if lines is not None else LINES
        self.error = error
        self.calls = 0

    def detect_text(self, Image):  # noqa: N803
        self.calls += 1
        if self.error:
            raise self.error
        return {"TextDetections": [
            {
                "Type": "LINE",
                "DetectedText": text,
                "Confidence": confidence,
                "Geometry": {"BoundingBox": {"Top": top, "Left": 0.05}},
            }
            for text, confidence, top in self.lines
        ]}


class ScannedPdfTests(unittest.TestCase):
    def test_ocr_recovers_part_lines(self) -> None:
        fake = FakeRekognition()
        with mock.patch.object(ocr, "_default_client", return_value=fake):
            result = dispatch(SCAN_PDF)

        rows = [b["row"] for b in result.blocks if b.get("row")]
        self.assertEqual([row["Part no"] for row in rows], ["SCN-100", "SCN-200"])
        self.assertEqual(rows[0]["Qty"], "400")
        self.assertTrue(any("ocr_used" in w for w in result.warnings), result.warnings)
        self.assertFalse(any("needs_ocr" in w for w in result.warnings))

    def test_low_confidence_lines_are_dropped(self) -> None:
        fake = FakeRekognition()
        with mock.patch.object(ocr, "_default_client", return_value=fake):
            result = dispatch(SCAN_PDF)
        texts = [b.get("value", "") for b in result.blocks if b.get("block_type") == "text"]
        self.assertNotIn("blurry footnote", texts)

    def test_ocr_failure_keeps_needs_ocr_warning(self) -> None:
        fake = FakeRekognition(error=RuntimeError("AccessDeniedException"))
        with mock.patch.object(ocr, "_default_client", return_value=fake):
            result = dispatch(SCAN_PDF)

        self.assertEqual([b for b in result.blocks if b.get("row")], [])
        self.assertTrue(any("ocr_failed" in w for w in result.warnings), result.warnings)
        self.assertTrue(any("needs_ocr" in w for w in result.warnings), result.warnings)

    def test_pdf_without_images_reports_clearly(self) -> None:
        with mock.patch.object(ocr, "pdf_page_images", return_value=[]):
            result = dispatch(SCAN_PDF)
        self.assertTrue(any("ocr_no_images" in w for w in result.warnings), result.warnings)


class ImageAttachmentTests(unittest.TestCase):
    def test_png_attachment_is_ocred(self) -> None:
        fake = FakeRekognition()
        with mock.patch.object(ocr, "_default_client", return_value=fake):
            result = dispatch(SCAN_PNG)

        rows = [b["row"] for b in result.blocks if b.get("row")]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]["Material"], "SS304")

    def test_image_failure_is_reported(self) -> None:
        fake = FakeRekognition(error=RuntimeError("throttled"))
        with mock.patch.object(ocr, "_default_client", return_value=fake):
            result = dispatch(SCAN_PNG)
        self.assertTrue(any("ocr_failed" in w for w in result.warnings), result.warnings)


class OcrRowHarvestTests(unittest.TestCase):
    """OCR 丢标点时仍要能把字段抓全（真实 Rekognition 输出就是这样）。"""

    def test_missing_commas_still_yields_all_fields(self) -> None:
        from quotation_agent.parsers.ocr_rows import harvest_row

        row = harvest_row(
            "1. SCN-100 Bracket AL6061, 400 pcs tol +/-0.10 mm, 0.35 kg, approx 5 min, anodise"
        )
        self.assertEqual(row["Part no"], "SCN-100")
        self.assertEqual(row["Qty"], "400")
        self.assertEqual(row["Material"], "AL6061")
        self.assertEqual(row["Tolerance (mm)"], "+/-0.10")
        self.assertEqual(row["Mass (kg)"], "0.35")
        self.assertEqual(row["Cycle (min)"], "5")
        self.assertEqual(row["Description"], "Bracket")

    def test_line_without_part_number_is_not_a_row(self) -> None:
        from quotation_agent.parsers.ocr_rows import harvest_row

        self.assertIsNone(harvest_row("PURCHASE REQUEST-SCAN"))

    def test_grams_are_converted(self) -> None:
        from quotation_agent.parsers.ocr_rows import harvest_row

        row = harvest_row("9. ABC-900 Pin SS304 1200 pcs 620 g 3 min")
        self.assertEqual(row["Mass (kg)"], "0.62")
        self.assertEqual(row["Qty"], "1200")


class MixedDocumentTests(unittest.TestCase):
    """一份 PDF 里既有文字页也有扫描页：只对扫描页调 OCR。"""

    def test_only_pages_without_text_are_ocred(self) -> None:
        fake = FakeRekognition(lines=[
            ("1. MIX-500 Cover, AL6061, 600 pcs, tol +/-0.10 mm, 0.40 kg, 4 min, anodise", 99.0, 0.2),
        ])
        with mock.patch.object(ocr, "_default_client", return_value=fake):
            result = dispatch(MIXED_PDF)

        self.assertTrue(any("ocr_pages: 2" in w for w in result.warnings), result.warnings)
        self.assertEqual(fake.calls, 1, "只应给扫描页调一次 OCR")
        rows = [b["row"] for b in result.blocks if b.get("row")]
        self.assertEqual([row["Part no"] for row in rows], ["MIX-500"])
        # 第 1 页的文字仍然由文字层提供
        texts = " ".join(b.get("value", "") for b in result.blocks if b.get("block_type") == "text")
        self.assertIn("PAGE 1", texts)

    def test_text_only_pdf_never_calls_ocr(self) -> None:
        fake = FakeRekognition()
        with mock.patch.object(ocr, "_default_client", return_value=fake):
            dispatch(TEXT_PDF)
        self.assertEqual(fake.calls, 0)


class StructureFallbackTests(unittest.TestCase):
    """结构读不出时的兜底：xlsx 走文本收割，PDF 走 OCR。"""

    def test_headerless_xlsx_uses_text_harvest(self) -> None:
        result = dispatch(NO_HEADER_XLSX)
        rows = [b["row"] for b in result.blocks if b.get("row")]
        self.assertEqual([row["Part no"] for row in rows], ["VLV-2010", "VLV-2012"])
        self.assertEqual(rows[0]["Qty"], "250")
        self.assertTrue(any("harvest_fallback" in w for w in result.warnings), result.warnings)

    def test_ocr_trigger_rules(self) -> None:
        from quotation_agent.parsers.pdf_parser import _needs_ocr

        # 有图、文字太少 → OCR
        self.assertTrue(_needs_ocr("title", 0, True))
        # 有图、有结构 → 不 OCR
        self.assertFalse(_needs_ocr("Part no | Qty | 500 pcs", 3, True))
        # 有图、无结构、无件号 → OCR（表头认不出/字段覆盖不足的表现）
        self.assertTrue(_needs_ocr("PURCHASE REQUEST please see attached drawing", 0, True))
        # 有图、无结构、但有件号 → 不 OCR
        self.assertFalse(_needs_ocr("1. VLV-2010 Valve body, SS304, 250 pcs", 0, True))
        # 没有图 → 永远不 OCR（矢量文字页无从 OCR）
        self.assertFalse(_needs_ocr("title", 0, False))


if __name__ == "__main__":
    unittest.main()
