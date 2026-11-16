"""附件素材自检：每个文件都能被预期的库读出来，坏文件必须报错。

这不测解析器的业务逻辑（那是第二步），只保证素材本身可用、覆盖到了想覆盖的形态。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ATTACH = Path(__file__).resolve().parent / "fixtures" / "attachments"


class AttachmentFixtureTests(unittest.TestCase):
    def test_all_expected_files_exist_and_are_not_empty(self) -> None:
        expected = [
            "part_list_full.xlsx", "part_list_partial.xlsx", "part_list_messy.xlsx",
            "part_list_empty.xlsx", "part_spec_pair.pptx", "part_spec_notes.pptx",
            "spec_table.docx", "drawing_text.pdf", "drawing_no_text.pdf", "broken.xlsx",
        ]
        for name in expected:
            path = ATTACH / name
            with self.subTest(file=name):
                self.assertTrue(path.exists(), f"缺少素材 {name}")
                self.assertGreater(path.stat().st_size, 0)

    def test_xlsx_variants_have_expected_row_counts(self) -> None:
        from openpyxl import load_workbook

        full = load_workbook(ATTACH / "part_list_full.xlsx").active
        partial = load_workbook(ATTACH / "part_list_partial.xlsx").active
        messy = load_workbook(ATTACH / "part_list_messy.xlsx").active
        empty = load_workbook(ATTACH / "part_list_empty.xlsx").active

        # 满表：标题 2 行 + 空行 + 表头 + 5 行数据 = 9 行
        self.assertEqual(full.max_row, 9)
        self.assertEqual(full.cell(row=4, column=1).value, "Line")
        self.assertEqual(full.cell(row=5, column=5).value, 500)

        # 部分表：只到第 3 行，末尾提示看幻灯片
        self.assertEqual(partial.max_row, 9)
        self.assertIn("see the part-spec slides", str(partial.cell(row=9, column=1).value))

        # 脏表：合并标题 + 表头在第 4 行 + 千分位 + 多余列
        self.assertIn("PURCHASE ENQUIRY", str(messy["A1"].value))
        self.assertEqual(messy.cell(row=4, column=1).value, "Line")
        self.assertEqual(messy.cell(row=5, column=5).value, "500 pcs")
        self.assertEqual(messy.cell(row=7, column=5).value, "1,000 pcs")
        self.assertEqual(messy.max_column, 11)

        # 空表：只有表头
        self.assertEqual(empty.max_row, 1)

    def test_pptx_variants(self) -> None:
        from pptx import Presentation

        pair = Presentation(ATTACH / "part_spec_pair.pptx")
        table = pair.slides[0].shapes[1].table
        self.assertEqual(len(table.rows), 3)  # 表头 + 2 行
        self.assertEqual(table.cell(1, 1).text, "SPC-050")

        notes = Presentation(ATTACH / "part_spec_notes.pptx")
        slide = notes.slides[0]
        self.assertIn("HSG-400", slide.shapes[1].table.cell(1, 0).text)
        # 关键信息在备注里，只读表格会漏掉
        self.assertIn("±0.005", slide.notes_slide.notes_text_frame.text)

    def test_docx_table(self) -> None:
        from docx import Document

        doc = Document(ATTACH / "spec_table.docx")
        self.assertEqual(len(doc.tables), 1)
        table = doc.tables[0]
        self.assertEqual(len(table.rows), 3)  # 表头 + 2 行
        self.assertEqual(table.cell(1, 1).text, "BRK-100")

    def test_pdfs(self) -> None:
        text_pdf = (ATTACH / "drawing_text.pdf").read_bytes()
        blank_pdf = (ATTACH / "drawing_no_text.pdf").read_bytes()

        self.assertTrue(text_pdf.startswith(b"%PDF-1.4"))
        self.assertIn(b"Order quantity: 800 pcs", text_pdf)
        self.assertIn(b"CVR-310", text_pdf)

        self.assertTrue(blank_pdf.startswith(b"%PDF-1.4"))
        # 没有文字层：不能出现任何文字操作符，解析器要据此报 needs_ocr
        self.assertNotIn(b"Tj", blank_pdf)

    def test_broken_xlsx_really_fails_to_load(self) -> None:
        from openpyxl import load_workbook

        with self.assertRaises(Exception):
            load_workbook(ATTACH / "broken.xlsx")


if __name__ == "__main__":
    unittest.main()
