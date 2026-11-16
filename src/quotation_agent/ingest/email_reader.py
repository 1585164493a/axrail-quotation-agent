"""第一步 —— 邮件接入。

邮件是整条流水线的唯一入口。其它格式（Excel、PowerPoint、PDF、Word）
都是这封邮件的附件，所以这个模块只回答一个问题：

    "来了什么、谁发的、什么时候、带了什么附件？"

它**故意不**去理解件号、数量、价格——那些是第二步（格式解析）和
第三步（归一化）的事。

命令行：
    python -m quotation_agent.ingest.email_reader <文件.eml> [--staging DIR] [--out 文件.json]
"""

from __future__ import annotations

import argparse
import hashlib
import html as html_lib
import json
import re
from datetime import datetime
from email import policy
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from pathlib import Path

from ..models import AttachmentRef, Envelope

# 匹配 RFQ-2026-118 / RFQ 2026 118 / rfq_2026-118 这类编号
RFQ_RE = re.compile(r"RFQ[\s_\-]*(\d{4})[\s_\-]*(\d{2,})", re.IGNORECASE)

# 更宽松的询价编号："RFQ No.: 118/2026"、"Enquiry 118"、"询价单 2026-118"。
# 只认"询价"这一类前缀，避免把 PO 号、快递单号误当成询价编号。
LOOSE_ID_RE = re.compile(
    r"(?i)\b(?:RFQ|ENQ|ENQUIRY|INQUIRY|询价单|询价|报价请求|报价单)"
    r"\s*(?:no\.?|number|编号)?\s*[:：#\-–—]?\s*"
    r"([A-Z]{0,4}\d[\dA-Z/\-–—]{0,20})"
)

# 客户公司名，例如 "Example Customer Sdn Bhd"。
# 公司主体部分保持大小写敏感（避免抓到一串小写词），只让法律后缀忽略大小写，
# 因为签名里经常写成 "SDN. BHD." 这种全大写。
COMPANY_NAME_RE = re.compile(
    r"([A-Z][\w&.\-']*(?:\s+[A-Z][\w&.\-']*){0,5}\s+"
    r"(?i:Sdn\.?\s*Bhd\.?|Pte\.?\s*Ltd\.?|Bhd\.?|Ltd\.?|Limited|Inc\.?|LLC|GmbH|PLT))"
)

MAX_ATTACHMENT_BYTES = 64 * 1024 * 1024  # 单个附件上限 64 MB，防止把内存吃满


def _html_to_text(raw: str) -> str:
    """极简 HTML 转文本（不引第三方库）。"""
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", raw)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = html_lib.unescape(text)
    text = text.replace("\xa0", " ")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def _part_text(part: Message, subtype: str) -> str:
    """取一个 MIME 分段的正文；编码坏掉时退化为替换字符，不抛异常。"""
    try:
        content = part.get_content()
    except (LookupError, UnicodeDecodeError):
        payload = part.get_payload(decode=True) or b""
        charset = part.get_content_charset() or "utf-8"
        content = payload.decode(charset, errors="replace")
    if subtype == "html":
        return _html_to_text(content)
    return content


def _extract_body(msg: Message) -> tuple[str, list[str]]:
    """返回 (正文, 告警列表)。text/plain 优先，没有才退到 text/html。"""
    plain: list[str] = []
    rich: list[str] = []
    for part in msg.walk():
        if part.is_multipart():
            continue
        if part.get_filename() or part.get_content_disposition() == "attachment":
            continue  # 附件不参与正文
        subtype = part.get_content_type().split("/")[-1].lower()
        if part.get_content_maintype() != "text":
            continue
        if subtype == "plain":
            plain.append(_part_text(part, "plain"))
        elif subtype == "html":
            rich.append(_part_text(part, "html"))

    warnings: list[str] = []
    plain_text = [p.strip() for p in plain if p.strip()]
    rich_text = [p.strip() for p in rich if p.strip()]
    if plain_text:
        body = "\n".join(plain_text)
    elif rich_text:
        body = "\n".join(rich_text)
        warnings.append("body_html_only: body taken from the HTML part and converted to text")
    else:
        body = ""
        warnings.append("body_empty: the email has no text body")
    return body, warnings


def _safe_filename(name: str, used: set[str]) -> str:
    """把附件名洗成安全的文件名，并处理同一封邮件里的重名。"""
    base = Path(name).name.strip() or "attachment.bin"
    base = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base)
    if base in used:
        stem, suffix = Path(base).stem, Path(base).suffix
        i = 2
        while f"{stem}-{i}{suffix}" in used:
            i += 1
        base = f"{stem}-{i}{suffix}"
    used.add(base)
    return base


def _save_attachments(msg: Message, staging: Path, digest: str) -> tuple[list[AttachmentRef], list[str]]:
    """把附件写到同一个扁平目录里。

    文件名前面加邮件摘要前缀，这样两封都叫 part_list.xlsx 的邮件不会互相
    覆盖；同时只建一层目录，在没有写权限的机器上也能跑。
    """
    refs: list[AttachmentRef] = []
    warnings: list[str] = []
    used: set[str] = set()
    if any(part.get_filename() for part in msg.walk()):
        staging.mkdir(parents=True, exist_ok=True)
    for part in msg.walk():
        name = part.get_filename()
        if not name:
            continue
        payload = part.get_payload(decode=True) or b""
        if len(payload) > MAX_ATTACHMENT_BYTES:
            warnings.append(f"attachment_too_large: {name} ({len(payload)} bytes)")
            continue
        safe = _safe_filename(name, used)
        target = staging / f"{digest}__{safe}"
        target.write_bytes(payload)
        refs.append(
            AttachmentRef(
                filename=safe,
                content_type=part.get_content_type(),
                size_bytes=len(payload),
                path=str(target),
                sha256=hashlib.sha256(payload).hexdigest(),
            )
        )
    if not refs:
        warnings.append("no_attachments: no attachment on this email; specification files may be missing")
    return refs, warnings


def _normalise_rfq_id(raw: str) -> str | None:
    """把抓到的编号片段统一成 RFQ-<年>-<编号> / RFQ-<编号>。

    年份取 2000–2099 之间的四位数，其余数字取最后一个当序号。
    """
    nums = re.findall(r"\d+", raw)
    if not nums:
        return None
    year = next((n for n in nums if len(n) == 4 and 2000 <= int(n) <= 2099), None)
    rest = [n for n in nums if n != year]
    if year and rest:
        return f"RFQ-{year}-{rest[-1]}"
    if rest:
        return f"RFQ-{rest[-1]}"
    return None


def _extract_rfq_ids(text: str) -> list[str]:
    """先抓规范格式，再抓宽松格式；同一封邮件里重复出现的编号只留一个。"""
    ids: set[str] = set()
    for m in RFQ_RE.finditer(text):
        ids.add(f"RFQ-{m.group(1)}-{m.group(2)}")
    for m in LOOSE_ID_RE.finditer(text):
        normalised = _normalise_rfq_id(m.group(1))
        if normalised:
            ids.add(normalised)
    return sorted(ids)


def _guess_customer(body: str, sender_email: str) -> tuple[str, str]:
    """从签名里猜客户公司名，猜不到就退回发件域名并给告警。"""
    for line in reversed(body.splitlines()[-40:]):
        match = COMPANY_NAME_RE.search(line.strip().strip(",;"))
        if match and len(match.group(1)) <= 80:
            return match.group(1).strip(), ""
    domain = sender_email.split("@")[-1] if "@" in sender_email else ""
    if domain:
        return "", f"customer_name_not_found: no company name in the signature (sender domain {domain})"
    return "", "customer_name_not_found: no company name found"


def read_bytes(raw: bytes, source: str, staging_dir: Path) -> Envelope:
    """把一封原始邮件字节解析成 :class:`Envelope`。"""
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    subject = str(msg.get("Subject") or "").strip()
    from_pairs = getaddresses([str(msg.get("From") or "")])
    sender_name = from_pairs[0][0] if from_pairs else ""
    sender_email = from_pairs[0][1] if from_pairs else ""
    recipients = [addr for _, addr in getaddresses([str(msg.get("To") or "")]) if addr]

    date: datetime | None = None
    raw_date = msg.get("Date")
    if raw_date:
        try:
            date = parsedate_to_datetime(str(raw_date))
        except (TypeError, ValueError):
            date = None  # 日期坏了不致命，留空即可

    body, warnings = _extract_body(msg)

    # 附件扁平落盘，用邮件摘要做前缀
    digest = hashlib.sha256(raw).hexdigest()[:12]
    attachments, att_warnings = _save_attachments(msg, staging_dir, digest)
    warnings.extend(att_warnings)

    # RFQ 号：主题和正文都找，去重排序
    rfq_ids = _extract_rfq_ids(subject + "\n" + body)
    if not rfq_ids:
        warnings.append("rfq_id_not_found: no RFQ or enquiry number found in the subject or body")

    customer_name, customer_warning = _guess_customer(body, sender_email)
    if customer_warning:
        warnings.append(customer_warning)

    return Envelope(
        source=source,
        message_id=str(msg.get("Message-ID") or digest),
        subject=subject,
        sender_name=sender_name,
        sender_email=sender_email,
        recipients=recipients,
        date=date,
        body_text=body,
        rfq_ids=rfq_ids,
        customer_name=customer_name,
        customer_email_domain=sender_email.split("@")[-1] if "@" in sender_email else "",
        attachments=attachments,
        warnings=warnings,
    )


def read_eml(path: str | Path, staging_dir: str | Path = "artifacts") -> Envelope:
    """从磁盘读一封 .eml。"""
    p = Path(path)
    return read_bytes(p.read_bytes(), p.name, Path(staging_dir))


def parse_headers(raw: bytes) -> dict:
    """只读邮件头，不碰正文与附件。

    原始层用它填"信封字段"（发件人、收件人、主题、时间），
    这样不解析正文也能把邮件列出来、追责、查重。
    """
    msg = BytesParser(policy=policy.default).parsebytes(raw)

    from_pairs = getaddresses([str(msg.get("From") or "")])
    sender_name = from_pairs[0][0] if from_pairs else ""
    sender_email = from_pairs[0][1] if from_pairs else ""
    recipients = [addr for _, addr in getaddresses([str(msg.get("To") or "")]) if addr]

    sent_at = None
    raw_date = msg.get("Date")
    if raw_date:
        try:
            sent_at = parsedate_to_datetime(str(raw_date)).isoformat()
        except (TypeError, ValueError):
            sent_at = None

    return {
        "message_id": str(msg.get("Message-ID") or "").strip() or None,
        "subject": str(msg.get("Subject") or "").strip(),
        "sender_name": sender_name,
        "sender_email": sender_email,
        "recipients": recipients,
        "sent_at": sent_at,
    }


def main(argv: list[str] | None = None) -> int:
    from ..cli_util import utf8_stdout

    utf8_stdout()
    ap = argparse.ArgumentParser(description="第一步：把 .eml 解析成 Envelope（JSON）。")
    ap.add_argument("eml", help=".eml 文件路径")
    ap.add_argument("--staging", default="artifacts", help="附件落盘的扁平目录")
    ap.add_argument("--out", default="", help="把 Envelope 的 JSON 写到这个文件（UTF-8）")
    args = ap.parse_args(argv)

    envelope = read_eml(args.eml, args.staging)
    payload = json.dumps(envelope.to_dict(), ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(payload, encoding="utf-8")
        print(f"envelope written to {out}")
    else:
        print(payload)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
