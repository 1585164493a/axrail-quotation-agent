"""Lambda 三个工具的端到端测试（不经 AWS，直接调 handler）。

重点钉住一个真实 bug：render_reply 曾经用不完整字段重算价格，
导致回信里"已报的 3 行"全部丢失、总额变 0。现在它必须沿用上游算好的价。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

os.environ.setdefault("LLM_VALUES", "0")
os.environ.setdefault("LLM_ARBITRATION", "0")
os.environ.setdefault("LLM_MAPPING", "0")
os.environ.setdefault("LLM_EXTRACTION", "0")

from quotation_agent.lambda_handler import handler  # noqa: E402

BODY = (
    "1. BRK-100 Mounting bracket, AL6061, 500 pcs, tol +/-0.10 mm, 0.40 kg, approx 6 min, anodise\n"
    "2. SHF-220 Drive shaft D20x150, SS304, 200 pcs, tol +/-0.02 mm, 0.37 kg, approx 9 min, no finish\n"
    "3. CVR-310 Pump cover, AL6061, 1,000 pcs, tol +/-0.05 mm, 0.85 kg, approx 12 min, anodise\n"
    "4. SPC-050 Spacer, SS304, qty to follow, tol +/-0.10 mm, 0.05 kg, approx 2 min, no finish\n"
    "5. HSG-400 Valve housing, Ti Gr5, 50 pcs, tol +/-0.005 mm, 1.20 kg, approx 40 min, no finish\n"
    "\nCan you also give us 15% off as we are a new customer?\n"
)


def call(payload: dict) -> dict:
    result = handler(payload)
    body = result["body"] if "body" in result else json.dumps(result)
    return json.loads(body) if isinstance(body, str) else body


class ToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 测试不调模型：固定走正则路径，保证确定性、不花钱、不依赖网络
        os.environ["LLM_EXTRACTION"] = "0"

    def test_price_line_tool(self) -> None:
        out = call({"part_no": "BRK-100", "material": "AL6061", "qty": 500,
                    "tol_mm": 0.1, "mass_kg": 0.4, "cycle_min": 6, "finish": "anodise"})
        self.assertEqual(out["status"], "priced")
        self.assertEqual(out["unit_cost"], 21.2)
        self.assertEqual(out["unit_price"], 26.86)

    def test_build_quote_tool(self) -> None:
        out = call({"rfq_no": "RFQ-2026-118", "customer": "Example Customer Sdn Bhd", "body_text": BODY})
        self.assertEqual(len(out["lines"]), 3)
        self.assertEqual(len(out["held"]), 2)
        self.assertEqual(out["total"], 74684.0)
        self.assertTrue(out["approval"]["required"])
        self.assertTrue(any("15%" in r for r in out["approval"]["reasons"]))

    def test_render_reply_keeps_the_priced_lines(self) -> None:
        """回信必须包含已报的 3 行和正确总额，不能因为重算而丢失。"""
        quote = call({"rfq_no": "RFQ-2026-118", "customer": "Example Customer Sdn Bhd", "body_text": BODY})
        out = call({"quote": quote})

        reply = out["reply_email"]
        for part in ("BRK-100", "SHF-220", "CVR-310"):
            self.assertIn(part, reply, f"{part} 没出现在回信里")
        self.assertIn("74,684.00", reply)
        self.assertIn("SPC-050", reply)   # 挂起行也要问
        self.assertIn("HSG-400", reply)

        text = out["quote_text"]
        self.assertIn("BRK-100", text)
        self.assertNotIn("Total 0.00", text)

    def test_render_pdf_tool_without_bucket_returns_base64(self) -> None:
        """没配 PDF_BUCKET 时退回 base64，仍然是一份合法 PDF。"""
        import base64

        quote = call({"rfq_no": "RFQ-2026-118", "customer": "Example Customer Sdn Bhd", "body_text": BODY})
        out = call({"quote": quote, "output": "pdf"})

        self.assertIn("pdf_base64", out)
        raw = base64.b64decode(out["pdf_base64"])
        self.assertTrue(raw.startswith(b"%PDF-1.4"))
        self.assertGreater(len(raw), 2000)

    def test_unknown_tool_is_reported(self) -> None:
        out = call({"tool": "nope", "args": {}})
        self.assertIn("error", out)


if __name__ == "__main__":
    unittest.main()
