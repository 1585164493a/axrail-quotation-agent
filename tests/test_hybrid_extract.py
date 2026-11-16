"""混合抽取测试：正则优先、模型兜底、两路交叉验证。

这里用一个"假模型"代替 Bedrock，把三档行为都钉住：
1. 正则抽全 → 不调模型（省钱）；
2. 正则抽不全 → 调模型，两路块共存；
3. 两路数值不一致 → merge 自动产生冲突（不在这里写第二套比对）。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.extract import hybrid_blocks, is_complete, regex_blocks  # noqa: E402
from quotation_agent.quote.normalise import candidates_from_blocks, merge  # noqa: E402

GOOD_BODY = """Hi team,

  1. BRK-100 Mounting bracket, AL6061, 500 pcs, tol +/-0.10 mm, 0.40 kg, approx 6 min, anodise
  2. SHF-220 Drive shaft D20x150, SS304, 200 pcs, tol +/-0.02 mm, 0.37 kg, approx 9 min, no finish
"""

MESSY_BODY = """Hello,

please quote the bracket for the pump, aluminium, five hundred pieces,
tolerance one tenth, about 0.4 kg, anodised. Delivery six weeks.

Thanks
"""


class SpyLLM:
    def __init__(self, rows: list[dict] | None = None, error: Exception | None = None) -> None:
        self.rows = rows if rows is not None else []
        self.error = error
        self.calls = 0

    def __call__(self, body: str) -> list[dict]:
        self.calls += 1
        if self.error:
            raise self.error
        return self.rows


class HybridExtractTests(unittest.TestCase):
    def test_regex_complete_does_not_call_model(self) -> None:
        """整齐的正文：正则抽全，模型一次都不该被调用（这是省钱的关键）。"""
        spy = SpyLLM(rows=[{"part_no": "NOPE", "material": "X"}])
        blocks, warnings = hybrid_blocks(GOOD_BODY, llm=spy)

        self.assertEqual(spy.calls, 0)
        self.assertFalse(any("llm" in w for w in warnings))
        self.assertEqual(len(blocks), 2)
        self.assertTrue(all(b["locator"].startswith("body line") for b in blocks))

    def test_regex_incomplete_triggers_model(self) -> None:
        """口语化正文：正则抽不出，模型兜底，块来自 llm。"""
        spy = SpyLLM(rows=[{
            "part_no": "BRK-100", "description": "bracket", "material": "AL6061",
            "qty": 500, "tol_mm": 0.1, "mass_kg": 0.4, "cycle_min": 6, "finish": "anodise",
        }])
        blocks, warnings = hybrid_blocks(MESSY_BODY, llm=spy)

        self.assertEqual(spy.calls, 1)
        self.assertTrue(any("llm_fallback_used" in w for w in warnings))
        llm_blocks = [b for b in blocks if b["locator"].startswith("llm line")]
        self.assertEqual(len(llm_blocks), 1)
        self.assertEqual(llm_blocks[0]["row"]["Part no"], "BRK-100")
        self.assertEqual(llm_blocks[0]["row"]["Qty"], 500)

    def test_model_failure_does_not_break_the_flow(self) -> None:
        spy = SpyLLM(error=RuntimeError("throttled"))
        blocks, warnings = hybrid_blocks(MESSY_BODY, llm=spy)

        self.assertTrue(any("llm_failed" in w for w in warnings))
        self.assertIsInstance(blocks, list)  # 仍然返回（可能是空的）块列表

    def test_model_rows_without_part_no_are_dropped(self) -> None:
        spy = SpyLLM(rows=[{"material": "AL6061"}, {"part_no": "SHF-220", "material": "SS304"}])
        blocks, warnings = hybrid_blocks(MESSY_BODY, llm=spy)
        rows = [b["row"] for b in blocks if b["locator"].startswith("llm line")]

        self.assertEqual(len(rows), 1)
        self.assertTrue(any("llm_row_without_part_no" in w for w in warnings))

    def test_conflicting_values_become_a_conflict(self) -> None:
        """正则抽到的 1000 和模型给的 800 都要留在结果里，merge 必须报冲突。

        这里故意让 CVR-310 那行缺公差（正则抽不全），才会触发模型兜底。
        """
        body = (
            "1. BRK-100 Bracket, AL6061, 500 pcs, tol +/-0.10 mm, 0.40 kg, approx 6 min, anodise\n"
            "2. CVR-310 Pump cover, AL6061, 1000 pcs, 0.85 kg, approx 12 min, anodise\n"
        )
        spy = SpyLLM(rows=[{
            "part_no": "CVR-310", "material": "AL6061", "qty": 800,
            "tol_mm": 0.05, "mass_kg": 0.85, "cycle_min": 12, "finish": "anodise",
        }])

        blocks, warnings = hybrid_blocks(body, llm=spy)
        rfq = merge(candidates_from_blocks(blocks), rfq_no="RFQ-TEST", customer="X")

        self.assertEqual(spy.calls, 1, "缺公差应当触发模型兜底")
        self.assertTrue(any("llm_fallback_used" in w for w in warnings))
        cvr = rfq.line_by_part("CVR-310")
        self.assertIsNotNone(cvr)
        self.assertEqual(cvr.qty, 1000)  # 正则那行权重更高（同文件取更可靠读法）
        self.assertTrue(any(c.field_name == "qty" for c in rfq.conflicts), rfq.conflicts)

    def test_no_model_configured_is_reported_not_fatal(self) -> None:
        blocks, warnings = hybrid_blocks(MESSY_BODY, llm=None)
        self.assertTrue(any("llm_not_configured" in w for w in warnings))
        self.assertIsInstance(blocks, list)


class CompletenessTests(unittest.TestCase):
    def test_is_complete_requires_material_qty_tolerance(self) -> None:
        self.assertTrue(is_complete([{"Part no": "A", "Material": "AL6061", "Qty": "5", "Tolerance (mm)": "0.1"}]))
        self.assertFalse(is_complete([{"Part no": "A", "Material": "AL6061", "Qty": "5"}]))  # 缺公差
        self.assertFalse(is_complete([]))

    def test_tbc_quantity_is_not_an_extraction_gap(self) -> None:
        """正文写了 "qty to follow"，缺数量是客户没给，不该触发模型。"""
        rows = [
            {"Part no": "A", "Material": "AL6061", "Qty": "5", "Tolerance (mm)": "0.1"},
            {"Part no": "B", "Material": "SS304", "Tolerance (mm)": "0.1"},
        ]
        self.assertTrue(is_complete(rows, "B spacer, qty to follow"))
        # 没有待定标记却缺数量 → 认为抽取漏了
        self.assertFalse(is_complete(rows, "B spacer"))

    def test_body_only_fixture_skips_the_model(self) -> None:
        from pathlib import Path

        from quotation_agent.ingest.email_reader import read_bytes

        root = Path(__file__).resolve().parents[1]
        envelope = read_bytes((root / "tests" / "fixtures" / "01_rfq_body_only.eml").read_bytes(),
                              "01.eml", root / ".testtmp")
        spy = SpyLLM(rows=[])
        blocks, warnings = hybrid_blocks(envelope.body_text, llm=spy)

        self.assertEqual(spy.calls, 0, "整齐正文 + 一行 TBC 不该调模型")
        self.assertEqual(len(blocks), 5)
        self.assertFalse(any("llm" in warning for warning in warnings))

    def test_regex_blocks_on_good_body(self) -> None:
        blocks = regex_blocks(GOOD_BODY)
        self.assertEqual([b["row"]["Part no"] for b in blocks], ["BRK-100", "SHF-220"])


if __name__ == "__main__":
    unittest.main()
