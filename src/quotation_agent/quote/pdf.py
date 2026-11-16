"""极简 PDF 生成器（零依赖）。

只做报价单需要的事：定宽字体、画线、写文字、自动换行。
不引第三方库的原因：AgentCore 容器里少一个依赖、少一份许可证风险，
而且报价单版式是固定的，用不着 LaTeX/HTML 渲染管线。
"""

from __future__ import annotations

from pathlib import Path

PAGE_W, PAGE_H = 595, 842  # A4，单位 pt
MARGIN = 48


def _esc(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


class PdfDoc:
    """按"从上往下"的顺序往页面上写字。"""

    def __init__(self) -> None:
        self.ops: list[str] = []
        self.y = PAGE_H - MARGIN

    # ---------- 绘图原语 ----------

    def text(self, x: float, y: float, text: str, size: int = 10, bold: bool = False) -> None:
        font = "F2" if bold else "F1"
        self.ops.append(f"BT /{font} {size} Tf 1 0 0 1 {x:.2f} {y:.2f} Tm ({_esc(text)}) Tj ET")

    def text_right(self, x_right: float, y: float, text: str, size: int = 10, bold: bool = False) -> None:
        # Helvetica 平均字宽约 0.5em，右对齐只需要粗算
        width = len(text) * size * 0.5
        self.text(x_right - width, y, text, size, bold)

    def line(self, x1: float, y1: float, x2: float, y2: float, width: float = 0.6) -> None:
        self.ops.append(f"{width} w {x1:.2f} {y1:.2f} m {x2:.2f} {y2:.2f} l S")

    def rect(self, x: float, y: float, w: float, h: float, gray: float = 0.92) -> None:
        self.ops.append(f"{gray} g {x:.2f} {y:.2f} {w:.2f} {h:.2f} re f 0 g")

    # ---------- 排版辅助 ----------

    def write(self, text: str, size: int = 10, bold: bool = False, indent: float = 0.0, gap: float = 16) -> None:
        self.text(MARGIN + indent, self.y, text, size, bold)
        self.y -= gap

    def wrap(self, text: str, width_chars: int) -> list[str]:
        words, lines, current = text.split(), [], ""
        for word in words:
            candidate = f"{current} {word}".strip()
            if len(candidate) <= width_chars:
                current = candidate
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    def paragraph(self, text: str, size: int = 9, indent: float = 0.0, gap: float = 12) -> None:
        for piece in self.wrap(text, int((PAGE_W - 2 * MARGIN - indent) / (size * 0.5))):
            self.text(MARGIN + indent, self.y, piece, size)
            self.y -= gap


    def save(self, path: str | Path) -> Path:
        stream = "\n".join(self.ops).encode("latin-1", "replace")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            (
                b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 "
                + f"{PAGE_W} {PAGE_H}".encode()
                + b"] /Resources << /Font << /F1 5 0 R /F2 6 0 R >> >> /Contents 4 0 R >>"
            ),
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>",
        ]

        out = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for i, body in enumerate(objects, start=1):
            offsets.append(len(out))
            out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"

        xref_at = len(out)
        out += f"xref\n0 {len(objects) + 1}\n".encode() + b"0000000000 65535 f \n"
        for off in offsets[1:]:
            out += f"{off:010d} 00000 n \n".encode()
        out += (
            b"trailer\n<< /Size " + str(len(objects) + 1).encode()
            + b" /Root 1 0 R >>\nstartxref\n" + str(xref_at).encode() + b"\n%%EOF\n"
        )

        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(bytes(out))
        return target
