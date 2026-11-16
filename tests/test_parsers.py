"""解析器测试：对着 tests/fixtures/attachments 下的真实素材跑。

关注三件事：
1. 能不能读出内容（而不是"解析成功但 0 块"）；
2. 读出来的块有没有出处（locator）；
3. 读不出来的时候，有没有明确告警（needs_ocr / failed），而不是静默返回空。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.parsers import dispatch  # noqa: E402
from quotation_agent.parsers.xlsx_parser import parse_xlsx  # noqa: E402

ATTACH = Path(__file__).resolve().parent / "fixtures" / "attachments"


def rows(result) -> list[dict]:
    return [b["row"] for b in result.blocks if b["block_type"] == "table_row"]


def kv(result) -> dict[str, str]:
    return {b["key"]: b["value"] for b in result.blocks if b["block_type"] == "kv"}


class XlsxParserTests(unittest.TestCase):
    def test_full_table_gives_five_rows(self) -> None:
        result = parse_xlsx(ATTACH / "part_list_full.xlsx")
        self.assertTrue(result.ok)
        table = rows(result)
        self.assertEqual(len(table), 5)
        self.assertEqual(table[0]["Part no"], "BRK-100")
        self.assertEqual(table[0]["Qty"], 500)
        self.assertEqual(table[1]["Tolerance (mm)"], "±0.02")

    def test_every_block_has_locator(self) -> None:
        result = parse_xlsx(ATTACH / "part_list_full.xlsx")
        for block in result.blocks:
            self.assertTrue(block["locator"], block)
            self.assertIn("!", block["locator"])  # 形如 Sheet!A5

    def test_messy_sheet_still_finds_header_and_rows(self) -> None:
        """表头在第 4 行、数量带千分位：仍要抽出 5 行。"""
        result = parse_xlsx(ATTACH / "part_list_messy.xlsx")
        table = rows(result)
        self.assertEqual(len(table), 5)
        self.assertEqual(table[0]["Part no"], "BRK-100")
        # 脏数据保留原样，由第三步归一化，解析器不改写
        self.assertEqual(table[0]["Qty"], "500 pcs")
        self.assertEqual(table[2]["Qty"], "1,000 pcs")
        self.assertEqual(table[2]["Remark"], "qty check with drawing")

    def test_partial_sheet_keeps_pointer_note(self) -> None:
        """只有 3 行 + 一句"看幻灯片"：备注要作为文本块保留。"""
        result = parse_xlsx(ATTACH / "part_list_partial.xlsx")
        self.assertEqual(len(rows(result)), 3)
        texts = " ".join(b["value"] for b in result.blocks if b["block_type"] == "text")
        self.assertIn("see the part-spec slides", texts)

    def test_empty_sheet_reports_no_rows(self) -> None:
        result = parse_xlsx(ATTACH / "part_list_empty.xlsx")
        self.assertTrue(result.ok)
        self.assertEqual(rows(result), [])
        self.assertIn("table_header", kv(result))

    def test_broken_file_fails_loudly(self) -> None:
        result = parse_xlsx(ATTACH / "broken.xlsx")
        self.assertFalse(result.ok)
        self.assertTrue(result.error)


class PptxParserTests(unittest.TestCase):
    def test_pair_slide_table(self) -> None:
        result = dispatch(ATTACH / "part_spec_pair.pptx")
        self.assertTrue(result.ok)
        table = rows(result)
        self.assertEqual(len(table), 2)
        self.assertEqual(table[0]["Part no"], "SPC-050")
        self.assertEqual(table[1]["Part no"], "HSG-400")
        self.assertTrue(any(b["block_type"] == "title" for b in result.blocks))

    def test_speaker_notes_are_captured(self) -> None:
        """关键公差写在备注里：只读表格会漏，备注必须抓。"""
        result = dispatch(ATTACH / "part_spec_notes.pptx")
        notes = [b for b in result.blocks if "notes" in b["locator"]]
        self.assertTrue(notes, "备注没有被抽取")
        joined = " ".join(b["value"] for b in notes)
        self.assertIn("±0.005", joined)


class DocxParserTests(unittest.TestCase):
    def test_word_table(self) -> None:
        result = dispatch(ATTACH / "spec_table.docx")
        self.assertTrue(result.ok)
        table = rows(result)
        self.assertEqual(len(table), 2)
        self.assertEqual(table[0]["Part no"], "BRK-100")
        titles = [b["value"] for b in result.blocks if b["block_type"] == "title"]
        self.assertTrue(any("Part specification" in t for t in titles))


class PdfParserTests(unittest.TestCase):
    def test_text_pdf_gives_kv_and_text(self) -> None:
        result = dispatch(ATTACH / "drawing_text.pdf")
        self.assertTrue(result.ok)
        pairs = kv(result)
        self.assertEqual(pairs.get("Part no"), "CVR-310")
        self.assertEqual(pairs.get("Order quantity"), "800 pcs")
        self.assertEqual(pairs.get("Drawing rev"), "B")

    def test_pdf_without_text_layer_asks_for_ocr(self) -> None:
        result = dispatch(ATTACH / "drawing_no_text.pdf")
        self.assertEqual(result.blocks, [])
        combined = " ".join(result.warnings)
        self.assertIn("needs_ocr", combined)

    def test_real_sample_drawing_field_value_layout(self) -> None:
        """题目原样例的 PDF：标签一列、值一列，抽出来是交替两行，必须配对成 kv。"""
        result = dispatch(ATTACH / "drawing_CVR-310_RevB.pdf")
        self.assertTrue(result.ok)
        pairs = kv(result)
        self.assertEqual(pairs.get("Part no"), "CVR-310")
        self.assertEqual(pairs.get("Order quantity"), "800 pcs")
        self.assertEqual(pairs.get("Drawing rev"), "B")
        self.assertEqual(pairs.get("Customer RFQ"), "RFQ-2026-118")


class DispatchTests(unittest.TestCase):
    def test_unknown_extension_is_rejected_clearly(self) -> None:
        result = dispatch(ATTACH / "part_list_full.xlsx".replace(".xlsx", ".xyz"))
        self.assertFalse(result.ok)
        self.assertIn("unsupported_format", result.error)


if __name__ == "__main__":
    unittest.main()
