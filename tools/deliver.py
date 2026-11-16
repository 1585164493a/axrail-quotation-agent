"""生成一套交付物：报价单 PDF + 回信草稿 + 人工复核清单。

    python tools/deliver.py --email 2
    python tools/deliver.py --email 2 --out deliverables/RFQ-2026-118
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quotation_agent.cli_util import utf8_stdout  # noqa: E402
from quotation_agent.quote import build_quote, render_text  # noqa: E402
from quotation_agent.quote.render import (  # noqa: E402
    render_quote_pdf,
    render_reply_email,
    render_review_list,
)
from quotation_agent.store.db import connect, init_db  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="生成报价单 PDF / 回信草稿 / 复核清单")
    ap.add_argument("--db", default=str(ROOT / "data" / "email_extract.db"))
    ap.add_argument("--email", type=int, required=True, help="stage_email.id")
    ap.add_argument("--out", default="", help="输出目录，默认 deliverables/<rfq_no>")
    args = ap.parse_args(argv)

    conn = connect(args.db)
    init_db(conn)
    quote = build_quote(conn, args.email)

    out = Path(args.out) if args.out else ROOT / "deliverables" / quote.rfq.rfq_no
    out.mkdir(parents=True, exist_ok=True)

    pdf_path = render_quote_pdf(quote, out / f"{quote.quote_no}.pdf")
    (out / "reply-email.txt").write_text(render_reply_email(quote), encoding="utf-8")
    (out / "review-list.md").write_text(render_review_list(quote), encoding="utf-8")
    (out / "quote.txt").write_text(render_text(quote), encoding="utf-8")

    print(f"输出目录 {out}")
    for item in ("pdf", "reply-email.txt", "review-list.md", "quote.txt"):
        path = pdf_path if item == "pdf" else out / item
        print(f"  {item:<16} {path.stat().st_size:>7} B")

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
