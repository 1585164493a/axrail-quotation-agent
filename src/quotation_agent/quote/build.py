"""把库里的块跑成一份报价：归一化 → 定价 → 审批判断 → 写 mart_rfq。

这是"链路打通"的那一段：输入是 stage_block，输出是可直接渲染成报价单的 Quote。
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date

from .model import Approval, PricedLine, Quote
from .normalise import candidates_from_blocks, merge
from .pricing import (
    APPROVAL_TOTAL_THRESHOLD,
    POLICY_MAX_DISCOUNT,
    price_line,
)

DISCOUNT_RE = re.compile(
    r"(\d{1,2})\s*%\s*(?:off|discount|折扣|below|cheaper|lower)"
    r"|(\d{1,2})\s*%\s*(?:discount|off)\b"
    r"|(?:discount|折扣)\s*(?:of\s*)?(\d{1,2})\s*%",
    re.IGNORECASE,
)


def load_blocks(conn: sqlite3.Connection, stage_email_id: int) -> list[dict]:
    """取出这封邮件所有附件抽出来的块，按附件、顺序排好。"""
    rows = conn.execute(
        """
        SELECT COALESCE(a.filename, 'email body') AS filename,
               b.block_type, b.locator, b.ordinal, b.key, b.value, b.row_json
        FROM stage_block b
        LEFT JOIN stage_attachment a ON a.id = b.stage_attachment_id
        WHERE b.stage_email_id = ?
        ORDER BY b.stage_attachment_id, b.ordinal
        """,
        (stage_email_id,),
    ).fetchall()
    blocks = []
    for row in rows:
        blocks.append({
            "filename": row["filename"],
            "block_type": row["block_type"],
            "locator": row["locator"],
            "ordinal": row["ordinal"],
            "key": row["key"],
            "value": row["value"],
            "row": json.loads(row["row_json"]) if row["row_json"] else None,
        })
    return blocks


def requested_discount(body_text: str) -> float:
    """从正文里读客户要的折扣。

    客户的说法很杂："15% off"、"12% below your quote"、"give us a 10% discount"、
    "折扣 8%"。三种语序都认，取第一个数字。
    """
    match = DISCOUNT_RE.search(body_text or "")
    if not match:
        return 0.0
    value = next((group for group in match.groups() if group), None)
    return int(value) / 100 if value else 0.0


def build_quote(conn: sqlite3.Connection, stage_email_id: int) -> Quote:
    email = conn.execute("SELECT * FROM stage_email WHERE id = ?", (stage_email_id,)).fetchone()
    if email is None:
        raise SystemExit(f"no stage_email #{stage_email_id}")

    rfq_ids = json.loads(email["rfq_ids"] or "[]")
    rfq_no = rfq_ids[0] if rfq_ids else f"NO-RFQ-{stage_email_id}"

    blocks = load_blocks(conn, stage_email_id)
    candidates = candidates_from_blocks(blocks)
    rfq = merge(candidates, rfq_no=rfq_no, customer=email["customer_name"] or "")

    quote = Quote(rfq=rfq)
    quote.quote_no = f"Q-{rfq_no}-{date.today():%Y%m%d}"

    if not candidates:
        rfq.notes.append("No table rows available: only the email body, or the attachments were not parsed")

    for line in rfq.lines:
        result = price_line(line)
        if isinstance(result, PricedLine):
            quote.priced.append(result)
        else:
            quote.held.append(result)

    # ---- 审批判断 ----
    reasons: list[str] = []
    if quote.total >= APPROVAL_TOTAL_THRESHOLD:
        reasons.append(f"Quotation total {quote.total:,.2f} MYR exceeds the {APPROVAL_TOTAL_THRESHOLD:,.0f} MYR threshold")
    if quote.held:
        reasons.append(f"{len(quote.held)} line(s) cannot be priced yet (engineering / procurement)")
    wanted = requested_discount(email["body_text"] or "")
    if wanted > POLICY_MAX_DISCOUNT:
        reasons.append(f"Customer requested {wanted:.0%} discount, above the {POLICY_MAX_DISCOUNT:.0%} policy limit")
    if rfq.conflicts:
        reasons.append(f"{len(rfq.conflicts)} source conflict(s) (e.g. quantity or material disagree between documents)")

    quote.approval = Approval(required=bool(reasons), reasons=reasons)

    # ---- 落 mart ----
    conn.execute("DELETE FROM mart_rfq WHERE stage_email_id = ?", (stage_email_id,))
    conn.execute(
        "INSERT INTO mart_rfq (stage_email_id, rfq_no, customer_name, payload_json, built_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (
            stage_email_id, rfq_no, email["customer_name"] or "",
            json.dumps(quote.to_payload(), ensure_ascii=False),
            date.today().isoformat() + "T00:00:00+00:00",
        ),
    )
    conn.commit()
    return quote


def render_text(quote: Quote) -> str:
    """命令行里看的报价单（给客户的版式在 render.py）。"""
    lines = [
        f"Quotation {quote.quote_no}",
        f"Customer  {quote.rfq.customer or '-'}",
        f"RFQ       {quote.rfq.rfq_no}     valid {quote.valid_days} days",
        "",
        f"{'Part':<10}{'Material':<10}{'Qty':>7}{'Cost':>9}{'List':>9}{'Disc':>7}{'Unit':>9}{'Line total':>13}",
        "-" * 78,
    ]
    for p in quote.priced:
        lines.append(
            f"{p.line.part_no:<10}{p.line.material:<10}{(p.line.qty or 0):>7}"
            f"{p.unit_cost:>9.2f}{p.base_price:>9.2f}{p.discount_rate:>7.0%}"
            f"{p.unit_price:>9.2f}{p.line_total:>13,.2f}"
        )

    if quote.held:
        lines.append("")
        lines.append("Held (not quoted, pending confirmation):")
        for h in quote.held:
            lines.append(f"  {h.line.part_no:<10} {h.reason:<20} {h.detail}")

    if quote.rfq.conflicts:
        lines.append("")
        lines.append("Source conflicts:")
        for c in quote.rfq.conflicts:
            lines.append(f"  {c.part_no}.{c.field_name}: {c.describe()}")

    lines += [
        "",
        f"Total {quote.total:,.2f} MYR",
        f"Approval {quote.approval.describe()}",
    ]
    return "\n".join(lines)
