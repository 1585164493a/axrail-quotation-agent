"""第五步：把 Quote 渲染成三样东西。

    报价单 PDF      给客户看
    回信草稿        发给采购，并把缺的信息问清楚
    人工复核清单    给人看：哪里被标了、为什么、谁要批

三条都从同一个 Quote 对象出来，保证"客户看到的价"和"复核看到的价"永远一致。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

from .model import Quote
from .pdf import MARGIN, PAGE_H, PAGE_W, PdfDoc

# 表格列位置（pt）
COLS = [MARGIN, MARGIN + 62, MARGIN + 182, MARGIN + 252, MARGIN + 306, MARGIN + 386, MARGIN + 446]
COL_RIGHT = PAGE_W - MARGIN


def _money(value: float) -> str:
    return f"{value:,.2f}"


# PDF 用 Helvetica/WinAnsi：÷ − × ± 这类符号会变成 "?"，换成 ASCII 写法
_PDF_MAP = {"÷": "/", "−": "-", "×": "x", "±": "+/-", "–": "-", "—": "-", "≈": "~"}


def _pdf_safe(text: str) -> str:
    for bad, good in _PDF_MAP.items():
        text = text.replace(bad, good)
    return text


# 挂起原因 → 给客户看的英文说明（内部复核清单仍用中文 detail）
HOLD_REASON_EN = {
    "hold_no_qty": "Order quantity still to be confirmed, so the setup cost cannot be spread.",
    "hold_no_material": "Material is not on our standard price list; a material quotation is being obtained.",
    "hold_no_rate": "Tolerance is tighter than our standard machining range; engineering review required.",
    "hold_no_tolerance": "Tolerance could not be read from the documents; please confirm.",
    "hold_no_mass_or_cycle": "Part mass or cycle time is missing, so material and machining cost cannot be calculated.",
}

HOLD_REASON_SHORT_EN = {
    "hold_no_qty": "quantity to be confirmed",
    "hold_no_material": "material not on price list",
    "hold_no_rate": "tolerance needs engineering review",
    "hold_no_tolerance": "tolerance unclear",
    "hold_no_mass_or_cycle": "missing mass or cycle time",
}


def _hold_en(held) -> str:
    return HOLD_REASON_EN.get(held.reason, held.detail)


def _split_qty_conflict(conflict) -> tuple[str | None, str | None]:
    """把数量冲突拆成（RFQ 数量, 图纸数量）；靠出处里的文件名判断。"""
    rfq_value, drawing_value = None, None
    for value, source in conflict.values:
        if "drawing" in source.lower() or ".pdf" in source.lower():
            drawing_value = value
        else:
            rfq_value = value
    return rfq_value, drawing_value


def _assumptions(quote: Quote) -> list[str]:
    items = [
        f"All prices in MYR, valid for {quote.valid_days} days from the quotation date.",
        "Prices exclude freight, packing, taxes and any tooling not listed here.",
        "Delivery: as requested in the RFQ (6 weeks), subject to confirmation at order.",
        "Volume discount applied per line from the standard tier (5% from 500 pcs, 8% from 1,000 pcs).",
    ]
    for conflict in quote.rfq.conflicts:
        if conflict.field_name == "qty":
            rfq_qty, drawing_qty = _split_qty_conflict(conflict)
            items.append(
                f"{conflict.part_no}: quoted at {rfq_qty} pcs as per the RFQ; the drawing shows "
                f"{drawing_qty} pcs. Price will be confirmed once the order quantity is agreed."
            )
        else:
            items.append(f"{conflict.part_no}: {conflict.field_name} differs between documents; please confirm.")
    if quote.held:
        items.append("Items on hold are not included in the total.")
    return items


def render_quote_pdf(quote: Quote, path: str | Path) -> Path:
    """写报价单 PDF。"""
    doc = PdfDoc()

    # ---- 抬头 ----
    doc.text(MARGIN, PAGE_H - MARGIN, "QUOTATION", 20, bold=True)
    doc.text_right(COL_RIGHT, PAGE_H - MARGIN, quote.quote_no, 11, bold=True)
    doc.y = PAGE_H - MARGIN - 22
    doc.text(MARGIN, doc.y, "Precision CNC machining - quotation", 9)

    doc.y -= 34
    doc.line(MARGIN, doc.y + 12, COL_RIGHT, doc.y + 12, 0.8)

    left_y = doc.y
    doc.text(MARGIN, left_y, "Customer", 8)
    doc.text(MARGIN + 60, left_y, quote.rfq.customer or "-", 10, bold=True)
    doc.text(MARGIN, left_y - 15, "RFQ no.", 8)
    doc.text(MARGIN + 60, left_y - 15, quote.rfq.rfq_no, 10)

    doc.text(MARGIN + 300, left_y, "Date", 8)
    doc.text(MARGIN + 340, left_y, date.today().isoformat(), 10)
    doc.text(MARGIN + 300, left_y - 15, "Valid", 8)
    doc.text(MARGIN + 340, left_y - 15, f"{quote.valid_days} days", 10)

    # ---- 明细表 ----
    doc.y = left_y - 48
    header_y = doc.y
    doc.rect(MARGIN - 4, header_y - 4, COL_RIGHT - MARGIN + 8, 16)
    for x, label in zip(COLS, ["Part no.", "Description", "Material", "Qty", "Unit price", "Disc.", "Line total"]):
        doc.text(x, header_y, label, 8, bold=True)
    doc.y -= 18

    for priced in quote.priced:
        line = priced.line
        doc.text(COLS[0], doc.y, line.part_no, 9)
        doc.text(COLS[1], doc.y, (line.description or "")[:34], 9)
        doc.text(COLS[2], doc.y, line.material, 9)
        doc.text_right(COLS[4] - 8, doc.y, str(line.qty or "-"), 9)
        doc.text_right(COLS[5], doc.y, _money(priced.unit_price), 9)
        doc.text(COLS[5] + 12, doc.y, f"{priced.discount_rate:.0%}", 9)
        doc.text_right(COL_RIGHT, doc.y, _money(priced.line_total), 9)
        doc.y -= 15

    doc.y -= 6
    doc.line(MARGIN, doc.y + 10, COL_RIGHT, doc.y + 10, 0.6)
    doc.text_right(COL_RIGHT - 110, doc.y - 4, "Total (MYR)", 10, bold=True)
    doc.text_right(COL_RIGHT, doc.y - 4, _money(quote.total), 11, bold=True)
    doc.y -= 30

    # ---- 挂起行 ----
    if quote.held:
        doc.text(MARGIN, doc.y, "Not quoted - pending confirmation", 10, bold=True)
        doc.y -= 15
        for held in quote.held:
            qty_note = f"{held.line.qty:,} pcs" if held.line.qty else "qty TBC"
            descriptor = held.line.description or "no description"
            doc.text(MARGIN, doc.y, f"{held.line.part_no}  ·  {qty_note}  ·  {descriptor}", 9, bold=True)
            doc.y -= 12
            doc.paragraph(_hold_en(held), size=8, indent=12, gap=11)
            doc.y -= 3

    # ---- 假设 ----
    doc.text(MARGIN, doc.y, "Assumptions and notes", 10, bold=True)
    doc.y -= 14
    for item in _assumptions(quote):
        doc.paragraph(f"- {item}", size=8, indent=2, gap=11)
        doc.y -= 1

    # ---- 页脚 ----
    doc.text(MARGIN, MARGIN - 12, f"{quote.quote_no}  |  prices in MYR  |  page 1 of 1", 7)

    return doc.save(path)


def render_reply_email(quote: Quote) -> str:
    """英文回信草稿：附报价、问缺的信息、说清折扣与审批。"""
    missing = [h for h in quote.held]
    lines = [
        f"Subject: Quotation {quote.quote_no} - {quote.rfq.rfq_no}",
        "",
        f"Dear {quote.rfq.customer.split()[0] if quote.rfq.customer else 'Sir/Madam'} team,",
        "",
        f"Thank you for your enquiry {quote.rfq.rfq_no}. Please find our quotation {quote.quote_no} attached.",
        "",
    ]

    if quote.priced:
        lines.append("Quoted lines:")
        for priced in quote.priced:
            line = priced.line
            lines.append(
                f"  - {line.part_no} ({line.description or 'part'}, {line.material}), "
                f"{line.qty} pcs at MYR {priced.unit_price:,.2f} per piece "
                f"({priced.discount_rate:.0%} volume discount), line total MYR {priced.line_total:,.2f}"
            )
        lines.append("")
        lines.append(f"Total: MYR {quote.total:,.2f}. The quotation is valid for {quote.valid_days} days.")
        lines.append("")

    if missing:
        lines.append("We could not quote the following items yet:")
        for held in missing:
            if held.reason == "hold_no_qty":
                lines.append(
                    f"  - {held.line.part_no}: the order quantity is still to be confirmed. "
                    f"Please advise the quantity and we will price it immediately."
                )
            elif held.reason == "hold_no_material":
                lines.append(
                    f"  - {held.line.part_no}: {held.line.material_raw or 'this material'} is not on our "
                    f"standard price list. We are obtaining a material quotation and will revert."
                )
            else:
                lines.append(f"  - {held.line.part_no}: {held.detail}")
        lines.append("")

    for conflict in quote.rfq.conflicts:
        if conflict.field_name == "qty":
            rfq_qty, drawing_qty = _split_qty_conflict(conflict)
            lines.append(
                f"One point to confirm: for {conflict.part_no} the RFQ lists {rfq_qty} pcs while the "
                f"drawing shows {drawing_qty} pcs. We have quoted {conflict.part_no} at the RFQ "
                f"quantity; please confirm which figure to use and we will adjust if needed."
            )
            lines.append("")

    if any("折扣" in r or "%" in r for r in quote.approval.reasons):
        lines.append(
            "Regarding the requested 15% new-customer discount: our volume discount is already included "
            "in the prices above. Anything beyond that needs approval from our sales manager, so we will "
            "come back to you separately."
        )
        lines.append("")

    lines += [
        "Please let us know if you need any clarification.",
        "",
        "Best regards,",
        "Sales team",
        "Precision CNC machining",
    ]
    return "\n".join(lines)


def render_review_list(quote: Quote) -> str:
    """人工复核清单（markdown）：标记了什么、为什么、谁要批、每笔价怎么来的。"""
    out = [
        f"# Review list - {quote.quote_no}",
        "",
        f"- Customer: {quote.rfq.customer or '-'}",
        f"- RFQ: {quote.rfq.rfq_no}",
        f"- Total: {quote.total:,.2f} MYR",
        f"- Approval: {quote.approval.describe()}",
        "",
    ]

    out.append("## What a person must look at")
    if quote.rfq.conflicts:
        out.append("")
        out.append("### Source conflicts (not resolved automatically)")
        for conflict in quote.rfq.conflicts:
            out.append(f"- **{conflict.part_no}.{conflict.field_name}**: {conflict.describe()}")
    if quote.held:
        out.append("")
        out.append("### Lines on hold (not quoted)")
        for held in quote.held:
            refs = "; ".join(held.line.refs) or "-"
            out.append(f"- **{held.line.part_no}** `{held.reason}`: {held.detail}")
            out.append(f"  - source: {refs}")
    if not quote.rfq.conflicts and not quote.held:
        out.append("- none (every line was priced automatically)")

    out.append("")
    out.append("## Traceability of the quoted lines")
    out.append("")
    out.append("| Part | Qty | Cost | Unit price | Line total | Sources |")
    out.append("|---|---|---|---|---|---|")
    for priced in quote.priced:
        refs = "<br>".join(priced.line.refs) or "-"
        out.append(
            f"| {priced.line.part_no} | {priced.line.qty} | {priced.unit_cost:,.2f} | "
            f"{priced.unit_price:,.2f} | {priced.line_total:,.2f} | {refs} |"
        )

    out.append("")
    out.append("## How each number was produced")
    for priced in quote.priced:
        out.append("")
        out.append(f"**{priced.line.part_no}**")
        for trace in priced.trace:
            out.append(f"- `{trace.rule}` {trace.detail} = {trace.amount:,.2f}")
    return "\n".join(out)


def _sources_summary(refs: list[str], max_locators: int = 4) -> str:
    """把 refs 按文件收拢：同一份文件里的多个行号只写一次文件名。

    refs 形如 "part_list.xlsx @ Part list!A7"、"drawing.pdf @ page 1 L13"。
    """
    grouped: dict[str, list[str]] = {}
    order: list[str] = []
    for ref in refs:
        if " @ " in ref:
            filename, locator = ref.split(" @ ", 1)
        else:
            filename, locator = ref, ""
        if filename not in grouped:
            grouped[filename] = []
            order.append(filename)
        if locator and locator not in grouped[filename]:
            grouped[filename].append(locator)

    parts = []
    for filename in order:
        locators = grouped[filename]
        shown = locators[:max_locators]
        extra = len(locators) - len(shown)
        text = filename
        if shown:
            text += f" ({', '.join(shown)}" + (f" +{extra} more" if extra > 0 else "") + ")"
        parts.append(text)
    return "; ".join(parts) or "-"


def render_review_pdf(quote: Quote, path: str | Path, approval_status: str = "not_required") -> Path:
    """人工复核清单 PDF：要人看什么、为什么、审批状态、每个数字的出处与规则。

    题目要求（[16]）：what was flagged and why / approval status /
    every price traces back to a table row and a rule。这一页按这个顺序排。
    """
    doc = PdfDoc()

    doc.text(MARGIN, PAGE_H - MARGIN, "REVIEW LIST", 18, bold=True)
    doc.text_right(COL_RIGHT, PAGE_H - MARGIN, quote.quote_no, 11, bold=True)
    doc.y = PAGE_H - MARGIN - 30
    doc.text(MARGIN, doc.y, "Internal - for the person who signs off", 9)

    doc.y -= 26
    doc.line(MARGIN, doc.y + 10, COL_RIGHT, doc.y + 10, 0.8)

    y = doc.y
    # 左列：三组 label / value 同行对齐
    left_rows = [
        ("Customer", quote.rfq.customer or "-", 10, True),
        ("RFQ", quote.rfq.rfq_no, 10, False),
        ("Total", f"{_money(quote.total)} MYR", 10, True),
    ]
    for offset, (label, value, size, bold) in enumerate(left_rows):
        row_y = y - offset * 16
        doc.text(MARGIN, row_y, label, 8)
        doc.text(MARGIN + 70, row_y, value, size, bold=bold)

    # 右列：同样是 label / value 同行，别再往下错一行
    right_rows = [
        ("Approval status", approval_status.upper().replace("_", " "), 11, True),
        ("Issued", date.today().isoformat(), 9, False),
    ]
    for offset, (label, value, size, bold) in enumerate(right_rows):
        row_y = y - offset * 16
        doc.text(MARGIN + 300, row_y, label, 8)
        doc.text(MARGIN + 385, row_y, value, size, bold=bold)

    doc.y = y - 58
    doc.line(MARGIN, doc.y + 8, COL_RIGHT, doc.y + 8, 0.4)

    # ---- 1. 审批 ----
    doc.y -= 12
    doc.write("1  APPROVAL", 11, bold=True, gap=14)
    if quote.approval.required:
        for reason in quote.approval.reasons:
            doc.paragraph(f"- {reason}", 9, indent=8, gap=11)
    else:
        doc.paragraph("No approval required (within delegated authority).", 9, indent=8, gap=11)

    # ---- 2. 要人看什么 ----
    doc.y -= 8
    doc.write("2  WHAT A PERSON MUST CHECK", 11, bold=True, gap=14)

    if quote.rfq.conflicts:
        doc.paragraph("Source conflicts (not resolved automatically)", 9, indent=0, gap=12)
        for conflict in quote.rfq.conflicts:
            doc.paragraph(f"- {conflict.part_no}.{conflict.field_name}: {conflict.describe()}", 8.5, indent=8)

    low_confidence = [p for p in quote.priced if p.line.confidence < 0.55]
    if low_confidence:
        doc.paragraph("Low confidence (quantity / material / tolerance)", 9, indent=0, gap=12)
        for priced in low_confidence:
            flags = "; ".join(priced.line.flags) or "sources disagree or unclear"
            doc.paragraph(
                f"- {priced.line.part_no}: confidence {priced.line.confidence:.2f} - {flags}",
                8.5, indent=8,
            )

    if quote.held:
        doc.paragraph("Lines on hold (not quoted)", 9, indent=0, gap=12)
        for held in quote.held:
            doc.paragraph(f"- {held.line.part_no} [{held.reason}]: {held.detail}", 8.5, indent=8)

    if not (quote.rfq.conflicts or quote.held or low_confidence):
        doc.paragraph("Nothing flagged - every line was priced and every field was consistent.", 9, indent=8)

    # ---- 3. 价格溯源 ----
    doc.y -= 10
    doc.write("3  PRICE TRACEABILITY (table row + rule)", 11, bold=True, gap=14)
    for priced in quote.priced:
        rules = " / ".join(trace.rule for trace in priced.trace)
        sources = _sources_summary(priced.line.refs)
        doc.write(f"{priced.line.part_no}  qty {priced.line.qty}  unit {_money(priced.unit_price)}", 9, bold=True, indent=0, gap=11)
        doc.paragraph(f"sources: {sources}", 8, indent=8, gap=10)
        doc.paragraph(f"rules:   {rules}", 8, indent=8, gap=11)

    # ---- 4. 规则明细 ----
    doc.y -= 10
    doc.write("4  RULE DETAIL", 11, bold=True, gap=14)
    for priced in quote.priced:
        doc.write(priced.line.part_no, 9, bold=True, indent=0, gap=11)
        for trace in priced.trace:
            doc.paragraph(_pdf_safe(f"{trace.rule}: {trace.detail} = {_money(trace.amount)}"), 8, indent=8, gap=10)

    return doc.save(path)
