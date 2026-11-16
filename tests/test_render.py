"""渲染测试：报价单 PDF、回信草稿、复核清单。

PDF 不靠肉眼验：用 pypdf 把文字抽回来，检查关键内容在不在。
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from quotation_agent.pipeline import ingest_email, parse_attachments  # noqa: E402
from quotation_agent.quote.build import build_quote  # noqa: E402
from quotation_agent.quote.render import (  # noqa: E402
    render_quote_pdf,
    render_reply_email,
    render_review_list,
)
from quotation_agent.store.db import connect, init_db  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"
TMP = ROOT / ".testtmp"


class RenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        TMP.mkdir(parents=True, exist_ok=True)
        cls.db_path = TMP / "render.db"
        if cls.db_path.exists():
            cls.db_path.unlink()
        cls.conn = connect(cls.db_path)
        init_db(cls.conn)
        info = ingest_email(cls.conn, FIXTURES / "02_rfq_full_attachments.eml", TMP / "render-artifacts")
        parse_attachments(cls.conn, TMP / "render-scratch")
        cls.quote = build_quote(cls.conn, info["stage_email_id"])
        cls.out = TMP / "render-out"
        cls.out.mkdir(parents=True, exist_ok=True)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.conn.close()
        if cls.db_path.exists():
            cls.db_path.unlink()

    def test_pdf_contains_the_quote(self) -> None:
        from pypdf import PdfReader

        path = render_quote_pdf(self.quote, self.out / "quote.pdf")
        raw = path.read_bytes()
        self.assertTrue(raw.startswith(b"%PDF-1.4"))

        text = "\n".join(page.extract_text() for page in PdfReader(str(path)).pages)
        for needle in ("QUOTATION", "Example Customer Sdn Bhd", "RFQ-2026-118",
                       "BRK-100", "CVR-310", "74,684.00"):
            self.assertIn(needle, text)
        # 挂起行也要在 PDF 上说明原因
        self.assertIn("Order quantity still to be confirmed", text)
        self.assertIn("drawing shows 800 pcs", text)

    def test_pdf_is_english_only(self) -> None:
        """给客户的 PDF 不能出现中文（Helvetica 渲染不了，会变成问号）。"""
        from pypdf import PdfReader

        path = render_quote_pdf(self.quote, self.out / "quote_en.pdf")
        text = "\n".join(page.extract_text() for page in PdfReader(str(path)).pages)
        self.assertFalse(any("\u4e00" <= ch <= "\u9fff" for ch in text), "PDF 里混入了中文")
        self.assertNotIn("??", text)

    def test_reply_email_asks_the_right_questions(self) -> None:
        reply = render_reply_email(self.quote)
        self.assertIn(self.quote.quote_no, reply)
        self.assertIn("SPC-050", reply)
        self.assertIn("order quantity", reply.lower())
        self.assertIn("HSG-400", reply)
        # 数量冲突方向必须正确：RFQ 1000，图纸 800
        self.assertIn("RFQ lists 1000 pcs while the drawing shows 800 pcs", reply)
        # 15% 折扣要走审批，不能在信里答应
        self.assertIn("15%", reply)
        self.assertIn("approval", reply.lower())
        self.assertNotIn("we agree to 15%", reply)

    def test_review_list_covers_flags_and_trace(self) -> None:
        review = render_review_list(self.quote)
        self.assertIn("Review list", review)
        self.assertIn("CVR-310.qty", review)
        self.assertIn("hold_no_qty", review)
        self.assertIn("hold_no_material", review)
        self.assertIn("sign-off", review)
        # 每笔价都要能追到规则
        self.assertIn("M-AL6061", review)
        self.assertIn("P-MARGIN", review)
        self.assertIn("part_list.xlsx", review)

    def test_three_outputs_agree_on_total(self) -> None:
        """PDF、回信、复核清单里的总额必须是同一个数。"""
        from pypdf import PdfReader

        path = render_quote_pdf(self.quote, self.out / "quote_total.pdf")
        pdf_text = "\n".join(page.extract_text() for page in PdfReader(str(path)).pages)
        reply = render_reply_email(self.quote)
        review = render_review_list(self.quote)
        money = f"{self.quote.total:,.2f}"
        self.assertIn(money, pdf_text)
        self.assertIn(money, reply)
        self.assertIn(money, review)


if __name__ == "__main__":
    unittest.main()
