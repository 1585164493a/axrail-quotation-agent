"""把邮箱里的未读邮件拉下来，存成 .eml 传到 S3 的 inbox/。

为什么用 IMAP 轮询而不是 SES 收信：
- SES 收信需要自己的域名 + MX 记录 + 退出沙箱审核，几天起步；
- IMAP 只要能登录就能用，当天能演示。

凭据不进代码：读 `_axrail_notes/.env.mail` 或环境变量。
    IMAP_HOST=imap.qq.com
    IMAP_USER=你的QQ邮箱
    IMAP_PASS=QQ邮箱的"授权码"（不是登录密码）

用法：
    python tools/pull_mail.py              # 拉一次未读
    python tools/pull_mail.py --loop 60    # 每 60 秒拉一次（演示用）
    python tools/pull_mail.py --all --days 3   # 拉最近 3 天（含已读）
    python tools/pull_mail.py --dry-run    # 只打印，不上传
"""

from __future__ import annotations

import argparse
import email
import hashlib
import imaplib
import json
import os
import re
import ssl
import sys

# 控制台可能是 GBK：主题里的零宽字符会让 print 直接抛 UnicodeEncodeError
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(errors="replace")
import time
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = Path(r"D:\pythoncode\_axrail_notes\.env.mail")
STATE_FILE = Path(r"D:\pythoncode\_axrail_notes\.mail_state.json")
BUCKET = "s3-quotation-agent"
PREFIX = "inbox/"


def load_env() -> None:
    if not ENV_FILE.exists():
        return
    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        os.environ.setdefault(name.strip(), value.strip())


def slugify(text: str, limit: int = 40) -> str:
    text = re.sub(r"[^\w\u4e00-\u9fff.-]+", "-", (text or "").strip())
    return (text[:limit].strip("-") or "mail").lower()


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def connect() -> imaplib.IMAP4_SSL:
    host = os.environ.get("IMAP_HOST", "imap.qq.com")
    user = os.environ.get("IMAP_USER")
    password = os.environ.get("IMAP_PASS")
    if not user or not password:
        raise SystemExit(
            "缺少 IMAP_USER / IMAP_PASS。\n"
            f"请创建 {ENV_FILE}，内容形如：\n"
            "  IMAP_HOST=imap.qq.com\n"
            "  IMAP_USER=xxx@qq.com\n"
            "  IMAP_PASS=授权码（QQ邮箱设置→账户→开启IMAP→生成授权码）"
        )
    client = imaplib.IMAP4_SSL(host, 993, ssl_context=ssl.create_default_context())
    client.login(user, password)
    client.select("INBOX")
    return client


def fetch_uids(client: imaplib.IMAP4_SSL, use_all: bool, days: int) -> list[bytes]:
    if use_all:
        since = (datetime.now() - timedelta(days=days)).strftime("%d-%b-%Y")
        status, data = client.search(None, "SINCE", since)
    else:
        status, data = client.search(None, "UNSEEN")
    if status != "OK":
        return []
    return data[0].split()


def main() -> int:
    parser = argparse.ArgumentParser(description="Pull mailbox emails into S3")
    parser.add_argument("--loop", type=int, default=0, help="poll every N seconds (0 = once)")
    parser.add_argument("--all", action="store_true", help="include read emails (last N days)")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument("--dry-run", action="store_true", help="print instead of uploading")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--filter", default="RFQ|询价|报价|quotation|quote",
                        help="only pull emails whose subject matches this regex")
    parser.add_argument("--no-filter", action="store_true", help="pull everything (noise included)")
    args = parser.parse_args()

    load_env()
    state = load_state()
    pattern = None if args.no_filter else re.compile(args.filter, re.IGNORECASE)

    client = None
    s3 = None
    if not args.dry_run:
        import boto3
        from botocore.config import Config

        session = boto3.Session(profile_name=os.environ.get("AWS_PROFILE", "aws"), region_name="ap-southeast-2")
        s3 = session.client("s3", config=Config(retries={"max_attempts": 6, "mode": "adaptive"}))

    def run_once() -> int:
        nonlocal client
        if client is None:
            client = connect()
        uids = fetch_uids(client, args.all, args.days)
        if not uids:
            print("  (no new email)")
            return 0

        uploaded = 0
        for uid in uids[-args.limit:]:  # 最新的 N 封（IMAP 返回按 UID 升序）
            status, payload = client.fetch(uid, "(RFC822)")
            if status != "OK" or not payload or not isinstance(payload[0], tuple):
                continue
            raw = payload[0][1]
            message = email.message_from_bytes(raw)
            message_id = (message.get("Message-ID") or hashlib.sha256(raw).hexdigest()).strip()
            if message_id in state:
                continue

            subject = str(message.get("Subject") or "")
            try:
                from email.header import decode_header, make_header

                subject = str(make_header(decode_header(subject)))
            except Exception:  # noqa: BLE001
                pass

            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            name = f"{stamp}-{slugify(subject)}-{uid.decode()}.eml"
            key = f"{PREFIX}{name}"

            if pattern and not pattern.search(subject):
                print(f"  skip (not an RFQ): {subject[:60]}")
                continue

            if args.dry_run:
                print(f"  [dry-run] {key}  ({len(raw)} bytes)  subject={subject[:50]}")
            else:
                s3.put_object(Bucket=BUCKET, Key=key, Body=raw,
                              ContentType="message/rfc822")
                client.store(uid, "+FLAGS", "\\Seen")
                state[message_id] = key
                uploaded += 1
                print(f"  uploaded {key}  ({len(raw)} bytes)")
            print(f"    subject: {subject[:70]}")

        if not args.dry_run:
            save_state(state)
        return uploaded

    if args.loop:
        print(f"polling every {args.loop}s … (Ctrl+C to stop)")
        while True:
            try:
                run_once()
            except Exception as exc:  # noqa: BLE001
                print(f"  ! {type(exc).__name__}: {exc}")
                client = None
            time.sleep(args.loop)

    count = run_once()
    print(f"\ndone: {count} new email(s) in s3://{BUCKET}/{PREFIX}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
