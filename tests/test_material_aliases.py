"""自由文本材料 → 价表牌号的映射。

模型抽出来的是"6061 aluminium"这种人话，价表里是 AL6061。
映射错了会静默按"无材料价"挂起，所以把常见写法钉住。

注意：价表只有 AL6061 和 SS304。其他牌号（Ti Gr5、7075、316）
必须**原样保留并挂起**——宁可报不出价，也不能猜一个价格。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.quote.normalise import parse_material  # noqa: E402


class MaterialAliasTests(unittest.TestCase):
    def test_variants_that_exist_in_the_price_list(self) -> None:
        cases = {
            "6061 aluminium": "AL6061",
            "aluminium 6061": "AL6061",
            "AL 6061-T6": "AL6061",
            "aluminum alloy 6061": "AL6061",
            "stainless 304": "SS304",
            "SS304": "SS304",
            "304 stainless steel": "SS304",
        }
        for raw, expected in cases.items():
            with self.subTest(raw=raw):
                self.assertEqual(parse_material(raw)[0], expected)

    def test_grades_not_in_the_price_list_stay_raw(self) -> None:
        """牌号认得出、但价表没有 → 保持原文，让定价去挂起，绝不猜价。"""
        for raw in ("titanium grade 5", "Ti-6Al-4V", "aluminum 7075", "SS316", "Inconel 718"):
            with self.subTest(raw=raw):
                self.assertEqual(parse_material(raw)[0], raw)

    def test_raw_value_is_preserved_for_audit(self) -> None:
        canonical, raw = parse_material("6061 aluminium")
        self.assertEqual(canonical, "AL6061")
        self.assertEqual(raw, "6061 aluminium")


if __name__ == "__main__":
    unittest.main()
