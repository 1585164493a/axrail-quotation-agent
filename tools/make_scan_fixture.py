"""生成"扫描件"样本：没有文字层的 PDF + 一张 PNG，用来验证 OCR。

PIL 保存的 PDF 里只有一张图，没有文字层 —— 正好模拟客户传真的扫描件。
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "attachments"

LINES = [
    "PURCHASE REQUEST - SCAN",
    "1. SCN-100 Bracket, AL6061, 400 pcs, tol +/-0.10 mm, 0.35 kg, approx 5 min, anodise",
    "2. SCN-200 Shaft, SS304, 150 pcs, tol +/-0.02 mm, 0.50 kg, approx 7 min, no finish",
]


def build() -> tuple[Path, Path]:
    image = Image.new("RGB", (1200, 500), "white")
    draw = ImageDraw.Draw(image)
    y = 60
    for line in LINES:
        draw.text((40, y), line, fill="black")
        y += 90

    OUT.mkdir(parents=True, exist_ok=True)
    png = OUT / "scan_plate.png"
    image.save(png)

    pdf = OUT / "scan_plate.pdf"
    image.save(pdf, "PDF", resolution=150)
    return pdf, png


def build_mixed() -> Path:
    """混合 PDF：第 1 页有文字层，第 2 页是扫描图（验证逐页判断 OCR）。"""
    from pypdf import PdfReader, PdfWriter

    from quotation_agent.quote.pdf import PdfDoc

    text_pdf = OUT / "_text_page.pdf"
    doc = PdfDoc()
    doc.text(60, 760, "PURCHASE REQUEST - PAGE 1 (text layer)", 12)
    doc.text(60, 730, "This page was typed, not scanned.", 10)
    doc.save(text_pdf)

    image_pdf = OUT / "_image_page.pdf"
    image = Image.new("RGB", (1000, 300), "white")
    draw = ImageDraw.Draw(image)
    draw.text((30, 60), "1. MIX-500 Cover, AL6061, 600 pcs, tol +/-0.10 mm, 0.40 kg, 4 min, anodise",
              fill="black")
    image.save(image_pdf, "PDF", resolution=150)

    writer = PdfWriter()
    for path in (text_pdf, image_pdf):
        reader = PdfReader(str(path))
        for page in reader.pages:
            writer.add_page(page)

    mixed = OUT / "mixed_text_and_scan.pdf"
    with mixed.open("wb") as handle:
        writer.write(handle)
    text_pdf.unlink(missing_ok=True)
    image_pdf.unlink(missing_ok=True)
    return mixed


if __name__ == "__main__":
    pdf, png = build()
    mixed = build_mixed()
    print(pdf, png, mixed)
