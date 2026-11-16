"""生成多样化的 RFQ 测试邮件（不同客户、零件、材料、数量、边界情况）。

为什么要生成而不是手写：每封邮件只是信封字段 + 正文的差别，
用一个场景表统一生成，改一条场景就多一封邮件，也不容易写错格式。

用法：python tools/make_email_fixtures.py
产物：tests/fixtures/emails/*.eml
"""

from __future__ import annotations

from email.message import EmailMessage
from email.utils import formatdate
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "emails"

# 场景表：(文件名, RFQ号, 客户名, 发件人, 主题, 正文)
SCENARIOS = [
    (
        "rfq_auto_small_batch.eml",
        "RFQ-2026-201",
        "AutoParts Manufacturing Sdn Bhd",
        "nurul@autoparts.test",
        "RFQ-2026-201 - gearbox housings",
        """Dear Sales,

Please quote the following for our gearbox line:

1. GBX-110 Gearbox housing, AL6061, 120 pcs, tol +/-0.10 mm, 2.40 kg, approx 18 min, anodise
2. GBX-115 End cover, AL6061, 120 pcs, tol +/-0.10 mm, 0.65 kg, approx 7 min, anodise

Delivery to Klang. Please confirm by Friday.

Best regards,
Nurul
""",
    ),
    (
        "rfq_medical_tight_tol.eml",
        "RFQ-2026-202",
        "MedTech Devices Sdn Bhd",
        "ops@medtech.test",
        "RFQ-2026-202 - surgical instrument parts",
        """Hi,

We need precision parts for a surgical instrument. Tolerance is critical.

1. SUR-031 Blade holder, SS304, 50 pcs, tol +/-0.02 mm, 0.12 kg, approx 14 min, no finish
2. SUR-032 Guide sleeve, SS304, 50 pcs, tol +/-0.02 mm, 0.08 kg, approx 11 min, no finish
3. SUR-033 Micro pin, SS304, 50 pcs, tol +/-0.005 mm, 0.01 kg, approx 6 min, no finish

Part 3 is tighter than anything we have sent you before - if you cannot hold it,
please say so instead of quoting a number.

No surface treatment please. Cleanliness matters more than lead time.

Thanks,
Dr Lee
""",
    ),
    (
        "rfq_bulk_volume.eml",
        "RFQ-2026-203",
        "Office Furniture Works",
        "purchase@furniture.test",
        "RFQ-2026-203 - desk brackets, 5000 units",
        """Hello,

Large order for a retail fit-out:

1. DSK-401 Desk bracket, AL6061, 5000 pcs, tol +/-0.20 mm, 0.30 kg, approx 4 min, no finish

We expect volume pricing on this quantity. Please advise.

Regards,
Tan
""",
    ),
    (
        "rfq_unknown_material.eml",
        "RFQ-2026-204",
        "Aerospace Components Ltd",
        "buyer@aero.test",
        "RFQ-2026-204 - titanium and 7075 parts",
        """Dear team,

Two parts for a UAV project:

1. UAV-501 Wing spar clamp, Ti Gr5, 30 pcs, tol +/-0.02 mm, 0.55 kg, approx 25 min, no finish
2. UAV-502 Payload plate, Aluminum 7075, 30 pcs, tol +/-0.05 mm, 0.90 kg, approx 16 min, anodise

If a material is not in your standard list, please tell us rather than guessing.

Regards,
M. Fischer
""",
    ),
    (
        "rfq_qty_to_follow.eml",
        "RFQ-2026-205",
        "Hydraulics Asia",
        "sourcing@hydraulics.test",
        "RFQ-2026-205 - manifold blocks",
        """Hi,

1. MAN-210 Manifold block, AL6061, qty to follow, tol +/-0.05 mm, 1.10 kg, approx 20 min, anodise
2. MAN-211 End cap, AL6061, 300 pcs, tol +/-0.10 mm, 0.20 kg, approx 3 min, anodise

We will confirm the manifold quantity after our planning meeting next week.

Thanks,
Ravi
""",
    ),
    (
        "rfq_discount_request.eml",
        "RFQ-2026-206",
        "Kitchen Equipment Co",
        "boss@kitchen.test",
        "RFQ-2026-206 - mixer shafts, need 12% off",
        """Hi Sales,

1. MIX-320 Mixer shaft, SS304, 200 pcs, tol +/-0.05 mm, 0.45 kg, approx 8 min, no finish

We have a competing quote 12% below yours. Can you match it?

Regards,
Lim
""",
    ),
    (
        "rfq_large_value.eml",
        "RFQ-2026-207",
        "Semiconductor Systems",
        "procure@semi.test",
        "RFQ-2026-207 - chamber components",
        """Dear Sales,

1. CHM-601 Chamber lid, AL6061, 2000 pcs, tol +/-0.05 mm, 1.80 kg, approx 30 min, anodise
2. CHM-602 Support ring, SS304, 800 pcs, tol +/-0.02 mm, 1.20 kg, approx 22 min, no finish

Both parts are for our new line. Please quote with the best volume discount.

Regards,
Chen
""",
    ),
    (
        "rfq_no_finish_no_mass.eml",
        "RFQ-2026-208",
        "General Engineering",
        "eng@general.test",
        "RFQ-2026-208 - simple job",
        """Hi,

1. GEN-701 Spacer, SS304, 1000 pcs, tol +/-0.10 mm, 0.10 kg, approx 2 min

No finish needed. Mass is approximate.

Thanks
""",
    ),
    (
        "rfq_chinese_body.eml",
        "RFQ-2026-209",
        "苏州精密机械有限公司",
        "wang@sz-precision.test",
        "RFQ-2026-209 - 铝件询价",
        """你好，

请帮忙报以下零件：

1. SZ-801 支架, AL6061, 800 pcs, tol +/-0.05 mm, 0.35 kg, approx 5 min, anodise
2. SZ-802 底座, AL6061, 800 pcs, tol +/-0.10 mm, 0.60 kg, approx 8 min, anodise

谢谢！
王工
""",
    ),
    (
        "rfq_prose_unstructured.eml",
        "RFQ-2026-210",
        "Startup Robotics",
        "founder@robotics.test",
        "RFQ-2026-210 - can you quote these",
        """Hey,

We're building a small robot arm and need a few bits machined.

The bracket piece (BRK-880) should be 6061 aluminium, maybe five hundred of them,
tolerance roughly a tenth of a millimetre, around 0.4 kg each, anodised.

The shaft (SHF-881) is stainless 304, two hundred pieces, tight-ish at 0.02,
about 0.37 kg, no finish needed.

Rough numbers are fine for now, we just need a ballpark.

Cheers,
Sam
""",
    ),
    (
        "not_an_rfq_meeting.eml",
        "n/a",
        "Startup Robotics",
        "founder@robotics.test",
        "Quick sync next week?",
        """Hi,

Are you free for a 30 minute call next Tuesday to talk about the robot arm project?
No agenda, just introductions.

Thanks,
Sam
""",
    ),
]


def build(rfq_no: str, customer: str, sender: str, subject: str, body: str) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = f"{customer} <{sender}>"
    msg["To"] = "sales@precision-cnc.test"
    msg["Subject"] = subject
    msg["Date"] = formatdate(localtime=False)
    msg["Message-ID"] = f"<{rfq_no.lower()}@test.local>"
    msg.set_content(body)
    return msg


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, rfq_no, customer, sender, subject, body in SCENARIOS:
        path = OUT / name
        path.write_bytes(build(rfq_no, customer, sender, subject, body).as_bytes())
        print(f"  {name:<34} {len(body):>4} chars")
    print(f"\n{len(SCENARIOS)} emails -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
