"""建库 / 入库 / 看库 / 重跑。

    python tools/init_db.py                       # 建表（幂等）
    python tools/init_db.py --rebuild             # 清空重建（开发期重置）
    python tools/init_db.py --store a.eml b.eml   # 原件入库 + 解析（正文+附件）
    python tools/init_db.py --reparse 1           # 用当前解析器重跑 raw_email #1
    python tools/init_db.py --dump                # 看各层内容

业务编排在 quotation_agent.pipeline，这里只做命令行。
`--reparse` 是分层设计的意义：解析器改了，原件不用重新收集。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quotation_agent.cli_util import utf8_stdout  # noqa: E402
from quotation_agent.pipeline import ingest_email, reparse_email  # noqa: E402
from quotation_agent.store.db import SCHEMA_VERSION, connect, init_db, summary  # noqa: E402

# 开发期重置时清掉的全部历史表（含 v1/v2 的老表名）
ALL_TABLES = (
    "stage_block", "stage_attachment", "stage_email", "mart_rfq",
    "parse_run", "raw_attachment", "raw_email", "blob_store", "raw_source",
    "email_message", "attachment", "extract_block", "extract_run",
    "schema_meta", "db_meta",
)


def reset(conn: sqlite3.Connection) -> None:
    """清空重建：先关外键再按依赖顺序删。"""
    conn.execute("PRAGMA foreign_keys = OFF")
    for table in ALL_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table}")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.commit()
    print("all tables dropped for rebuild")


def dump(conn: sqlite3.Connection) -> None:
    print("\n== 各层行数 ==")
    for table, count in summary(conn).items():
        print(f"  {table:<18} {count}")

    print("\n== blob_store ==")
    for row in conn.execute("SELECT substr(sha256,1,12) AS h, size_bytes, storage FROM blob_store ORDER BY created_at"):
        print(f"  {row['h']}  {row['size_bytes']:>7} B  {row['storage']}")

    print("\n== raw_email / raw_attachment ==")
    for row in conn.execute(
        "SELECT id, subject, message_id, sender_email, to_recipients, sent_at, filename, size_bytes "
        "FROM raw_email ORDER BY id"
    ):
        print(f"  email #{row['id']} {row['subject']}")
        print(f"      {row['message_id']} | {row['sender_email']} -> {row['to_recipients']} | sent {row['sent_at']}")
    for row in conn.execute(
        "SELECT a.id, a.raw_email_id, a.filename, a.size_bytes FROM raw_attachment a ORDER BY a.id"
    ):
        print(f"    att #{row['id']:<3} (email {row['raw_email_id']}) {row['filename']:<30} {row['size_bytes']:>7} B")

    print("\n== stage_email ==")
    for row in conn.execute(
        "SELECT id, raw_email_id, run_id, subject, customer_name, customer_level, rfq_ids, warnings "
        "FROM stage_email ORDER BY id"
    ):
        print(f"  #{row['id']} raw={row['raw_email_id']} run={row['run_id']} {row['subject']}")
        print(f"      customer={row['customer_name'] or '-'} ({row['customer_level'] or '-'}) rfq={row['rfq_ids']}")
        print(f"      warnings={row['warnings']}")

    print("\n== stage_block（按邮件汇总）==")
    for row in conn.execute(
        "SELECT stage_email_id, COUNT(*) c FROM stage_block GROUP BY stage_email_id ORDER BY stage_email_id"
    ):
        print(f"  stage_email #{row['stage_email_id']}: {row['c']} blocks")


def main(argv: list[str] | None = None) -> int:
    utf8_stdout()
    ap = argparse.ArgumentParser(description="初始化 / 填充 email_extract.db")
    ap.add_argument("--db", default=str(ROOT / "data" / "email_extract.db"))
    ap.add_argument("--store", nargs="*", default=[], help="要入库的 .eml")
    ap.add_argument("--staging", default=str(ROOT / "artifacts"))
    ap.add_argument("--reparse", type=int, default=0, help="按 raw_email.id 重新解析")
    ap.add_argument("--rebuild", action="store_true", help="清空所有表后重建")
    ap.add_argument("--dump", action="store_true")
    args = ap.parse_args(argv)

    conn = connect(args.db)
    if args.rebuild:
        reset(conn)
    init_db(conn)
    print(f"schema ok: {args.db}（版本 {SCHEMA_VERSION}）")

    staging = Path(args.staging)
    staging.mkdir(parents=True, exist_ok=True)

    for eml in args.store:
        info = ingest_email(conn, eml, staging)
        print(f"  raw_email#{info['raw_id']} → run#{info['run_id']} → stage#{info['stage_email_id']}  "
              f"{info['file']}  客户={info['customer'] or '-'}（{info['level']}） "
              f"正文行={info['body_rows']} 附件={info['attachments']}")

    if args.reparse:
        info = reparse_email(conn, args.reparse, staging)
        print(f"  reparse raw_email#{info['raw_id']} → run#{info['run_id']} → stage#{info['stage_email_id']} "
              f"正文行={info['body_rows']}")

    if args.dump or args.store or args.reparse:
        dump(conn)

    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
