"""解析器公共部分：块构造函数、表头识别、按扩展名分发。

块类型（与库里的 stage_block.block_type 一一对应）：
    title      标题栏/抬头字段
    kv         键值对，如 "Order quantity: 800 pcs"
    table_row  表格的一行，整行以 dict 存入 row
    text       自由文本（段落、备注、说明行）
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ParseResult:
    """一次解析的结果。ok=False 表示文件读不了/格式不支持。"""

    blocks: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    ok: bool = True
    error: str = ""

    def add(self, block_type: str, locator: str, ordinal: int, **kw) -> None:
        block = {"block_type": block_type, "locator": locator, "ordinal": ordinal}
        block.update({k: v for k, v in kw.items() if v is not None})
        self.blocks.append(block)


# 表头里常见的列名，用来找"哪一行是表头"
HEADER_HINTS = {
    "part no", "partno", "part number", "part_no", "partno.", "item", "line",
    "qty", "quantity", "material", "tolerance", "mass", "weight", "cycle",
    "finish", "description", "drawing",
}

# 键值对行："Order quantity: 800 pcs" / "Part no - CVR-310"
KV_RE = re.compile(r"^\s*([A-Za-z][A-Za-z0-9 /#_().+-]{1,40}?)\s*[:：]\s*(.+?)\s*$")


def norm_cell(value) -> str:
    """单元格值转成干净字符串；Number 保留原样。"""
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value).strip()


def is_blank_row(values: list) -> bool:
    return all(norm_cell(v) == "" for v in values)


def looks_like_header(values: list) -> bool:
    """一行里命中 ≥3 个表头关键词，就当它是表头。"""
    hits = 0
    for v in values:
        text = norm_cell(v).lower().strip(" :")
        if not text:
            continue
        if text in HEADER_HINTS or any(h in text for h in ("part no", "tolerance", "material", "qty")):
            hits += 1
    return hits >= 3


def row_dict(headers: list, values: list) -> dict:
    """把一行数据按表头拼成 dict，空表头列忽略。"""
    row: dict = {}
    for i, value in enumerate(values):
        name = norm_cell(headers[i]) if i < len(headers) else f"col{i + 1}"
        if not name:
            continue
        text = norm_cell(value)
        if text == "":
            continue
        row[name] = value if isinstance(value, (int, float)) else text
    return row


def parse_kv_line(line: str) -> tuple[str, str] | None:
    match = KV_RE.match(line)
    if not match:
        return None
    key = match.group(1).strip()
    value = match.group(2).strip()
    if not value or len(key) > 40:
        return None
    return key, value


def dispatch(path: str | Path, mapper=None) -> ParseResult:
    """按扩展名选解析器。未支持的格式返回 ok=False，不抛异常。

    mapper: 可选的结构映射函数（仅 xlsx 用，表头认不出来时兜底）。
    """
    p = Path(path)
    suffix = p.suffix.lower()
    if suffix == ".xlsx":
        from .xlsx_parser import parse_xlsx

        return parse_xlsx(p, mapper=mapper)
    if suffix == ".pptx":
        from .pptx_parser import parse_pptx

        return parse_pptx(p)
    if suffix == ".docx":
        from .docx_parser import parse_docx

        return parse_docx(p)
    if suffix == ".pdf":
        from .pdf_parser import parse_pdf

        return parse_pdf(p)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        from .image_parser import parse_image

        return parse_image(p)
    return ParseResult(ok=False, error=f"unsupported_format: {suffix or 'unknown'}")
