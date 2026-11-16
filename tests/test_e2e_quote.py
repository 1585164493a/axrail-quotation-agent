"""端到端：同一份 RFQ 用不同格式送达，必须得到同一份报价。

这是题目里最硬的一条要求：
    1.30-5:00 用至少两种格式跑同一份 RFQ，展示拿到同一份报价、PDF 与邮件草稿。

这里在临时库里灌两封邮件：
- 02：Excel + PPT + 有文字层的 PDF（干净版）
- 11：脏 Excel + Word + 无文字层的 PDF
两者都覆盖 1-5 行，报价必须一致。
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.pipeline import full_run, ingest_email, parse_attachments  # noqa: E402
from quotation_agent.store.db import connect, init_db, summary  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TMP = ROOT / ".testtmp"


class EndToEndQuoteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        # 测试不调模型：固定用正则路径，保证确定性、不花钱、不依赖网络
        os.environ["LLM_EXTRACTION"] = "0"

    def setUp(self) -> None:
        TMP.mkdir(parents=True, exist_ok=True)
        self.db_path = TMP / "e2e.db"
        if self.db_path.exists():
            self.db_path.unlink()
        self.conn = connect(self.db_path)
        init_db(self.conn)
        self.staging = TMP / "e2e-artifacts"
        self.scratch = TMP / "e2e-scratch"

    def tearDown(self) -> None:
        self.conn.close()
        if self.db_path.exists():
            self.db_path.unlink()

    def run_email(self, name: str):
        info = ingest_email(self.conn, FIXTURES / name, self.staging)
        parse_attachments(self.conn, self.scratch)
        from quotation_agent.quote.build import build_quote

        return info, build_quote(self.conn, info["stage_email_id"])

    def test_two_formats_same_quote(self) -> None:
        """干净附件 vs 脏附件：报价必须完全一致。"""
        _, q_clean = self.run_email("02_rfq_full_attachments.eml")
        _, q_messy = self.run_email("11_rfq_messy_attachments.eml")

        self.assertEqual(
            [(p.line.part_no, p.line.qty, round(p.unit_price, 2)) for p in q_clean.priced],
            [(p.line.part_no, p.line.qty, round(p.unit_price, 2)) for p in q_messy.priced],
            "不同格式必须给出同样的行价格",
        )
        self.assertAlmostEqual(q_clean.total, q_messy.total, places=2)
        self.assertEqual(
            sorted(h.line.part_no for h in q_clean.held),
            sorted(h.line.part_no for h in q_messy.held),
        )

    def test_quote_numbers_match_brief(self) -> None:
        """第 1 行 21.20 成本 / 28.27 牌价 / 26.86 折后——题目算例。"""
        _, quote = self.run_email("02_rfq_full_attachments.eml")
        brk = next(p for p in quote.priced if p.line.part_no == "BRK-100")
        self.assertAlmostEqual(brk.unit_cost, 21.20, places=2)
        self.assertAlmostEqual(brk.base_price, 28.27, places=2)
        self.assertAlmostEqual(brk.unit_price, 26.86, places=2)
        self.assertAlmostEqual(brk.line_total, 13430.00, places=2)

    def test_conflict_and_holds_are_reported(self) -> None:
        _, quote = self.run_email("02_rfq_full_attachments.eml")
        self.assertEqual([c.part_no for c in quote.rfq.conflicts], ["CVR-310"])
        self.assertEqual(sorted(h.line.part_no for h in quote.held), ["HSG-400", "SPC-050"])
        self.assertTrue(quote.approval.required)
        joined = " ".join(quote.approval.reasons)
        self.assertIn("exceeds the", joined)
        self.assertIn("15%", joined)

    def test_quote_payload_is_stored_in_mart(self) -> None:
        info, quote = self.run_email("02_rfq_full_attachments.eml")
        row = self.conn.execute(
            "SELECT * FROM mart_rfq WHERE stage_email_id = ?", (info["stage_email_id"],)
        ).fetchone()
        self.assertIsNotNone(row, "mart_rfq 里应该有一份报价")
        self.assertEqual(row["rfq_no"], "RFQ-2026-118")
        self.assertIn("payload_json", row.keys())

    def test_every_price_line_has_traceable_refs(self) -> None:
        """题目要求：每笔价格都能追溯到某一行表格。"""
        _, quote = self.run_email("02_rfq_full_attachments.eml")
        for priced in quote.priced:
            self.assertTrue(priced.line.refs, f"{priced.line.part_no} 没有出处")
            rules = {t.rule for t in priced.trace}
            self.assertIn("P-MARGIN", rules)
            for trace in priced.trace:
                self.assertTrue(trace.detail, "trace 必须有说明")

    def test_body_only_quote_matches_attachment_quote(self) -> None:
        """只给邮件正文 vs 正文+全套附件：报价必须一样。

        正文里已经写全了 5 个零件，附件只是补充；两条路应当收敛到同一个数。
        """
        _, q_attachments = self.run_email("02_rfq_full_attachments.eml")
        _, q_body = self.run_email("01_rfq_body_only.eml")

        self.assertEqual(
            [(p.line.part_no, p.line.qty, round(p.unit_price, 2)) for p in q_body.priced],
            [(p.line.part_no, p.line.qty, round(p.unit_price, 2)) for p in q_attachments.priced],
            "正文与附件必须给出同样的行价格",
        )
        self.assertAlmostEqual(q_body.total, q_attachments.total, places=2)
        self.assertEqual(
            sorted(h.line.part_no for h in q_body.held),
            sorted(h.line.part_no for h in q_attachments.held),
        )
        # 正文那一路没有图纸，所以没有数量冲突；附件那一路才有
        self.assertEqual(q_body.rfq.conflicts, [])
        self.assertEqual([c.part_no for c in q_attachments.rfq.conflicts], ["CVR-310"])
        # 每一行的出处要能说清是正文还是附件
        self.assertTrue(all("body line" in r for r in q_body.priced[0].line.refs))


if __name__ == "__main__":
    unittest.main()
