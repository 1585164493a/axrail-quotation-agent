"""生成第一步（邮件接入）用的测试邮件。

这些 .eml 是**确定性**生成的：日期、Message-ID 都写死，重跑结果一致。
生成一次之后，`tests/fixtures/*.eml` 就可以直接提交进仓库，测试不再依赖脚本。

用法：
    python tests/fixtures/build_fixtures.py
"""

from __future__ import annotations

from email.message import EmailMessage
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATTACH = HERE / "attachments"

RFQ_BODY = """Hi team,

Please quote the parts below. Our part list (Excel) and spec slides are also attached.
Delivery needed in 6 weeks to our Shah Alam plant.

  1. BRK-100 Mounting bracket, AL6061, 500 pcs, tol +/-0.10 mm, 0.40 kg, approx 6 min, anodise
  2. SHF-220 Drive shaft D20x150, SS304, 200 pcs, tol +/-0.02 mm, 0.37 kg, approx 9 min, no finish
  3. CVR-310 Pump cover, AL6061, 1,000 pcs, tol +/-0.05 mm, 0.85 kg, approx 12 min, anodise
  4. SPC-050 Spacer, SS304, qty to follow, tol +/-0.10 mm, 0.05 kg, approx 2 min, no finish
  5. HSG-400 Valve housing, Ti Gr5, 50 pcs, tol +/-0.005 mm, 1.20 kg, approx 40 min, no finish

Can you also give us 15% off as we are a new customer?

Thanks,
Alex Tan
Procurement, Example Customer Sdn Bhd
"""


def _base(subject: str, message_id: str, sender: str = "Alex Tan <buyer@example-customer.test>") -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = "sales@example-cnc-shop.test"
    msg["Date"] = "Mon, 02 Nov 2026 09:14:00 +0800"
    msg["Message-ID"] = f"<{message_id}@example-customer.test>"
    return msg


def write(name: str, payload: bytes) -> None:
    (HERE / name).write_bytes(payload)
    print(f"  {name}  ({len(payload)} bytes)")


def f01_body_only() -> bytes:
    msg = _base("RFQ-2026-118 - CNC parts, delivery in 6 weeks", "fx01")
    msg.set_content(RFQ_BODY)
    return msg.as_bytes()


def f02_full_attachments() -> bytes:
    msg = _base("RFQ-2026-118 - CNC parts, delivery in 6 weeks", "fx02")
    msg.set_content(RFQ_BODY)
    files = [
        ("part_list.xlsx", "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("part_spec.pptx", "application", "vnd.openxmlformats-officedocument.presentationml.presentation"),
        ("drawing_CVR-310_RevB.pdf", "application", "pdf"),
    ]
    for name, maintype, subtype in files:
        data = (ATTACH / name).read_bytes()
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


def f03_html_only() -> bytes:
    msg = _base("RFQ-2026-118 - parts (HTML only)", "fx03")
    msg.set_content("")
    msg.add_alternative(
        "<div>Hi team,<br>Please quote the 5 parts, RFQ-2026-118.<br>"
        "Delivery in 6 weeks.<br>Thanks,<br>Alex Tan<br>Procurement, Example Customer Sdn Bhd</div>",
        subtype="html",
    )
    return msg.as_bytes()


def f04_reply_chain() -> bytes:
    msg = _base("Re: RFQ-2026-118 - CNC parts, delivery in 6 weeks", "fx04")
    msg.set_content(
        "Alex,\n\nOne correction: the spacer quantity is still to be confirmed, we will come back to you.\n\n"
        "Best regards,\nSales\nExample CNC Shop Sdn Bhd\n\n"
        "-----Original Message-----\nFrom: Alex Tan\nSent: Monday, 2 November 2026\nSubject: RFQ-2026-118 - CNC parts\n\n"
        + RFQ_BODY
    )
    return msg.as_bytes()


def f05_no_rfq_id() -> bytes:
    msg = _base("Quick quote please", "fx05")
    msg.set_content(
        "Hello,\n\nCould you price 20 of these brackets for us?\nMaterial AL6061, mass 0.4 kg, tolerance +/-0.10 mm.\n\n"
        "Thanks,\nAlex Tan\nProcurement, Example Customer Sdn Bhd\n"
    )
    return msg.as_bytes()


def f06_not_an_rfq() -> bytes:
    msg = _base("Interview follow-up and next steps", "fx06", sender="Kelvin Kok <kelvinkok@axrail.com>")
    msg.set_content(
        "Hi Wu Pengxu,\n\nThank you for your time at the interview today.\n\n"
        "A few key points:\n- Please submit within 2 days.\n- All written material should be in English.\n\n"
        "Good luck,\nKelvin Kok\n"
    )
    return msg.as_bytes()


def f07_public_domain() -> bytes:
    msg = _base("RFQ-2026-118 from our purchasing team", "fx07", sender="Alex Tan <alex.work@gmail.com>")
    msg.set_content(RFQ_BODY)
    return msg.as_bytes()


def f08_chinese() -> bytes:
    msg = _base("询价单 2026-118 请报价", "fx08", sender="陈伟 <chen.wei@example-customer.test>")
    msg.set_content(
        "你好，\n\n请给我们报下面 5 个零件的价格，交期 6 周。\n"
        "1. BRK-100 安装支架 AL6061 500 件 公差 ±0.10 mm\n"
        "2. SHF-220 传动轴 SS304 200 件 公差 ±0.02 mm\n\n"
        "另外想问一下新客户能不能给 15% 折扣。\n\n谢谢\n陈伟\n采购部，Example Customer Sdn Bhd\n"
    )
    return msg.as_bytes()


def f09_two_rfqs_in_one() -> bytes:
    msg = _base("Two RFQs from us: RFQ-2026-118 and RFQ-2026-119", "fx09")
    msg.set_content(
        "Hello,\n\nWe are sending two requests in one email by mistake, sorry.\n\n"
        "RFQ-2026-118: the 5 parts in the attached list.\n"
        "RFQ-2026-119: 50 pcs of SHF-220, same spec.\n\n"
        "Thanks,\nAlex Tan\nProcurement, Example Customer Sdn Bhd\n"
    )
    return msg.as_bytes()


def f10_bad_encoding() -> bytes:
    """声明 utf-8 但实际是 GBK 字节：解析不能崩，只能降级。"""
    body = "请报价：CVR-310 泵盖 800 件，公差 ±0.05 mm。谢谢。陈伟，Example Customer Sdn Bhd".encode("gbk")
    head = (
        "Subject: RFQ-2026-118 bad encoding\r\n"
        "From: Alex Tan <buyer@example-customer.test>\r\n"
        "To: sales@example-cnc-shop.test\r\n"
        "Date: Mon, 02 Nov 2026 09:14:00 +0800\r\n"
        "Message-ID: <fx10@example-customer.test>\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=utf-8\r\n"
        "Content-Transfer-Encoding: 8bit\r\n\r\n"
    )
    return head.encode("ascii") + body


def f11_messy_attachments() -> bytes:
    """三个"脏"附件：带千分位和多余列的 Excel、Word 表格、没有文字层的 PDF。"""
    msg = _base("RFQ-2026-118 - parts (messy attachments)", "fx11")
    msg.set_content(
        "Hi team,\n\nPlease quote the attached part list. The Word file has the spec, "
        "and the drawing is a scan so you may need to read it carefully.\n\n"
        "Thanks,\nAlex Tan\nProcurement, Example Customer Sdn Bhd\n"
    )
    for name, maintype, subtype in [
        ("part_list_messy.xlsx", "application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
        ("spec_table.docx", "application", "vnd.openxmlformats-officedocument.wordprocessingml.document"),
        ("drawing_no_text.pdf", "application", "pdf"),
    ]:
        data = (ATTACH / name).read_bytes()
        msg.add_attachment(data, maintype=maintype, subtype=subtype, filename=name)
    return msg.as_bytes()


BUILDERS = [
    ("01_rfq_body_only.eml", f01_body_only),
    ("02_rfq_full_attachments.eml", f02_full_attachments),
    ("03_rfq_html_only.eml", f03_html_only),
    ("04_rfq_reply_chain.eml", f04_reply_chain),
    ("05_rfq_no_id.eml", f05_no_rfq_id),
    ("06_not_an_rfq.eml", f06_not_an_rfq),
    ("07_rfq_public_domain.eml", f07_public_domain),
    ("08_rfq_chinese.eml", f08_chinese),
    ("09_two_rfqs.eml", f09_two_rfqs_in_one),
    ("10_rfq_bad_encoding.eml", f10_bad_encoding),
    ("11_rfq_messy_attachments.eml", f11_messy_attachments),
]


def main() -> None:
    print(f"writing fixtures to {HERE}")
    for name, builder in BUILDERS:
        write(name, builder())


if __name__ == "__main__":
    main()
