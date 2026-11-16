"""用 Pillow 画架构图（不需要浏览器，也不引入新依赖）。

设计目标：一眼看清"哪些是确定性代码、哪些是模型、哪些是 AgentCore 托管服务"。
输出：docs/architecture.png（2x，适合直接贴进 README）
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SCALE = 2
W, H = 1240, 700

BG = "#f7f9fc"
INK = "#14212e"
MUTED = "#5b6b7c"
BORDER = "#dde5ee"
BLUE_BG = "#eaf2ff"
BLUE_BORDER = "#b9d4ff"
AMBER_BG = "#fdf1d8"
AMBER_BORDER = "#e0a83c"
AMBER_INK = "#9a6b00"
WHITE = "#ffffff"

FONT = "segoeui.ttf"
FONT_BOLD = "seguisb.ttf"


def font(size: int, bold: bool = False):
    return ImageFont.truetype(FONT_BOLD if bold else FONT, size * SCALE)


class Canvas:
    def __init__(self) -> None:
        self.image = Image.new("RGB", (W * SCALE, H * SCALE), BG)
        self.draw = ImageDraw.Draw(self.image)

    def box(self, x, y, w, h, fill=WHITE, border=BORDER, radius=12, width=1, dash=False):
        self.draw.rounded_rectangle(
            [x * SCALE, y * SCALE, (x + w) * SCALE, (y + h) * SCALE],
            radius=radius * SCALE, fill=fill, outline=border, width=width * SCALE,
        )

    def text(self, x, y, value, size=12, bold=False, color=INK):
        self.draw.text((x * SCALE, y * SCALE), value, font=font(size, bold), fill=color)

    def wrap(self, x, y, value, width, size=11, color=MUTED, line_height=None):
        line_height = line_height or size + 4
        words = value.split(" ")
        line = ""
        cursor = y
        for word in words:
            trial = f"{line} {word}".strip()
            if self.draw.textlength(trial, font=font(size)) <= width * SCALE:
                line = trial
            else:
                self.text(x, cursor, line, size=size, color=color)
                cursor += line_height
                line = word
        if line:
            self.text(x, cursor, line, size=size, color=color)
        return cursor + line_height

    def arrow(self, x1, y1, x2, y2, color="#8aa0b6", width=2):
        self.draw.line([x1 * SCALE, y1 * SCALE, x2 * SCALE, y2 * SCALE], fill=color, width=width * SCALE)
        head = 6
        if abs(x2 - x1) >= abs(y2 - y1):
            direction = 1 if x2 > x1 else -1
            self.draw.polygon(
                [(x2 * SCALE, y2 * SCALE),
                 ((x2 - head * direction) * SCALE, (y2 - head / 1.6) * SCALE),
                 ((x2 - head * direction) * SCALE, (y2 + head / 1.6) * SCALE)],
                fill=color,
            )
        else:
            direction = 1 if y2 > y1 else -1
            self.draw.polygon(
                [(x2 * SCALE, y2 * SCALE),
                 ((x2 - head / 1.6) * SCALE, (y2 - head * direction) * SCALE),
                 ((x2 + head / 1.6) * SCALE, (y2 - head * direction) * SCALE)],
                fill=color,
            )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.image.save(path, "PNG")


def card(c: Canvas, x, y, w, h, title, lines, fill=WHITE, border=BORDER, title_color=INK):
    c.box(x, y, w, h, fill=fill, border=border)
    c.text(x + 12, y + 10, title.upper(), size=11, bold=True, color=title_color)
    cursor = y + 30
    for line, mono in lines:
        cursor = c.wrap(x + 12, cursor, line, w - 24, size=11, color=MUTED)
    return y + h


def build() -> Path:
    c = Canvas()
    c.text(34, 28, "AI Quotation Agent — architecture", size=24, bold=True)
    c.text(34, 62, "Email in, priced quotation out. The model only reads text; every number is produced by code.",
           size=12, color=MUTED)

    top_y = 104
    height = 150
    boxes = [
        (34, 190, "1 · Sources", [
            ("Customer email .eml", False),
            ("Attachments: xlsx · pptx · docx · pdf · scans", False),
            ("tools/pull_mail.py polls IMAP → S3", True),
        ], WHITE, BORDER, INK),
        (256, 200, "2 · Runtime", [
            ("agent.py — orchestration only", False),
            ("no arithmetic, no pricing", True),
            ("Memory: received → priced → rendered", False),
        ], BLUE_BG, BLUE_BORDER, INK),
        (488, 168, "3 · Gateway", [
            ("MCP · AWS_IAM", False),
            ("14 tools, tools___<name>", True),
        ], WHITE, BORDER, INK),
        (688, 250, "4 · Lambda tools", [
            ("price_line · build_quote · quote_email", False),
            ("render_reply · render_quote_pdf · render_review_pdf", False),
            ("reprice_quote · submit_approval · list_approvals", False),
            ("stateless, deterministic", True),
        ], WHITE, BORDER, INK),
        (970, 236, "5 · Deliverables", [
            ("Quotation PDF", False),
            ("Review list PDF (flags + approval status)", False),
            ("Reply email draft", False),
            ("S3 + 1h presigned links", True),
        ], WHITE, BORDER, INK),
    ]

    for x, w, title, lines, fill, border, title_color in boxes:
        card(c, x, top_y, w, height, title, lines, fill=fill, border=border, title_color=title_color)

    c.arrow(224, top_y + height / 2, 256, top_y + height / 2)
    c.arrow(456, top_y + height / 2, 488, top_y + height / 2)
    c.arrow(656, top_y + height / 2, 688, top_y + height / 2)
    c.arrow(938, top_y + height / 2, 970, top_y + height / 2)

    # ---- pipeline ----
    pipe_y = top_y + height + 40
    c.text(34, pipe_y - 22, "PIPELINE (inside the tools)", size=11, bold=True, color=MUTED)

    steps = [
        ("1 ingest", "MIME → envelope\n+ attachments", WHITE, BORDER),
        ("2 parse", "xlsx · pptx · docx\npdf · scan (OCR)", WHITE, BORDER),
        ("3 extract", "body lines\n(model fallback)", AMBER_BG, AMBER_BORDER),
        ("4 interpret", "units · IT grades\ncolumn mapping", AMBER_BG, AMBER_BORDER),
        ("5 normalise", "aliases → CanonicalLine\n+ confidence", WHITE, BORDER),
        ("6 price", "mass·rate + cycle·rate\n+ finish + setup/qty", WHITE, BORDER),
        ("7 review", "holds · conflicts\n(model explains)", AMBER_BG, AMBER_BORDER),
        ("8 render", "PDF · review list\n· reply", WHITE, BORDER),
    ]

    step_w = 116
    gap = 20
    for index, (title, body, fill, border) in enumerate(steps):
        x = 34 + index * (step_w + gap)
        c.box(x, pipe_y, step_w, 96, fill=fill, border=border, radius=10)
        c.text(x + 9, pipe_y + 10, title, size=11, bold=True, color=AMBER_INK if fill == AMBER_BG else INK)
        cursor = pipe_y + 30
        for line in body.split("\n"):
            c.text(x + 9, cursor, line, size=9.5 if len(body) > 26 else 10, color=MUTED)
            cursor += 15
        if fill == AMBER_BG:
            c.text(x + 9, pipe_y + 78, "MODEL", size=9, bold=True, color=AMBER_INK)
        if index < len(steps) - 1:
            c.arrow(x + step_w + 3, pipe_y + 47, x + step_w + gap - 4, pipe_y + 47, width=1)

    # ---- model band ----
    band_y = pipe_y + 124
    c.box(34, band_y, 700, 150, fill=AMBER_BG, border=AMBER_BORDER, radius=12, width=2)
    c.text(48, band_y + 12, "THE MODEL DOES THREE THINGS — NOTHING ELSE", size=11, bold=True, color=AMBER_INK)
    model_lines = [
        "1  data extraction — prose body → structured rows; unrecognisable header → column→field map (cached)",
        "2  semantic interpretation — IT7, 0.004\", 620 g → one number, range-checked",
        "3  conflict explanation — which existing source to trust, in words; advisory only",
        "OCR is Rekognition, not a model: it reads pixels, it does not interpret.",
    ]
    cursor = band_y + 32
    for line in model_lines:
        cursor = c.wrap(48, cursor, "•  " + line, 660, size=10.5, color="#7a5a00")

    c.box(748, band_y, 458, 150, fill=WHITE, border=BORDER, radius=12)
    c.text(762, band_y + 12, "NEVER DONE BY THE MODEL", size=11, bold=True, color=INK)
    never = [
        "No price, discount, margin or total.",
        "No approval decision, no confidence score, no PDF content.",
        "Every model output is schema-validated; invalid output falls back",
        "to the rule result, and a line that cannot be priced is held,",
        "never guessed.",
    ]
    cursor = band_y + 34
    for line in never:
        cursor = c.wrap(762, cursor, line, 420, size=11, color=MUTED)

    # ---- legend ----
    legend_y = band_y + 172
    items = [("AgentCore managed service", "#d8e7ff", "#9dc0f5"),
             ("model involvement", "#f7dfae", AMBER_BORDER),
             ("deterministic code", "#ffffff", "#c3ceda")]
    x = 34
    for label, fill, border in items:
        c.draw.rounded_rectangle([x * SCALE, legend_y * SCALE, (x + 12) * SCALE, (legend_y + 12) * SCALE],
                                 radius=3 * SCALE, fill=fill, outline=border, width=SCALE)
        c.text(x + 20, legend_y - 2, label, size=11, color=MUTED)
        x += 20 + c.draw.textlength(label, font=font(11)) / SCALE + 26

    c.text(34, legend_y + 26,
           "Same RFQ through body only, attachments only, or both produces the same quote (tests/test_same_quote.py).",
           size=11, color=MUTED)
    c.text(34, legend_y + 44,
           "Scanned pages use Amazon Rekognition (Textract is denied by this account's SCP), then harvest fields by pattern.",
           size=11, color=MUTED)

    path = Path(r"D:\pythoncode\axrail-quotation-agent\docs\architecture.png")
    c.save(path)
    return path


if __name__ == "__main__":
    print(build())
