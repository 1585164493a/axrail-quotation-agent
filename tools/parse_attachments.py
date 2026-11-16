"""解析所有待处理的附件，把块写进 stage_block。

    python tools/parse_attachments.py              # 处理 status='pending' 的附件
    python tools/parse_attachments.py --all        # 重新解析全部附件（先清掉旧块）
    python tools/parse_attachments.py --dump       # 打印块

业务编排在 quotation_agent.pipeline，这里只做命令行。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quotation_agent.cli_util import utf8_stdout  # noqa: E402
from quotation_agent.pipeline import parse_attachments  # noqa: E402
from quotation_agent.store.db import connect, init_db  # noqa: E402


def dump(conn) -> None:
    for att in conn.execute(
        "SELECT a.* FROM stage_attachment a WHERE a.status = 'ok' ORDER BY a.id"
    ):
        blocks = conn.execute(
            "SELECT block_type, locator, value, row_json FROM stage_block "
            "WHERE stage_attachment_id = ? ORDER BY ordinal", (att["id"],)
        ).fetchall()
        print(f"\n[{att['filename']}]  {len(blocks)} 块")
        for b in blocks:
            body = b["value"] if b["value"] is not None else b["row_json"]
            print(f"  {b['block_type']:<9} {b['locator']:<28} {(body or '')[:110]}")


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="解析附件并写入 stage_block")
    ap.add_argument("--db", default=str(ROOT / "data" / "email_extract.db"))
    ap.add_argument("--all", action="store_true", help="重新解析全部附件")
    ap.add_argument("--dump", action="store_true")
    args = ap.parse_args(argv)

    conn = connect(args.db)
    init_db(conn)

    results = parse_attachments(conn, ROOT / "artifacts" / "_parse", reparse_all=args.all)
    if not results:
        print("没有待解析的附件（加 --all 可重跑）")
    for info in results:
        flag = "ok  " if info["ok"] else "FAIL"
        warn = ", ".join(w.split(":")[0] for w in info["warnings"]) or "—"
        print(f"  {flag} {info['file']:<30} 块={info['blocks']:<3} 告警={warn}"
              + (f"  错误={info['error'][:60]}" if info["error"] else ""))

    if args.dump:
        dump(conn)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
