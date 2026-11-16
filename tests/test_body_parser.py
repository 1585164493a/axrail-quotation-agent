"""正文解析测试：题目样例的正文里写全了 5 个零件，必须能切成 5 行。

这条一旦不通，"只给邮件正文也能报价"就做不成，视频第一个演示也就没了。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.ingest.email_reader import read_eml  # noqa: E402
from quotation_agent.parsers.body_parser import parse_body
from quotation_agent.quote.normalise import parse_tol  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
STAGING = ROOT / ".testtmp"

BODY = """Hi team,

Please quote the parts below.

  1. BRK-100 Mounting bracket, AL6061, 500 pcs, tol +/-0.10 mm, 0.40 kg, approx 6 min, anodise
  2. SHF-220 Drive shaft D20x150, SS304, 200 pcs, tol +/-0.02 mm, 0.37 kg, approx 9 min, no finish
  3. CVR-310 Pump cover, AL6061, 1,000 pcs, tol +/-0.05 mm, 0.85 kg, approx 12 min, anodise
  4. SPC-050 Spacer, SS304, qty to follow, tol +/-0.10 mm, 0.05 kg, approx 2 min, no finish
  5. HSG-400 Valve housing, Ti Gr5, 50 pcs, tol +/-0.005 mm, 1.20 kg, approx 40 min, no finish

Thanks,
Alex
"""


class BodyParserTests(unittest.TestCase):
    def test_five_lines_with_all_fields(self) -> None:
        result = parse_body(BODY)
        self.assertEqual(len(result.blocks), 5)
        first = result.blocks[0]["row"]
        self.assertEqual(first["Part no"], "BRK-100")
        self.assertEqual(first["Material"], "AL6061")
        self.assertEqual(first["Qty"], "500")
        self.assertEqual(parse_tol(first["Tolerance (mm)"]), 0.10)
        self.assertEqual(first["Mass (kg)"], "0.40")
        self.assertEqual(first["Cycle (min)"], "6")
        self.assertEqual(first["Finish"], "Anodise")

    def test_thousand_separator_is_not_split(self) -> None:
        """'1,000 pcs' 里的逗号不能把数量切成 '000'。"""
        result = parse_body(BODY)
        cvr = next(b["row"] for b in result.blocks if b["row"]["Part no"] == "CVR-310")
        self.assertEqual(cvr["Qty"], "1,000")

    def test_tbc_quantity_is_kept_raw(self) -> None:
        """'qty to follow' 原样留给第三步归一化，解析器不改写。"""
        result = parse_body(BODY)
        spacer = next(b["row"] for b in result.blocks if b["row"]["Part no"] == "SPC-050")
        self.assertNotIn("Qty", spacer)
        self.assertEqual(parse_tol(spacer["Tolerance (mm)"]), 0.10)

    def test_locator_points_at_body_line(self) -> None:
        result = parse_body(BODY)
        for block in result.blocks:
            self.assertTrue(block["locator"].startswith("body line "), block["locator"])

    def test_no_line_items_is_reported(self) -> None:
        result = parse_body("Hello, please send your catalogue. Thanks.")
        self.assertEqual(result.blocks, [])
        self.assertTrue(any("no_line_items_in_body" in w for w in result.warnings))

    def test_real_fixture_body(self) -> None:
        env = read_eml(FIXTURES / "01_rfq_body_only.eml", STAGING)
        result = parse_body(env.body_text)
        self.assertEqual([b["row"]["Part no"] for b in result.blocks],
                         ["BRK-100", "SHF-220", "CVR-310", "SPC-050", "HSG-400"])


if __name__ == "__main__":
    unittest.main()
