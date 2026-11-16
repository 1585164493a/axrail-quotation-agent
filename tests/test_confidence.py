"""可信度打分与冲突处理。

题目要求 "flag anything a person must check"，所以这里钉住三件事：
1. 多来源一致 → 高分；
2. 多来源矛盾 → 0.30 + 冲突 + 该行必须人工确认，且**取结构化附件那份值**；
3. 关键字段缺失 → 0.40 + 标记（信息不全，不是矛盾）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quotation_agent.quote.confidence import score_field, source_kind, weight_of  # noqa: E402
from quotation_agent.quote.normalise import candidates_from_blocks, merge  # noqa: E402


def block(filename: str, locator: str, row: dict) -> dict:
    return {"filename": filename, "block_type": "table_row", "locator": locator, "ordinal": 1, "row": row}


class ConfidenceUnitTests(unittest.TestCase):
    def test_source_kind_and_weight(self) -> None:
        self.assertEqual(source_kind("part_list.xlsx @ Part list!A5"), "xlsx")
        self.assertEqual(source_kind("drawing.pdf @ page 1 L13"), "pdf")
        self.assertEqual(source_kind("email body @ body line 6"), "body")
        self.assertEqual(source_kind("email body @ llm line 1"), "llm")
        self.assertGreater(weight_of("a.xlsx @ x"), weight_of("b.pdf @ y"))
        self.assertGreater(weight_of("b.pdf @ y"), weight_of("email body @ body line 1"))
        self.assertGreater(weight_of("email body @ body line 1"), weight_of("email body @ llm line 1"))

    def test_agreement_is_high(self) -> None:
        score, status = score_field([(500, "a.xlsx @ A5"), (500, "email body @ body line 6")])
        self.assertEqual(status, "agreed")
        self.assertGreaterEqual(score, 0.9)

    def test_same_document_is_not_two_sources(self) -> None:
        """正文被正则和模型各读一遍，仍然算一份文件——模型重读不是佐证。"""
        score, status = score_field([(500, "email body @ body line 6"), (500, "email body @ llm line 1")])
        self.assertEqual(status, "single")
        self.assertEqual(score, 0.60)

    def test_two_attachments_agreeing_boost(self) -> None:
        score, _ = score_field([(500, "part_list.xlsx @ A5"), (500, "drawing.pdf @ page 1")])
        self.assertEqual(score, 0.95)

    def test_conflict_is_low(self) -> None:
        score, status = score_field([(1000, "a.xlsx @ A5"), (800, "b.pdf @ page 1")])
        self.assertEqual(status, "conflict")
        self.assertEqual(score, 0.3)

    def test_missing_is_flagged(self) -> None:
        score, status = score_field([])
        self.assertEqual(status, "missing")
        self.assertEqual(score, 0.4)


class ConfidenceMergeTests(unittest.TestCase):
    def test_two_sources_agree_gives_high_confidence(self) -> None:
        blocks = [
            block("email body", "body line 1", {"Part no": "BRK-100", "Material": "AL6061", "Qty": "500",
                                                "Tolerance (mm)": "+/-0.10", "Mass (kg)": "0.4", "Cycle (min)": "6"}),
            block("part_list.xlsx", "Part list!A5", {"Part no": "BRK-100", "Material": "AL6061", "Qty": "500",
                                                     "Tolerance (mm)": "+/-0.10", "Mass (kg)": "0.4", "Cycle (min)": "6"}),
        ]
        rfq = merge(candidates_from_blocks(blocks), rfq_no="RFQ-1", customer="X")
        line = rfq.line_by_part("BRK-100")
        self.assertGreaterEqual(line.confidence, 0.9)
        self.assertEqual(line.confidence_label, "high")
        self.assertEqual(rfq.conflicts, [])
    def test_conflict_is_flagged_and_structured_source_wins(self) -> None:
        """正文说 500，xlsx 说 480 → 记冲突、可信度低、取值用 xlsx（结构化附件更权威）。"""
        blocks = [
            block("email body", "body line 1", {"Part no": "BRK-100", "Material": "AL6061", "Qty": "500",
                                                "Tolerance (mm)": "+/-0.10"}),
            block("part_list.xlsx", "Part list!A5", {"Part no": "BRK-100", "Material": "AL6061", "Qty": "480",
                                                     "Tolerance (mm)": "+/-0.10"}),
        ]
        rfq = merge(candidates_from_blocks(blocks), rfq_no="RFQ-1", customer="X")
        line = rfq.line_by_part("BRK-100")

        self.assertEqual([c.field_name for c in rfq.conflicts], ["qty"])
        self.assertEqual(line.qty, 480)  # 结构化附件优先
        self.assertLess(line.confidence, 0.55)
        self.assertEqual(line.confidence_label, "low")
        self.assertTrue(any("qty" in flag for flag in line.flags))

    def test_conflict_between_two_attachments(self) -> None:
        """xlsx 与 pdf 打架（题目样例里的 1000 vs 800）。"""
        blocks = [
            block("part_list.xlsx", "Part list!A7", {"Part no": "CVR-310", "Material": "AL6061", "Qty": "1000",
                                                     "Tolerance (mm)": "+/-0.05"}),
            block("drawing_CVR-310.pdf", "page 1 L13", {"Part no": "CVR-310", "Qty": "800"}),
        ]
        rfq = merge(candidates_from_blocks(blocks), rfq_no="RFQ-1", customer="X")
        line = rfq.line_by_part("CVR-310")

        self.assertEqual(line.qty, 1000)  # xlsx 权重高于 pdf
        self.assertLess(line.confidence, 0.65)
        conflict = rfq.conflicts[0]
        self.assertEqual(conflict.field_name, "qty")
        self.assertIn("1000", conflict.describe())
        self.assertIn("800", conflict.describe())

    def test_missing_quantity_is_low_confidence(self) -> None:
        blocks = [block("email body", "body line 1", {"Part no": "SPC-050", "Material": "SS304",
                                                      "Qty": "TBC", "Tolerance (mm)": "+/-0.10"})]
        rfq = merge(candidates_from_blocks(blocks), rfq_no="RFQ-1", customer="X")
        line = rfq.line_by_part("SPC-050")

        self.assertIsNone(line.qty)
        self.assertEqual(line.confidence_label, "low")
        self.assertTrue(any("qty" in flag for flag in line.flags))


if __name__ == "__main__":
    unittest.main()
