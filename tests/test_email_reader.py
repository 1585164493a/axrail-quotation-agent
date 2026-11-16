"""第一步（邮件接入）的测试。

用标准库 unittest 写，这样不装 pytest 也能跑；
装了 pytest 也能直接跑（pytest 兼容 TestCase 风格）。
"""

from __future__ import annotations

import shutil
import sys
import unittest
from email.message import EmailMessage
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.ingest.email_reader import read_bytes, read_eml  # noqa: E402

BODY = """Hi team,

Please quote the parts below. Our part list (Excel) and spec slides are also attached.
Delivery needed in 6 weeks to our Shah Alam plant.

Thanks,
Alex Tan
Procurement, Example Customer Sdn Bhd
"""


def build_email(body: str = BODY, html: str | None = None, attachments: dict[str, bytes] | None = None) -> bytes:
    """造一封测试用邮件（纯内存，不落盘）。"""
    msg = EmailMessage()
    msg["Subject"] = "RFQ-2026-118 - CNC parts, delivery in 6 weeks"
    msg["From"] = "Alex Tan <buyer@example-customer.test>"
    msg["To"] = "sales@example-cnc-shop.test"
    msg["Date"] = "Mon, 02 Nov 2026 09:14:00 +0800"
    msg["Message-ID"] = "<rfq-2026-118@example-customer.test>"
    msg.set_content(body)
    if html is not None:
        msg.add_alternative(html, subtype="html")
    for name, payload in (attachments or {}).items():
        msg.add_attachment(payload, maintype="application", subtype="octet-stream", filename=name)
    return msg.as_bytes()


# 附件目录固定放在仓库内的 .testtmp：部分沙箱只允许浅层写入
STAGING = Path(__file__).resolve().parents[1] / ".testtmp"


def tearDownModule() -> None:
    shutil.rmtree(STAGING, ignore_errors=True)


class EmailReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)
        self.staging = STAGING

    def test_plain_body_fields(self) -> None:
        """普通纯文本邮件：主题、发件人、日期都要解析正确。"""
        env = read_bytes(build_email(), "rfq.eml", self.staging)
        self.assertEqual(env.subject, "RFQ-2026-118 - CNC parts, delivery in 6 weeks")
        self.assertEqual(env.sender_email, "buyer@example-customer.test")
        self.assertEqual(env.sender_name, "Alex Tan")
        self.assertEqual(env.rfq_ids, ["RFQ-2026-118"])
        self.assertIn("Shah Alam", env.body_text)
        self.assertEqual(env.date.isoformat(), "2026-11-02T09:14:00+08:00")

    def test_customer_name_from_signature(self) -> None:
        """公司名要从签名行里抠出来，不能连"Procurement,"一起抓。"""
        env = read_bytes(build_email(), "rfq.eml", self.staging)
        self.assertEqual(env.customer_name, "Example Customer Sdn Bhd")
        self.assertFalse(any(w.startswith("customer_name_not_found") for w in env.warnings))

    def test_missing_attachments_is_flagged(self) -> None:
        """没有附件必须报警：规格可能不在邮件里。"""
        env = read_bytes(build_email(), "rfq.eml", self.staging)
        self.assertEqual(env.attachments, [])
        self.assertIn("no_attachments: no attachment on this email; specification files may be missing", env.warnings)

    def test_attachments_are_saved_and_hashed(self) -> None:
        """附件要落盘、要有大小和 sha256，方便后面追溯。"""
        raw = build_email(attachments={"part_list.xlsx": b"PK\x03\x04fake-xlsx", "part_spec.pptx": b"PK\x03\x04fake-pptx"})
        env = read_bytes(raw, "rfq.eml", self.staging)

        self.assertEqual([a.filename for a in env.attachments], ["part_list.xlsx", "part_spec.pptx"])
        self.assertEqual(env.attachments[0].size_bytes, len(b"PK\x03\x04fake-xlsx"))
        self.assertEqual(len(env.attachments[0].sha256), 64)
        for att in env.attachments:
            self.assertTrue(Path(att.path).exists(), att.path)
        self.assertFalse(any(w.startswith("no_attachments") for w in env.warnings))

    def test_two_rfqs_do_not_collide_in_staging(self) -> None:
        """两封邮件都带同名附件时，落盘不能互相覆盖。"""
        env_a = read_bytes(build_email(attachments={"a.bin": b"A"}), "a.eml", self.staging)
        env_b = read_bytes(build_email(attachments={"a.bin": b"B"}), "b.eml", self.staging)
        self.assertNotEqual(env_a.attachments[0].path, env_b.attachments[0].path)
        self.assertEqual(Path(env_b.attachments[0].path).read_bytes(), b"B")

    def test_html_only_body(self) -> None:
        """只有 HTML 正文时，要能转出文本并留下告警。"""
        raw = build_email(body="", html="<div>Hi,<br>RFQ-2026-118 attached.<br>Thanks,<br>Alex</div>")
        env = read_bytes(raw, "rfq.eml", self.staging)
        self.assertIn("RFQ-2026-118", env.body_text)
        self.assertIn("body_html_only", " ".join(env.warnings))
        self.assertEqual(env.rfq_ids, ["RFQ-2026-118"])

    def test_rfq_id_formats(self) -> None:
        """客户不一定会写成 RFQ-2026-118，常见的几种写法都要认出来。"""
        cases = {
            "Re: RFQ-2026-118 - CNC parts": ["RFQ-2026-118"],
            "RFQ No.: 118/2026 - brackets": ["RFQ-2026-118"],
            "询价单 2026-118 请报价": ["RFQ-2026-118"],
            "Enquiry 118 for brackets": ["RFQ-118"],
        }
        for subject, expected in cases.items():
            msg = EmailMessage()
            msg["Subject"] = subject
            msg["From"] = "alex@example.com"
            msg["To"] = "sales@example.cnc"
            msg.set_content("Please quote these parts.")
            env = read_bytes(msg.as_bytes(), "x.eml", self.staging)
            self.assertEqual(env.rfq_ids, expected, subject)

    def test_missing_rfq_id_is_flagged(self) -> None:
        """没有 RFQ 号要报警，而不是编一个。"""
        msg = EmailMessage()
        msg["Subject"] = "Quick question about brackets"
        msg["From"] = "alex@example.com"
        msg["To"] = "sales@example.cnc"
        msg.set_content("Hello, could you price 10 brackets? Thanks.")
        env = read_bytes(msg.as_bytes(), "x.eml", self.staging)
        self.assertEqual(env.rfq_ids, [])
        self.assertTrue(any(w.startswith("rfq_id_not_found") for w in env.warnings))

    def test_real_sample_email_when_present(self) -> None:
        """拿 Axrail 那封真实邀请邮件做回归（本机没有就跳过）。"""
        sample = Path(r"D:\download\Axrail_AI_Engineer_–_Take-home_Task_(AI_Quotation_Agent).eml")
        if not sample.exists():
            self.skipTest("sample .eml not present on this machine")
        env = read_eml(sample, self.staging)
        self.assertEqual(env.sender_email, "kelvinkok@axrail.com")
        self.assertIn("Take-home Task", env.subject)
        self.assertIn("no_attachments", " ".join(env.warnings))


if __name__ == "__main__":
    unittest.main()
