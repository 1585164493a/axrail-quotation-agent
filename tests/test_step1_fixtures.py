"""第一步的输入/输出回归：把 tests/fixtures 下的真实 .eml 全部跑一遍。

这一层只关心"来了什么"：主题、发件人、RFQ 号、客户名、附件、告警。
解析件的字段是否正确，是第二步的事。

新增样例时：先在 build_fixtures.py 里加一个构造器，再在下面 CASES 里补一行。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.identity import resolve_customer  # noqa: E402
from quotation_agent.ingest.email_reader import read_eml  # noqa: E402

FIXTURES = Path(__file__).resolve().parent / "fixtures"
STAGING = Path(__file__).resolve().parents[1] / ".testtmp"

# 文件名 -> 期望值
CASES = {
    "01_rfq_body_only.eml": dict(
        rfq_ids=["RFQ-2026-118"],
        customer="Example Customer Sdn Bhd",
        attachments=0,
        warnings=["no_attachments"],
        body_has=["BRK-100", "HSG-400", "15% off"],
    ),
    "02_rfq_full_attachments.eml": dict(
        rfq_ids=["RFQ-2026-118"],
        customer="Example Customer Sdn Bhd",
        attachments=3,
        warnings=[],
        body_has=["BRK-100"],
    ),
    "03_rfq_html_only.eml": dict(
        rfq_ids=["RFQ-2026-118"],
        customer="Example Customer Sdn Bhd",
        attachments=0,
        warnings=["body_html_only", "no_attachments"],
        body_has=["Please quote the 5 parts"],
    ),
    "04_rfq_reply_chain.eml": dict(
        rfq_ids=["RFQ-2026-118"],
        customer="Example Customer Sdn Bhd",
        attachments=0,
        warnings=["no_attachments"],
        body_has=["spacer quantity is still to be confirmed"],
    ),
    "05_rfq_no_id.eml": dict(
        rfq_ids=[],
        customer="Example Customer Sdn Bhd",
        attachments=0,
        warnings=["rfq_id_not_found", "no_attachments"],
        body_has=["20 of these brackets"],
    ),
    "06_not_an_rfq.eml": dict(
        rfq_ids=[],
        customer="",
        attachments=0,
        warnings=["rfq_id_not_found", "customer_name_not_found"],
        body_has=["interview"],
    ),
    "07_rfq_public_domain.eml": dict(
        rfq_ids=["RFQ-2026-118"],
        customer="Example Customer Sdn Bhd",
        attachments=0,
        warnings=["no_attachments"],
        body_has=["BRK-100"],
    ),
    "08_rfq_chinese.eml": dict(
        rfq_ids=["RFQ-2026-118"],
        customer="Example Customer Sdn Bhd",
        attachments=0,
        warnings=["no_attachments"],
        body_has=["安装支架", "15% 折扣"],
    ),
    "09_two_rfqs.eml": dict(
        rfq_ids=["RFQ-2026-118", "RFQ-2026-119"],
        customer="Example Customer Sdn Bhd",
        attachments=0,
        warnings=["no_attachments"],
        body_has=["two requests"],
    ),
    "10_rfq_bad_encoding.eml": dict(
        rfq_ids=["RFQ-2026-118"],
        customer="Example Customer Sdn Bhd",
        attachments=0,
        warnings=["no_attachments"],
        body_has=["CVR-310"],
    ),
}


class Step1FixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        STAGING.mkdir(parents=True, exist_ok=True)

    def test_every_fixture_matches_expectations(self) -> None:
        for filename, expected in CASES.items():
            with self.subTest(fixture=filename):
                path = FIXTURES / filename
                self.assertTrue(path.exists(), f"缺少样例文件 {filename}")
                env = read_eml(path, STAGING)

                self.assertEqual(env.rfq_ids, expected["rfq_ids"], "RFQ 号")
                self.assertEqual(env.customer_name, expected["customer"], "客户名")
                self.assertEqual(len(env.attachments), expected["attachments"], "附件数量")

                joined = " ".join(env.warnings)
                for needle in expected["warnings"]:
                    self.assertIn(needle, joined, f"缺少告警 {needle}")
                for needle in expected["body_has"]:
                    self.assertIn(needle, env.body_text, f"正文缺少 {needle}")

    def test_attachments_of_full_fixture_are_usable(self) -> None:
        """带附件那封：三个附件都落盘、内容非空、哈希互不相同。"""
        env = read_eml(FIXTURES / "02_rfq_full_attachments.eml", STAGING)
        names = sorted(a.filename for a in env.attachments)
        self.assertEqual(names, ["drawing_CVR-310_RevB.pdf", "part_list.xlsx", "part_spec.pptx"])

        hashes = set()
        for att in env.attachments:
            p = Path(att.path)
            self.assertTrue(p.exists(), att.path)
            self.assertGreater(p.stat().st_size, 0)
            self.assertEqual(p.stat().st_size, att.size_bytes)
            hashes.add(att.sha256)
        self.assertEqual(len(hashes), 3, "三个附件内容应不同")

    def test_same_rfq_same_envelope_fields(self) -> None:
        """同一份 RFQ，只发正文 vs 正文+附件：身份信息必须一致（格式无关）。"""
        body_only = read_eml(FIXTURES / "01_rfq_body_only.eml", STAGING)
        full = read_eml(FIXTURES / "02_rfq_full_attachments.eml", STAGING)
        self.assertEqual(body_only.rfq_ids, full.rfq_ids)
        self.assertEqual(body_only.customer_name, full.customer_name)
        self.assertEqual(body_only.sender_email, full.sender_email)

    def test_bad_encoding_does_not_crash(self) -> None:
        """GBK 字节冒充 UTF-8：可以出现替换字符，但不能抛异常。"""
        env = read_eml(FIXTURES / "10_rfq_bad_encoding.eml", STAGING)
        self.assertTrue(env.body_text)
        self.assertEqual(env.rfq_ids, ["RFQ-2026-118"])

    def test_identity_levels_on_fixtures(self) -> None:
        """身份识别在样例上的等级：有签名的可自动，没线索的必须落草稿。"""
        expected = {
            "01_rfq_body_only.eml": "medium",  # 只有签名一条证据
            "06_not_an_rfq.eml": "draft",  # 没有公司线索
            "07_rfq_public_domain.eml": "medium",  # 公共邮箱，只能靠签名
        }
        for filename, level in expected.items():
            with self.subTest(fixture=filename):
                env = read_eml(FIXTURES / filename, STAGING)
                res = resolve_customer(env)
                self.assertEqual(res.level, level, f"{filename}: {res.to_dict()}")

    def test_drawing_title_upgrades_identity(self) -> None:
        """把图纸标题栏喂进去，客户识别应从 medium 升到 high。"""
        env = read_eml(FIXTURES / "02_rfq_full_attachments.eml", STAGING)
        before = resolve_customer(env)
        self.assertEqual(before.level, "medium")

        after = resolve_customer(
            env,
            attachment_texts={"drawing_CVR-310_RevB.pdf": "Example Customer Sdn Bhd - Drawing spec sheet"},
        )
        self.assertEqual(after.level, "high")
        self.assertGreater(after.confidence, before.confidence)


if __name__ == "__main__":
    unittest.main()
