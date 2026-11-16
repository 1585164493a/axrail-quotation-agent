# Full walkthrough - Axrail sample RFQ-2026-118

Every stage, with the actual data this build produced from the customer's own files.

## The case

| Input file | Role |
|---|---|
| `rfq_email.txt` | the buyer's email body (5 parts, 6 weeks, asks for 15% off) |
| `part_list.xlsx` | part list, lines 1-3 only |
| `part_spec.pptx` | spec slide, lines 4-5 |
| `drawing_CVR-310_RevB.pdf` | drawing spec sheet, says 800 pcs |

The four together are one RFQ. Packed into a single `.eml` for this run,
the way it would arrive in a real mailbox.

## Stage 1 - ingest: `.eml` -> Envelope

```json
{
  "sender": "Alex Tan <buyer@example-customer.test>",
  "to": [
    "sales@example-cnc-shop.test"
  ],
  "subject": "RFQ-2026-118 - CNC parts, delivery in 6 weeks",
  "sent_at": "2026-11-02T09:14:00+08:00",
  "rfq_ids": [
    "RFQ-2026-118"
  ],
  "customer": "Example Customer Sdn Bhd",
  "attachments": [
    {
      "filename": "part_list.xlsx",
      "size": 5470,
      "sha256": "b6faf82c40fa",
      "path": "D:\\pythoncode\\axrail-quotation-agent\\.testtmp\\walkthrough\\artifacts\\22d46c89e9ec__part_list.xlsx"
    },
    {
      "filename": "part_spec.pptx",
      "size": 28922,
      "sha256": "668a291a037d",
      "path": "D:\\pythoncode\\axrail-quotation-agent\\.testtmp\\walkthrough\\artifacts\\22d46c89e9ec__part_spec.pptx"
    },
    {
      "filename": "drawing_CVR-310_RevB.pdf",
      "size": 2423,
      "sha256": "22f923a94942",
      "path": "D:\\pythoncode\\axrail-quotation-agent\\.testtmp\\walkthrough\\artifacts\\22d46c89e9ec__drawing_CVR-310_RevB.pdf"
    }
  ]
}
```

## Stage 2 - parse: email body + attachments -> blocks

29 blocks. The body's own part lines become blocks too, so the quote
works whether the customer sends the list inline or as attachments. Each block
carries a `locator`, which is what makes the price traceable later.

| file | block | locator | content |
|---|---|---|---|
| email body | table_row | `body line 6` | {"Part no": "BRK-100", "Description": "Mounting bracket", "Material": "AL6061", "Qty": "5… |
| email body | table_row | `body line 7` | {"Part no": "SHF-220", "Description": "Drive shaft D20x150", "Material": "SS304", "Qty": … |
| email body | table_row | `body line 8` | {"Part no": "CVR-310", "Description": "Pump cover", "Material": "AL6061", "Qty": "1,000",… |
| email body | table_row | `body line 9` | {"Part no": "SPC-050", "Description": "Spacer", "Material": "SS304", "Tolerance (mm)": "0… |
| email body | table_row | `body line 10` | {"Part no": "HSG-400", "Description": "Valve housing", "Material": "Ti Gr5", "Qty": "50",… |
| part_list.xlsx | title | `Part list!A1` | RFQ-2026-118 Part list - Example Customer Sdn Bhd |
| part_list.xlsx | text | `Part list!A2` | SAMPLE DATA - fictional, for a candidate test only |
| part_list.xlsx | kv | `Part list!A4` | Line \| Part no \| Description \| Material \| Qty \| Tolerance (mm) \| Mass (kg) \| Cycle… |
| part_list.xlsx | table_row | `Part list!A5` | {"Line": 1, "Part no": "BRK-100", "Description": "Mounting bracket", "Material": "AL6061"… |
| part_list.xlsx | table_row | `Part list!A6` | {"Line": 2, "Part no": "SHF-220", "Description": "Drive shaft Ø20x150", "Material": "SS30… |
| part_list.xlsx | table_row | `Part list!A7` | {"Line": 3, "Part no": "CVR-310", "Description": "Pump cover", "Material": "AL6061", "Qty… |
| part_list.xlsx | text | `Part list!A9` | Lines 4-5: see the part-spec slides. |
| part_spec.pptx | title | `slide 1 title` | RFQ-2026-118: additional parts (spec) |
| part_spec.pptx | kv | `slide 1 table2 header` | Line \| Part no \| Description \| Material \| Qty \| Tolerance (mm) \| Mass (kg) \| Cycle… |
| part_spec.pptx | table_row | `slide 1 table2 row2` | {"Line": "4", "Part no": "SPC-050", "Description": "Spacer", "Material": "SS304", "Qty": … |
| part_spec.pptx | table_row | `slide 1 table2 row3` | {"Line": "5", "Part no": "HSG-400", "Description": "Valve housing", "Material": "Ti Gr5",… |
| part_spec.pptx | text | `slide 1 shape3 L1` | Notes: spacer quantity to be confirmed. Valve housing is a new design; please review the … |
| part_spec.pptx | text | `slide 1 shape3 L2` | SAMPLE DATA - fictional, for a candidate test only |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L3` | Field \| Value |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L5` | CVR-310 |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L7` | Pump cover |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L9` | B |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L11` | AL6061 |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L13` | 800 pcs |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L15` | ±0.05 mm |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L17` | 0.85 kg |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L19` | Clear anodise |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L21` | RFQ-2026-118 |
| drawing_CVR-310_RevB.pdf | kv | `page 1 L23` | dimensions per drawing CVR-310 Rev B. Break all sharp edges. |

## Stage 3 - normalise: blocks -> CanonicalRFQ

Five parts, merged across three files, with the sources kept:

| part | material | qty | tol (mm) | mass | cycle | finish | refs |
|---|---|---|---|---|---|---|---|
| BRK-100 | AL6061 | 500 | 0.1 | 0.4 | 6.0 | anodise | email body @ body line 6<br>part_list.xlsx @ Part list!A5 |
| SHF-220 | SS304 | 200 | 0.02 | 0.37 | 9.0 | none | email body @ body line 7<br>part_list.xlsx @ Part list!A6 |
| CVR-310 | AL6061 | 1000 | 0.05 | 0.85 | 12.0 | anodise | email body @ body line 8<br>part_list.xlsx @ Part list!A7<br>drawing_CVR-310_RevB.pdf @ page 1 L7<br>drawing_CVR-310_RevB.pdf @ page 1 L11<br>drawing_CVR-310_RevB.pdf @ page 1 L13<br>drawing_CVR-310_RevB.pdf @ page 1 L15<br>drawing_CVR-310_RevB.pdf @ page 1 L17<br>drawing_CVR-310_RevB.pdf @ page 1 L19 |
| SPC-050 | SS304 | TBC | 0.1 | 0.05 | 2.0 | none | email body @ body line 9<br>part_spec.pptx @ slide 1 table2 row2 |
| HSG-400 | Ti Gr5 | 50 | 0.005 | 1.2 | 40.0 | none | email body @ body line 10<br>part_spec.pptx @ slide 1 table2 row3 |

**Conflicts detected (not resolved):**

- `CVR-310.qty`: 1000 (email body @ body line 8); 1000 (part_list.xlsx @ Part list!A7); 800 (drawing_CVR-310_RevB.pdf @ page 1 L13)

## Stage 4 - price: CanonicalRFQ -> quote lines

| part | qty | unit cost | list price | discount | unit price | line total |
|---|---|---|---|---|---|---|
| BRK-100 | 500 | 21.20 | 28.27 | 5% | 26.86 | 13,430.00 |
| SHF-220 | 200 | 40.89 | 54.52 | 0% | 54.52 | 10,904.00 |
| CVR-310 | 1000 | 41.05 | 54.73 | 8% | 50.35 | 50,350.00 |
| **total** | | | | | | **74,684.00** |

**Held (not priced, with the reason):**

| part | reason | detail |
|---|---|---|
| SPC-050 | `hold_no_qty` | Order quantity is not confirmed (TBC), so setup cost cannot be spread. |
| HSG-400 | `hold_no_material` | Material Ti Gr5 has no standard price in the price list. |

**Trace for BRK-100** - every number names its rule and its source:

```
M-AL6061: 0.4 kg × 18.00 = 7.20  [email body @ body line 6]
R-3AXIS: 6.0 min × 2.00 (CNC 3-axis, tol ±0.1) = 12.00  [email body @ body line 6]
F-ANODISE: anodise = 1.50  [email body @ body line 6]
S-LINE: 250.00 / 500 pcs = 0.50
COST: sum of the four components = 21.20
P-MARGIN: 21.20 ÷ (1 − 25%) = 28.27
D-QTY-5: 28.27 × (1 − 5%) (500 pcs tier) = 26.86
TOTAL: 26.86 × 500 pcs = 13430.00
```

**Approval:** Needs sales manager sign-off: Quotation total 74,684.00 MYR exceeds the 50,000 MYR threshold; 2 line(s) cannot be priced yet (engineering / procurement); Customer requested 15% discount, above the 8% policy limit; 1 source conflict(s) (e.g. quantity or material disagree between documents)

## Stage 5 - render: three artefacts

| artefact | content |
|---|---|
| `Q-RFQ-2026-118-<date>.pdf` | quote no., customer, dates, line table, total, assumptions, held lines |
| `reply-email.txt` | English draft to the buyer |
| `review-list.md` | conflicts, holds, approval, full rule trace |

Reply draft (verbatim):

```text
Subject: Quotation Q-RFQ-2026-118-20261114 - RFQ-2026-118

Dear Example team,

Thank you for your enquiry RFQ-2026-118. Please find our quotation Q-RFQ-2026-118-20261114 attached.

Quoted lines:
  - BRK-100 (Mounting bracket, AL6061), 500 pcs at MYR 26.86 per piece (5% volume discount), line total MYR 13,430.00
  - SHF-220 (Drive shaft D20x150, SS304), 200 pcs at MYR 54.52 per piece (0% volume discount), line total MYR 10,904.00
  - CVR-310 (Pump cover, AL6061), 1000 pcs at MYR 50.35 per piece (8% volume discount), line total MYR 50,350.00

Total: MYR 74,684.00. The quotation is valid for 30 days.

We could not quote the following items yet:
  - SPC-050: the order quantity is still to be confirmed. Please advise the quantity and we will price it immediately.
  - HSG-400: Ti Gr5 is not on our standard price list. We are obtaining a material quotation and will revert.

One point to confirm: for CVR-310 the RFQ lists 1000 pcs while the drawing shows 800 pcs. We have quoted CVR-310 at the RFQ quantity; please confirm which figure to use and we will adjust if needed.

Regarding the requested 15% new-customer discount: our volume discount is already included in the prices above. Anything beyond that needs approval from our sales manager, so we will come back to you separately.

Please let us know if you need any clarification.

Best regards,
Sales team
Precision CNC machining
```

