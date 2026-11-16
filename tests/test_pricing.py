"""定价测试：对着题目给的规则和算例验算。

题目原文给了第 1 行的算例：0.40×18.00 + 6×2.00 + 1.50 + 250/500 = 21.20。
这里把它钉成测试，改动定价代码时立刻能发现回归。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.quote.model import CanonicalLine, HeldLine, PricedLine  # noqa: E402
from quotation_agent.quote.pricing import (  # noqa: E402
    MARGIN,
    discount_rate,
    machine_rate,
    material_price,
    price_line,
)


def line(**kw) -> CanonicalLine:
    base = dict(part_no="BRK-100", material="AL6061", qty=500, tol_mm=0.10,
                mass_kg=0.40, cycle_min=6, finish="anodise", refs=["part_list.xlsx @ Part list!A5"])
    base.update(kw)
    return CanonicalLine(**base)


class PriceLineTests(unittest.TestCase):
    def test_brief_worked_example(self) -> None:
        """题目算例：第 1 行单位成本必须是 21.20。"""
        result = price_line(line())
        self.assertIsInstance(result, PricedLine)
        self.assertAlmostEqual(result.unit_cost, 21.20, places=2)

    def test_margin_is_on_price_not_markup(self) -> None:
        """毛利 25% 的口径：售价 = 成本 ÷ 0.75，不是成本 × 1.25。"""
        result = price_line(line())
        self.assertAlmostEqual(result.base_price, round(21.20 / (1 - MARGIN), 2), places=2)
        self.assertAlmostEqual(result.base_price, 28.27, places=2)

    def test_quantity_discount_and_total(self) -> None:
        """500 件进 5% 档：26.86/件，行合计 13,430。"""
        result = price_line(line())
        self.assertEqual(result.discount_rate, 0.05)
        self.assertAlmostEqual(result.unit_price, 26.86, places=2)
        self.assertAlmostEqual(result.line_total, 13430.00, places=2)

    def test_1000_pcs_gets_eight_percent(self) -> None:
        result = price_line(line(part_no="CVR-310", qty=1000, cycle_min=12, tol_mm=0.05, mass_kg=0.85))
        self.assertEqual(result.discount_rate, 0.08)
        self.assertAlmostEqual(result.unit_cost, 41.05, places=2)
        self.assertAlmostEqual(result.unit_price, 50.35, places=2)

    def test_200_pcs_gets_no_discount(self) -> None:
        result = price_line(line(part_no="SHF-220", material="SS304", qty=200, tol_mm=0.02,
                                 mass_kg=0.37, cycle_min=9, finish="none"))
        self.assertEqual(result.discount_rate, 0.0)
        self.assertAlmostEqual(result.unit_cost, 40.89, places=2)

    def test_tolerance_boundary_uses_five_axis(self) -> None:
        """±0.02 含下界 → 五轴 3.50/min（这是最容易算错的地方）。"""
        self.assertEqual(machine_rate(0.02), ("CNC 5-axis", 3.50))
        self.assertEqual(machine_rate(0.049), ("CNC 5-axis", 3.50))
        self.assertEqual(machine_rate(0.05), ("CNC 3-axis", 2.00))
        self.assertEqual(machine_rate(0.10), ("CNC 3-axis", 2.00))
        self.assertIsNone(machine_rate(0.005))

    def test_tighter_than_002_is_held(self) -> None:
        result = price_line(line(part_no="HSG-400", material="Ti Gr5", tol_mm=0.005))
        self.assertIsInstance(result, HeldLine)
        self.assertEqual(result.reason, "hold_no_material")  # 材料先卡住

    def test_unknown_material_is_held(self) -> None:
        result = price_line(line(material="Ti Gr5"))
        self.assertIsInstance(result, HeldLine)
        self.assertEqual(result.reason, "hold_no_material")

    def test_missing_qty_is_held(self) -> None:
        result = price_line(line(part_no="SPC-050", qty=None))
        self.assertIsInstance(result, HeldLine)
        self.assertEqual(result.reason, "hold_no_qty")

    def test_known_material_but_no_rate_is_held(self) -> None:
        """材料有价、公差太紧：应报 hold_no_rate，而不是随便找个费率。"""
        result = price_line(line(material="AL6061", tol_mm=0.005))
        self.assertIsInstance(result, HeldLine)
        self.assertEqual(result.reason, "hold_no_rate")

    def test_price_is_never_negative_or_zero(self) -> None:
        result = price_line(line())
        self.assertGreater(result.unit_price, result.unit_cost)

    def test_trace_covers_every_cost_component(self) -> None:
        """每一笔钱都要有规则号和出处。"""
        result = price_line(line())
        rules = [t.rule for t in result.trace]
        for expected in ("M-AL6061", "R-3AXIS", "F-ANODISE", "S-LINE", "COST", "P-MARGIN", "TOTAL"):
            self.assertIn(expected, rules)
        self.assertTrue(all(t.source for t in result.trace if t.rule.startswith("M-")))


class TableLookupTests(unittest.TestCase):
    def test_material_prices(self) -> None:
        self.assertEqual(material_price("AL6061"), 18.00)
        self.assertEqual(material_price("SS304"), 22.00)
        self.assertIsNone(material_price("Ti Gr5"))

    def test_discount_tiers(self) -> None:
        self.assertEqual(discount_rate(499), 0.0)
        self.assertEqual(discount_rate(500), 0.05)
        self.assertEqual(discount_rate(999), 0.05)
        self.assertEqual(discount_rate(1000), 0.08)


if __name__ == "__main__":
    unittest.main()
