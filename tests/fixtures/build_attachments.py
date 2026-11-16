"""生成附件测试素材（xlsx / pptx / docx / pdf + 损坏文件）。

这些文件是**确定性**生成的，生成后直接提交进仓库；
测试只读它们，不再依赖脚本。

用法：
    python tests/fixtures/build_attachments.py
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font
from pptx import Presentation
from pptx.util import Inches, Pt

HERE = Path(__file__).resolve().parent / "attachments"

HEADERS = ["Line", "Part no", "Description", "Material", "Qty", "Tolerance (mm)", "Mass (kg)", "Cycle (min)", "Finish"]

FULL_ROWS = [
    [1, "BRK-100", "Mounting bracket", "AL6061", 500, "±0.10", 0.40, 6, "Anodise"],
    [2, "SHF-220", "Drive shaft Ø20x150", "SS304", 200, "±0.02", 0.37, 9, "None"],
    [3, "CVR-310", "Pump cover", "AL6061", 1000, "±0.05", 0.85, 12, "Anodise"],
    [4, "SPC-050", "Spacer", "SS304", "TBC", "±0.10", 0.05, 2, "None"],
    [5, "HSG-400", "Valve housing", "Ti Gr5", 50, "±0.005", 1.20, 40, "None"],
]


# ---------------------------------------------------------------- xlsx

def xlsx_full(path: Path) -> None:
    """5 行齐全的标准零件清单。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Part list"
    ws.append(["RFQ-2026-118 Part list - Example Customer Sdn Bhd"])
    ws.append(["SAMPLE DATA - fictional, for a candidate test only"])
    ws.append([])
    ws.append(HEADERS)
    for row in FULL_ROWS:
        ws.append(row)
    for c in ws[4]:
        c.font = Font(bold=True)
    wb.save(path)


def xlsx_partial(path: Path) -> None:
    """只有 1–3 行，第 4–5 行指向幻灯片（题目原样例的形态）。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Part list"
    ws.append(["RFQ-2026-118 Part list - Example Customer Sdn Bhd"])
    ws.append(["SAMPLE DATA - fictional, for a candidate test only"])
    ws.append([])
    ws.append(HEADERS)
    for row in FULL_ROWS[:3]:
        ws.append(row)
    ws.append([])
    ws.append(["Lines 4-5: see the part-spec slides."])
    wb.save(path)


def xlsx_messy(path: Path) -> None:
    """故意做脏：合并标题、表头在上方第 3 行、数量带千分位与单位、公差带单位、空行、多余列。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Sheet1"
    ws.merge_cells("A1:K1")
    ws["A1"] = "PURCHASE ENQUIRY  RFQ-2026-118"
    ws["A1"].font = Font(size=14, bold=True)
    ws["A1"].alignment = Alignment(horizontal="center")
    ws["A2"] = "Buyer: Alex Tan  |  Example Customer Sdn Bhd  |  Shah Alam plant"
    ws.append([])  # 第 3 行留空
    ws.append(HEADERS + ["Remark", "Currency"])
    ws.append([1, "BRK-100", "Mounting bracket", "AL6061", "500 pcs", "±0.10 mm", 0.40, "6 min", "Anodise", "", "MYR"])
    ws.append([2, "SHF-220", "Drive shaft D20x150", "SS304", "200 pcs", "±0.02 mm", 0.37, "9 min", "None", "", "MYR"])
    ws.append([3, "CVR-310", "Pump cover", "AL6061", "1,000 pcs", "±0.05 mm", 0.85, "12 min", "Anodise", "qty check with drawing", "MYR"])
    ws.append([])
    ws.append([4, "SPC-050", "Spacer", "SS304", "TBC", "±0.10 mm", 0.05, "2 min", "None", "qty to follow", "MYR"])
    ws.append([5, "HSG-400", "Valve housing", "Ti Gr5", 50, "±0.005 mm", 1.20, "40 min", "None", "new design, review tol", "MYR"])
    ws.append([])
    ws.append(["Notes: delivery in 6 weeks; 15% new-customer discount requested."])
    wb.save(path)


def xlsx_empty(path: Path) -> None:
    """只有表头，一行数据都没有。"""
    wb = Workbook()
    ws = wb.active
    ws.title = "Part list"
    ws.append(HEADERS)
    wb.save(path)


# ---------------------------------------------------------------- pptx

def pptx_pair(path: Path) -> None:
    """两行（第 4–5 行），对应题目里的规格幻灯片。"""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "RFQ-2026-118: additional parts (spec)"
    rows, cols = 3, len(HEADERS)
    table = slide.shapes.add_table(rows, cols, Inches(0.4), Inches(1.6), Inches(9), Inches(1.2)).table
    for i, h in enumerate(HEADERS):
        table.cell(0, i).text = h
    for i, row in enumerate(FULL_ROWS[3:], start=1):
        for j, val in enumerate(row):
            table.cell(i, j).text = str(val)
    prs.save(path)


def pptx_notes(path: Path) -> None:
    """只有一行数据，但把关键信息写在**备注**里——真实演示文稿常见这种藏法。"""
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[5])
    slide.shapes.title.text = "HSG-400 valve housing (new design)"
    rows, cols = 2, 5
    table = slide.shapes.add_table(rows, cols, Inches(0.6), Inches(1.8), Inches(8), Inches(1.0)).table
    for i, h in enumerate(["Part no", "Material", "Qty", "Tolerance (mm)", "Finish"]):
        table.cell(0, i).text = h
    for i, val in enumerate(["HSG-400", "Ti Gr5", "50", "±0.005", "None"]):
        table.cell(1, i).text = val
    notes = slide.notes_slide.notes_text_frame
    notes.text = "Please review the tolerance: ±0.005 mm is tighter than our usual work. Finish: none. Mass 1.2 kg, cycle 40 min."
    prs.save(path)


# ---------------------------------------------------------------- docx

def docx_table(path: Path) -> None:
    """Word 表格（题目没给 Word 样例，但客户会发）。"""
    doc = Document()
    doc.add_heading("RFQ-2026-118 — Part specification (Word)", level=1)
    doc.add_paragraph("Example Customer Sdn Bhd · Shah Alam plant · delivery in 6 weeks")
    table = doc.add_table(rows=1, cols=len(HEADERS))
    table.style = "Table Grid"
    for i, h in enumerate(HEADERS):
        table.rows[0].cells[i].text = h
    for row in FULL_ROWS[:2]:
        cells = table.add_row().cells
        for i, val in enumerate(row):
            cells[i].text = str(val)
    doc.add_paragraph("Lines 3-5 are in the Excel part list. Tolerance values are general unless stated.")
    doc.save(path)


# ---------------------------------------------------------------- pdf（手写，零依赖）

def _pdf(path: Path, lines: list[str] | None) -> None:
    """写一个单页 PDF；lines=None 表示页面上没有任何文字（模拟扫描件/纯图形）。"""
    objs: list[bytes] = []

    def add(body: bytes) -> int:
        objs.append(body)
        return len(objs)  # 对象号从 1 开始

    if lines:
        escaped = []
        for ln in lines:
            safe = ln.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")
            escaped.append(f"({safe}) Tj T*")
        stream = ("BT /F1 11 Tf 14 TL 56 780 Td\n" + "\n".join(escaped) + "\nET").encode("latin-1", "replace")
    else:
        stream = b"q 1 0 0 1 0 0 cm Q"  # 什么都不画

    contents_id = add(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    font_id = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    page_id = add(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
        b"/Resources << /Font << /F1 " + str(font_id).encode() + b" 0 R >> >> "
        b"/Contents " + str(contents_id).encode() + b" 0 R >>"
    )
    pages_id = add(b"<< /Type /Pages /Kids [" + str(page_id).encode() + b" 0 R] /Count 1 >>")
    catalog_id = add(b"<< /Type /Catalog /Pages " + str(pages_id).encode() + b" 0 R >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

    xref_at = len(out)
    out += f"xref\n0 {len(objs) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += (
        b"trailer\n<< /Size " + str(len(objs) + 1).encode() + b" /Root " + str(catalog_id).encode()
        + b" 0 R >>\nstartxref\n" + str(xref_at).encode() + b"\n%%EOF\n"
    )
    path.write_bytes(bytes(out))


def pdf_text(path: Path) -> None:
    _pdf(path, [
        "Example Customer Sdn Bhd - Drawing spec sheet",
        "SAMPLE DATA - fictional, for a candidate test only",
        "Part no: CVR-310      Drawing rev: B",
        "Description: Pump cover",
        "Material: AL6061",
        "Order quantity: 800 pcs",
        "General tolerance: ±0.05 mm",
        "Mass (approx.): 0.85 kg",
        "Finish: Clear anodise",
        "Customer RFQ: RFQ-2026-118",
        "Notes: dimensions per drawing CVR-310 Rev B. Break all sharp edges.",
    ])


def pdf_no_text(path: Path) -> None:
    """没有文字层：解析器应当报 needs_ocr，而不是返回空表当没事。"""
    _pdf(path, None)


# ---------------------------------------------------------------- 坏文件

def broken_xlsx(path: Path) -> None:
    path.write_bytes(b"this is not a real xlsx file\n" * 20)


BUILDERS = [
    ("part_list_full.xlsx", xlsx_full),
    ("part_list_partial.xlsx", xlsx_partial),
    ("part_list_messy.xlsx", xlsx_messy),
    ("part_list_empty.xlsx", xlsx_empty),
    ("part_spec_pair.pptx", pptx_pair),
    ("part_spec_notes.pptx", pptx_notes),
    ("spec_table.docx", docx_table),
    ("drawing_text.pdf", pdf_text),
    ("drawing_no_text.pdf", pdf_no_text),
    ("broken.xlsx", broken_xlsx),
]


def main() -> None:
    HERE.mkdir(parents=True, exist_ok=True)
    print(f"writing attachments to {HERE}")
    for name, builder in BUILDERS:
        builder(HERE / name)
        size = (HERE / name).stat().st_size
        print(f"  {name:<26} {size:>7} B")


if __name__ == "__main__":
    main()
