"""场景矩阵测试：每封邮件都有明确的"应该发生什么"。

老 fixture 全是 RFQ-2026-118 的格式变体，只验证了解析；
这里覆盖业务分支：小批量、紧公差、大批量折扣、未知材料挂起、
数量待定、超权限折扣、大额审批、中文、口语化（模型路径）、非询价。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("LLM_VALUES", "0")
os.environ.setdefault("LLM_ARBITRATION", "0")
os.environ.setdefault("LLM_MAPPING", "0")
os.environ.setdefault("LLM_EXTRACTION", "0")

from quotation_agent.ingest.email_reader import read_bytes  # noqa: E402
from quotation_agent.lambda_handler import handler  # noqa: E402

EMAILS = ROOT / "tests" / "fixtures" / "emails"
SCRATCH = ROOT / ".testtmp" / "scenarios"


def quote_of(eml_name: str, llm=None) -> dict:
    """把一封 .eml 跑成报价（直接调 build_quote，不起 S3）。"""
    import json

    envelope = read_bytes((EMAILS / eml_name).read_bytes(), eml_name, SCRATCH)
    payload = {
        "rfq_no": (envelope.rfq_ids or ["RFQ-UNKNOWN"])[0],
        "customer": envelope.customer_name,
        "body_text": envelope.body_text,
    }
    result = handler(payload)
    body = result.get("body", result)
    return json.loads(body) if isinstance(body, str) else body


class ScenarioMatrixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        SCRATCH.mkdir(parents=True, exist_ok=True)
        os.environ["LLM_EXTRACTION"] = "0"  # 确定性：不调模型

    def test_small_batch_two_lines_low_value(self) -> None:
        q = quote_of("rfq_auto_small_batch.eml")
        self.assertEqual([line["part_no"] for line in q["lines"]], ["GBX-110", "GBX-115"])
        self.assertEqual(q["held"], [])
        self.assertFalse(q["approval"]["required"])
        self.assertLess(q["total"], 50_000)

    def test_tight_tolerance_uses_five_axis_and_holds_the_impossible_one(self) -> None:
        """tol 0.02 → 5 轴费率；tol 0.005 超出能力 → 挂起 hold_no_rate，不许猜。"""
        q = quote_of("rfq_medical_tight_tol.eml")
        trace = " ".join(q["lines"][0]["trace"])
        self.assertIn("R-5AXIS", trace)
        self.assertNotIn("R-3AXIS", trace)
        held = {held["part_no"]: held["reason"] for held in q["held"]}
        self.assertEqual(held.get("SUR-033"), "hold_no_rate")

    def test_bulk_quantity_gets_eight_percent_tier(self) -> None:
        q = quote_of("rfq_bulk_volume.eml")
        line = q["lines"][0]
        self.assertEqual(line["qty"], 5000)
        self.assertEqual(line["discount_rate"], 0.08)
        self.assertIn("D-QTY-8", " ".join(line["trace"]))

    def test_unknown_materials_are_held_not_guessed(self) -> None:
        q = quote_of("rfq_unknown_material.eml")
        self.assertEqual(q["lines"], [])
        reasons = {held["part_no"]: held["reason"] for held in q["held"]}
        self.assertEqual(reasons, {"UAV-501": "hold_no_material", "UAV-502": "hold_no_material"})

    def test_quantity_to_follow_holds_only_that_line(self) -> None:
        q = quote_of("rfq_qty_to_follow.eml")
        self.assertEqual([line["part_no"] for line in q["lines"]], ["MAN-211"])
        self.assertEqual([held["part_no"] for held in q["held"]], ["MAN-210"])
        self.assertEqual(q["held"][0]["reason"], "hold_no_qty")

    def test_discount_above_policy_triggers_approval(self) -> None:
        q = quote_of("rfq_discount_request.eml")
        self.assertTrue(q["approval"]["required"])
        self.assertTrue(any("12%" in reason for reason in q["approval"]["reasons"]))

    def test_large_value_triggers_threshold_approval(self) -> None:
        q = quote_of("rfq_large_value.eml")
        self.assertGreater(q["total"], 50_000)
        self.assertTrue(any("threshold" in reason for reason in q["approval"]["reasons"]))

    def test_missing_finish_defaults_to_none(self) -> None:
        q = quote_of("rfq_no_finish_no_mass.eml")
        self.assertEqual(len(q["lines"]), 1)
        self.assertIn("F-NONE", " ".join(q["lines"][0]["trace"]))

    def test_chinese_body_is_parsed(self) -> None:
        q = quote_of("rfq_chinese_body.eml")
        self.assertEqual([line["part_no"] for line in q["lines"]], ["SZ-801", "SZ-802"])
        self.assertEqual(q["rfq_no"], "RFQ-2026-209")

    def test_prose_email_needs_the_model(self) -> None:
        """口语化正文：关掉模型时抽不出行——这正说明模型兜底的必要性。"""
        q = quote_of("rfq_prose_unstructured.eml")
        self.assertEqual(q["lines"], [])
        self.assertTrue(any("llm" in warning for warning in q["warnings"]))

    def test_prose_email_with_model_produces_lines(self) -> None:
        """用假模型返回口语邮件的结构，验证'模型给行 → 代码定价'这条路。"""
        import json

        fake_rows = [
            {"part_no": "BRK-880", "material": "6061 aluminium", "qty": 500,
             "tol_mm": 0.1, "mass_kg": 0.4, "cycle_min": 6, "finish": "anodise"},
            {"part_no": "SHF-881", "material": "stainless 304", "qty": 200,
             "tol_mm": 0.02, "mass_kg": 0.37, "cycle_min": 9, "finish": "none"},
        ]
        envelope = read_bytes((EMAILS / "rfq_prose_unstructured.eml").read_bytes(),
                              "rfq_prose_unstructured.eml", SCRATCH)

        from quotation_agent import lambda_handler as lh

        original_extract = lh.__dict__.get("_fake_llm")
        lh_tools = lh.TOOLS
        self.assertIn("build_quote", lh_tools)

        # 直接注入假模型：不走网络，也不改全局状态
        import quotation_agent.extract as extract_module

        original = extract_module.hybrid_blocks
        from quotation_agent.extract import hybrid_blocks as real_hybrid

        def patched(body, llm=None):
            return real_hybrid(body, llm=lambda _text: fake_rows)

        extract_module.hybrid_blocks = patched
        lh.hybrid_blocks = patched  # type: ignore[attr-defined]
        try:
            os.environ["LLM_EXTRACTION"] = "1"
            result = handler({"rfq_no": "RFQ-2026-210", "customer": "Startup Robotics",
                              "body_text": envelope.body_text})
            body = result.get("body", result)
            q = json.loads(body) if isinstance(body, str) else body
        finally:
            extract_module.hybrid_blocks = original
            lh.hybrid_blocks = original  # type: ignore[attr-defined]
            os.environ["LLM_EXTRACTION"] = "0"
            _ = original_extract

        self.assertEqual([line["part_no"] for line in q["lines"]], ["BRK-880", "SHF-881"])
        self.assertEqual(q["lines"][0]["material"], "AL6061")  # 6061 aluminium 被规范化

    def test_meeting_invite_yields_no_lines(self) -> None:
        q = quote_of("not_an_rfq_meeting.eml")
        self.assertEqual(q["lines"], [])
        self.assertEqual(q["total"], 0)


if __name__ == "__main__":
    unittest.main()
