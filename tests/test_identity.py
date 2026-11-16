"""客户身份识别的测试。

原则只有一条：证据足的自动过，证据矛盾的必须交人——不能自己挑一个。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.identity import resolve_customer  # noqa: E402
from quotation_agent.models import Envelope  # noqa: E402


def make_envelope(sender_email: str, sender_name: str = "Alex Tan", customer_name: str = "") -> Envelope:
    domain = sender_email.split("@")[-1]
    return Envelope(
        source="x.eml",
        message_id="<x@example>",
        subject="RFQ-2026-118",
        sender_name=sender_name,
        sender_email=sender_email,
        recipients=["sales@example.cnc"],
        date=None,
        body_text="",
        rfq_ids=["RFQ-2026-118"],
        customer_name=customer_name,
        customer_email_domain=domain,
    )


class ResolveCustomerTests(unittest.TestCase):
    def test_signature_only_is_medium(self) -> None:
        """只有签名一条线索：可以用，但要记一笔。"""
        env = make_envelope("buyer@example-customer.test", customer_name="Example Customer Sdn Bhd")
        res = resolve_customer(env)
        self.assertEqual(res.company, "Example Customer Sdn Bhd")
        self.assertEqual(res.level, "medium")
        self.assertAlmostEqual(res.confidence, 0.2, places=2)

    def test_signature_plus_drawing_title_is_high(self) -> None:
        """签名与图纸标题栏一致：高置信，自动过。"""
        env = make_envelope("buyer@example-customer.test", customer_name="Example Customer Sdn Bhd")
        drawing = "Example Customer Sdn Bhd - Drawing spec sheet\nPart no: CVR-310"
        res = resolve_customer(env, attachment_texts={"drawing_CVR-310.pdf": drawing})
        self.assertEqual(res.level, "high")
        self.assertEqual(res.company, "Example Customer Sdn Bhd")
        self.assertGreaterEqual(res.confidence, 0.5)
        self.assertEqual(res.conflicts, [])

    def test_directory_hit_wins(self) -> None:
        """历史客户库命中：最高置信度。"""
        env = make_envelope("buyer@example-customer.test")
        res = resolve_customer(env, directory={"example-customer.test": "Example Customer Sdn Bhd"})
        self.assertEqual(res.level, "high")
        self.assertEqual(res.company, "Example Customer Sdn Bhd")

    def test_conflicting_evidence_needs_review(self) -> None:
        """签名说 A 公司、图纸标题说 B 公司：不下结论，交人。"""
        env = make_envelope("buyer@example-customer.test", customer_name="Example Customer Sdn Bhd")
        drawing = "Alpha Precision Manufacturing Sdn Bhd - Drawing spec sheet"
        res = resolve_customer(env, attachment_texts={"a.pdf": drawing})
        self.assertEqual(res.level, "needs_review")
        self.assertTrue(res.conflicts, "矛盾必须进冲突清单")
        self.assertTrue(any("Alpha" in c or "mismatch" in c for c in res.conflicts))

    def test_public_domain_without_signature_is_draft(self) -> None:
        """公共邮箱 + 没有签名：没有线索，建待确认草稿，不猜。"""
        env = make_envelope("alex.work@gmail.com", sender_name="")
        res = resolve_customer(env)
        self.assertEqual(res.level, "draft")
        self.assertEqual(res.company, "")
        self.assertTrue(any("public mailbox" in n for n in res.notes))
        self.assertEqual(res.contact_name, "alex.work")

    def test_similar_names_are_merged(self) -> None:
        """同一个公司的大小写/标点差异不能算成两家。"""
        env = make_envelope("buyer@example-customer.test", customer_name="Example Customer Sdn Bhd")
        drawing = "EXAMPLE CUSTOMER SDN. BHD.\nDrawing spec sheet"
        res = resolve_customer(env, attachment_texts={"a.pdf": drawing})
        self.assertEqual(res.level, "high")
        self.assertEqual(res.conflicts, [])


if __name__ == "__main__":
    unittest.main()
