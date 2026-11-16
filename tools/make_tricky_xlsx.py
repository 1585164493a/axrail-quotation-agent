"""造一个"规则读不懂"的 Excel：表头在第 4 行、列名是客户黑话、带合并大标题。

用来证明 P1（结构映射）有必要：现有解析器找不到表头 → 整表退化成文本 → 报价为空。
"""

from pathlib import Path

import openpyxl

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "attachments"


def build() -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "QuoteSheet"

    ws["A1"] = "ACME PUMP CO., LTD"
    ws.merge_cells("A1:I1")
    ws["A2"] = "Quotation request - hydraulic block rev C"
    ws.merge_cells("A2:I2")
    ws["A3"] = "Prepared by: Lily Zhou     Date: 2026-11-15"

    headers = ["Item", "Desc.", "Matl", "Req'd", "Tol (mm)", "Wt.", "CYC", "Finish", "Note"]
    for col, name in enumerate(headers, start=1):
        ws.cell(row=4, column=col, value=name)

    rows = [
        (1, "Valve body DN10", "SUS304", 250, "+/-0.10", 0.62, 8, "none", ""),
        (2, "End cap DN10", "AL 6061-T6", 250, "+/-0.02", 0.18, 5, "anodised", ""),
        (3, "Spring seat", "AL 6061-T6", 1200, "+/-0.10", 0.09, 3, "anodised", "priority"),
        (4, "Lock nut", "SUS304", 1200, "+/-0.05", 0.06, 2, "none", ""),
    ]
    for r, row in enumerate(rows, start=5):
        for c, value in enumerate(row, start=1):
            ws.cell(row=r, column=c, value=value)

    for col, width in zip("ABCDEFGHI", [6, 22, 12, 9, 12, 8, 8, 11, 12]):
        ws.column_dimensions[col].width = width

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "part_list_vendor_template.xlsx"
    wb.save(path)
    return path


def build_no_header() -> Path:
    """没有表头、每行是"整句文字"的表格：验证文本收割（不依赖表头）。"""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Requests"
    ws["A1"] = "Request list (no header row - free text per line)"
    lines = [
        "1. VLV-2010 Valve body DN10, SS304, 250 pcs, tol +/-0.10 mm, 0.62 kg, 8 min, no finish",
        "2. VLV-2012 End cap DN10, AL6061, 250 pcs, tol +/-0.02 mm, 0.18 kg, 5 min, anodise",
    ]
    for row, line in enumerate(lines, start=3):
        ws.cell(row=row, column=1, value=line)
    ws.column_dimensions["A"].width = 110

    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "part_list_no_header.xlsx"
    wb.save(path)
    return path


if __name__ == "__main__":
    print(build())
    print(build_no_header())
