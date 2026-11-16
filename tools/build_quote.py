"""从库里出一份报价单（命令行）。

    python tools/build_quote.py                 # 用最后一封有附件的邮件
    python tools/build_quote.py --email 2       # 指定 stage_email.id
    python tools/build_quote.py --payload       # 同时打印写进 mart_rfq 的 JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quotation_agent.cli_util import utf8_stdout  # noqa: E402
from quotation_agent.quote import build_quote, render_text  # noqa: E402
from quotation_agent.store.db import connect, init_db  # noqa: E402


def pick_email(conn) -> int:
    """默认挑最后一封有块的邮件。"""
    row = conn.execute(
        "SELECT stage_email_id, COUNT(*) c FROM stage_block GROUP BY stage_email_id "
        "ORDER BY stage_email_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise SystemExit("no parsed blocks yet - run tools/parse_attachments.py first")
    return int(row["stage_email_id"])


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="build a quote from stage_block")
    ap.add_argument("--db", default=str(ROOT / "data" / "email_extract.db"))
    ap.add_argument("--email", type=int, default=0, help="stage_email.id")
    ap.add_argument("--payload", action="store_true", help="print the mart_rfq payload")
    ap.add_argument("--out", default="", help="write the quote text to a file")
    args = ap.parse_args(argv)

    conn = connect(args.db)
    init_db(conn)

    email_id = args.email or pick_email(conn)
    quote = build_quote(conn, email_id)
    text = render_text(quote)

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(f"（stage_email #{email_id}）\n\n{text}\n", encoding="utf-8")
        print(f"written: {out}")
    else:
        print(f"（stage_email #{email_id}）\n")
        print(text)

    if args.payload:
        print("\n--- payload ---")
        print(json.dumps(quote.to_payload(), ensure_ascii=False, indent=2))

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
