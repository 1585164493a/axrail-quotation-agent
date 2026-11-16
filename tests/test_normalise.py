"""归一化测试：跨文件合并、冲突检测、脏值解析。

用真实的块形态（表格行 + 图纸键值对）验证同一件号能不能合到一起、
数量不一致时会不会被抓住。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.quote.normalise import (  # noqa: E402
    candidates_from_blocks,
    merge,
    parse_finish,
    parse_material,
    parse_qty,
    parse_tol,
)


class ValueParsingTests(unittest.TestCase):
    def test_qty_variants(self) -> None:
        self.assertEqual(parse_qty(500), 500)
        self.assertEqual(parse_qty("1,000 pcs"), 1000)
        self.assertEqual(parse_qty("50"), 50)
        self.assertIsNone(parse_qty("TBC"))
        self.assertIsNone(parse_qty("to follow"))
        self.assertIsNone(parse_qty("待定"))
        self.assertIsNone(parse_qty(""))

    def test_tolerance_variants(self) -> None:
        self.assertAlmostEqual(parse_tol("±0.10 mm"), 0.10)
        self.assertAlmostEqual(parse_tol("+/-0.02"), 0.02)
        self.assertAlmostEqual(parse_tol("±0.005"), 0.005)
        self.assertAlmostEqual(parse_tol(0.05), 0.05)

    def test_material_aliases(self) -> None:
        self.assertEqual(parse_material("AL6061")[0], "AL6061")
        self.assertEqual(parse_material("6061")[0], "AL6061")
        self.assertEqual(parse_material("AL 6061")[0], "AL6061")
        self.assertEqual(parse_material("SS304")[0], "SS304")
        self.assertEqual(parse_material("Ti Gr5")[0], "Ti Gr5")

    def test_finish_aliases(self) -> None:
        self.assertEqual(parse_finish("Anodise")[0], "anodise")
        self.assertEqual(parse_finish("Clear anodise")[0], "anodise")
        self.assertEqual(parse_finish("None")[0], "none")
        self.assertEqual(parse_finish("")[0], "none")


def blocks() -> list[dict]:
    """模拟一封邮件里：Excel 三行 + 图纸的键值对。"""
    return [
        {"filename": "part_list.xlsx", "block_type": "kv", "locator": "Part list!A4",
         "key": "table_header", "value": "Line | Part no | Qty", "row": None},
        {"filename": "part_list.xlsx", "block_type": "table_row", "locator": "Part list!A5",
         "key": None, "value": None,
         "row": {"Line": 1, "Part no": "BRK-100", "Description": "Mounting bracket", "Material": "AL6061",
                 "Qty": 500, "Tolerance (mm)": "±0.10", "Mass (kg)": 0.4, "Cycle (min)": 6, "Finish": "Anodise"}},
        {"filename": "part_list.xlsx", "block_type": "table_row", "locator": "Part list!A7",
         "key": None, "value": None,
         "row": {"Line": 3, "Part no": "CVR-310", "Description": "Pump cover", "Material": "AL6061",
                 "Qty": "1,000 pcs", "Tolerance (mm)": "±0.05 mm", "Mass (kg)": 0.85,
                 "Cycle (min)": 12, "Finish": "Anodise"}},
        {"filename": "drawing_CVR-310_RevB.pdf", "block_type": "kv", "locator": "page 1 L5",
         "key": "Part no", "value": "CVR-310", "row": None},
        {"filename": "drawing_CVR-310_RevB.pdf", "block_type": "kv", "locator": "page 1 L13",
         "key": "Order quantity", "value": "800 pcs", "row": None},
    ]


class MergeTests(unittest.TestCase):
    def test_candidates_from_mixed_blocks(self) -> None:
        cands = candidates_from_blocks(blocks())
        parts = [c.part_no for c in cands]
        # 表格各出一行；图纸的键值组合成一个候选（同件号，合并发生在下一步）
        self.assertEqual(sorted(parts), ["BRK-100", "CVR-310", "CVR-310"])

    def test_merge_keeps_one_line_per_part(self) -> None:
        rfq = merge(candidates_from_blocks(blocks()), rfq_no="RFQ-2026-118", customer="Example Customer Sdn Bhd")
        self.assertEqual([l.part_no for l in rfq.lines], ["BRK-100", "CVR-310"])
        cvr = rfq.line_by_part("CVR-310")
        self.assertEqual(cvr.qty, 1000)
        self.assertAlmostEqual(cvr.tol_mm, 0.05)
        self.assertEqual(cvr.material, "AL6061")
        self.assertEqual(len(cvr.refs), 2, "两个来源都要留出处")

    def test_quantity_conflict_is_recorded(self) -> None:
        """Excel 1000 vs 图纸 800：必须进冲突清单，不能悄悄选一个。"""
        rfq = merge(candidates_from_blocks(blocks()), rfq_no="RFQ-2026-118", customer="X")
        self.assertEqual(len(rfq.conflicts), 1)
        conflict = rfq.conflicts[0]
        self.assertEqual(conflict.part_no, "CVR-310")
        self.assertEqual(conflict.field_name, "qty")
        values = {v for v, _ in conflict.values}
        self.assertEqual(values, {"1000", "800"})
        self.assertIn("part_list.xlsx", conflict.describe())
        self.assertIn("drawing_CVR-310_RevB.pdf", conflict.describe())

    def test_refs_point_back_to_source(self) -> None:
        rfq = merge(candidates_from_blocks(blocks()), rfq_no="RFQ", customer="X")
        cvr = rfq.line_by_part("CVR-310")
        self.assertTrue(any("Part list!A7" in r for r in cvr.refs))
        self.assertTrue(any("page 1 L13" in r for r in cvr.refs))


if __name__ == "__main__":
    unittest.main()
