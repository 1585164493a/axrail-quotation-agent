"""把数据库结构导出成 Excel（数据字典）。

数据来源是库里的 `schema_meta` 表，所以文档永远和实际表结构一致。
表清单、枚举值、索引这些解释性内容写在下方的常量里，改表时一起改。

用法：
    python tools/export_schema_xlsx.py [输出.xlsx]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "email_extract.db"

HEADER_FILL = PatternFill("solid", fgColor="1F3864")
HEADER_FONT = Font(bold=True, color="FFFFFF", size=11)
CAT_FILL = PatternFill("solid", fgColor="DEEAF6")
WARN_FILL = PatternFill("solid", fgColor="FFF2CC")
THIN = Side(style="thin", color="BFBFBF")
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)
WRAP = Alignment(wrap_text=True, vertical="top")

# 表名, 中文名, 用途, 关键约束
TABLES = [
    ("blob_store", "内容存储", "原始字节按 sha256 寻址；≤1 MiB 内联进库，更大的落文件、库里只留路径。",
     "sha256 主键，同内容只存一份"),
    ("raw_email", "原始邮件", "每封邮件一行（按内容哈希幂等：重复导入不新增），带信封字段与 blob 指针。",
     "blob_sha256 唯一"),
    ("raw_attachment", "原始附件", "附件是邮件的子资源，显式记录所属邮件（血缘）。",
     "raw_email_id 外键；同邮件内文件名唯一"),
    ("parse_run", "运行记录", "每次解析一条：解析哪份原件、哪个解析器版本、成功还是失败。",
     "run_uuid 唯一"),
    ("stage_email", "邮件解析结果（stage）", "从原件解析出的头部、正文、RFQ 号与客户识别结果。可重建。",
     "raw_email_id + run_id 唯一"),
    ("stage_attachment", "附件解析结果（stage）", "附件元数据与解析状态，同时指回 raw 附件。",
     "stage_email_id + filename 唯一"),
    ("stage_block", "抽取块（stage）", "抽出来的最小单位：文本、表格行、键值对、标题栏字段，每块带出处。",
     "必须带 block_type 与 locator"),
    ("mart_rfq", "询价单（mart）", "归一化后的业务模型，由第三步生成，可随时按 stage 重建。",
     "payload_json 存 CanonicalRFQ"),
    ("schema_meta", "数据字典", "逐字段说明，并标注所属层（blob/raw/run/stage/mart/meta）。",
     "table_name + column_name 主键"),
    ("db_meta", "库元信息", "schema 版本、架构说明、应用名。", "key 主键"),
]

# 字段, 取值, 含义
ENUMS = [
    ("blob_store.storage", "inline", "字节存在库内（≤1 MiB）"),
    ("blob_store.storage", "file", "字节落盘，库里只留 file_path"),
    ("parse_run.status", "running", "正在执行"),
    ("parse_run.status", "ok", "执行成功"),
    ("parse_run.status", "failed", "执行失败，原因写 note"),
    ("stage_attachment.status", "pending", "已落盘，尚未解析"),
    ("stage_attachment.status", "ok", "解析成功"),
    ("stage_attachment.status", "failed", "解析失败，原因写 error"),
    ("stage_attachment.status", "skipped", "按规则跳过（超大 / 不支持类型）"),
    ("stage_email.customer_level", "high", "证据累计 ≥0.45，可自动往下走"),
    ("stage_email.customer_level", "medium", "只有弱证据（0.20–0.45），可用但记入假设"),
    ("stage_email.customer_level", "needs_review", "证据互相矛盾，或单一弱证据 → 交人"),
    ("stage_email.customer_level", "draft", "无公司线索 → 建待确认草稿，不猜"),
    ("stage_block.block_type", "title", "标题栏/抬头字段（图纸、报价单顶部）"),
    ("stage_block.block_type", "kv", "键值对，如 Part no: CVR-310"),
    ("stage_block.block_type", "table_row", "表格的一行，整行存 row_json"),
    ("stage_block.block_type", "text", "自由文本块"),
]

# 索引名, 表, 字段, 作用
INDEXES = [
    ("idx_raw_att_email", "raw_attachment", "raw_email_id", "取某封邮件的原始附件"),
    ("idx_run_email", "parse_run", "raw_email_id", "查某封邮件被解析过几次"),
    ("idx_stage_email_raw", "stage_email", "raw_email_id", "从原件找回解析结果"),
    ("idx_stage_email_to", "stage_email", "sender_email", "按客户邮箱查历史询价"),
    ("idx_stage_att_email", "stage_attachment", "stage_email_id", "取某封邮件的附件"),
    ("idx_block_email", "stage_block", "stage_email_id", "取某封邮件的全部抽取块"),
    ("idx_block_attach", "stage_block", "stage_attachment_id", "取某附件的全部抽取块"),
]


def style_header(ws, ncols: int) -> None:
    for c in range(1, ncols + 1):
        cell = ws.cell(row=1, column=c)
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center", horizontal="center")
        cell.border = BORDER
    ws.freeze_panes = "A2"
    ws.row_dimensions[1].height = 28


def fill_body(ws, ncols: int, first_col_fill: bool = True) -> None:
    for r in range(2, ws.max_row + 1):
        for c in range(1, ncols + 1):
            cell = ws.cell(row=r, column=c)
            cell.alignment = WRAP
            cell.border = BORDER
        if first_col_fill:
            ws.cell(row=r, column=1).fill = CAT_FILL


def set_widths(ws, widths: list[int]) -> None:
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else ROOT / "docs" / "schema.xlsx"
    db = Path(argv[2]) if len(argv) > 2 else DEFAULT_DB

    if not db.exists():
        print(f"数据库不存在：{db}（先跑 python tools/init_db.py）")
        return 1

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    version = conn.execute("SELECT value FROM db_meta WHERE key='schema_version'").fetchone()
    version = version["value"] if version else "—"

    wb = Workbook()

    # ---- Sheet 1：表清单 ----
    ws = wb.active
    ws.title = "表清单"
    ws.append(["表名", "中文名", "用途", "关键约束", "当前行数"])
    for name, cn, purpose, constraint in TABLES:
        count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
        ws.append([name, cn, purpose, constraint, count])
    set_widths(ws, [18, 12, 60, 30, 10])
    style_header(ws, 5)
    fill_body(ws, 5)
    ws.auto_filter.ref = f"A1:E{ws.max_row}"

    # ---- Sheet 2：字段字典 ----
    ws2 = wb.create_sheet("字段字典")
    ws2.append(["表名", "字段", "类型", "含义", "来源（值从哪来）", "版本"])
    for row in conn.execute("SELECT * FROM schema_meta ORDER BY rowid"):
        ws2.append([
            row["table_name"], row["column_name"], row["data_type"],
            row["description"], row["source"], row["version"],
        ])
    set_widths(ws2, [16, 20, 9, 46, 56, 8])
    style_header(ws2, 6)
    fill_body(ws2, 6)
    ws2.auto_filter.ref = f"A1:F{ws2.max_row}"
    for r in range(2, ws2.max_row + 1):
        ws2.cell(row=r, column=5).fill = WARN_FILL

    # ---- Sheet 3：枚举值 ----
    ws3 = wb.create_sheet("枚举值")
    ws3.append(["字段", "取值", "含义"])
    for row in ENUMS:
        ws3.append(list(row))
    set_widths(ws3, [30, 16, 66])
    style_header(ws3, 3)
    fill_body(ws3, 3)
    ws3.auto_filter.ref = f"A1:C{ws3.max_row}"

    # ---- Sheet 4：索引 ----
    ws4 = wb.create_sheet("索引")
    ws4.append(["索引名", "表", "字段", "作用"])
    for row in INDEXES:
        ws4.append(list(row))
    set_widths(ws4, [22, 18, 18, 44])
    style_header(ws4, 4)
    fill_body(ws4, 4)

    # ---- Sheet 5：说明 ----
    ws5 = wb.create_sheet("说明")
    ws5.append(["项", "内容"])
    ws5.append(["schema 版本", version])
    ws5.append(["数据库文件", str(db)])
    ws5.append(["生成方式", "python tools/export_schema_xlsx.py docs/schema.xlsx"])
    ws5.append(["数据来源", "库内 schema_meta 表（文档与表结构一致）"])
    ws5.append(["改表须知", "先改 store/db.py 的 DDL 与 SCHEMA_META，再跑 init_db.py，最后重新导出本文件"])
    set_widths(ws5, [18, 80])
    style_header(ws5, 2)
    fill_body(ws5, 2, first_col_fill=False)
    ws5.cell(row=6, column=1).fill = WARN_FILL

    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    cols = conn.execute("SELECT COUNT(*) FROM schema_meta").fetchone()[0]
    conn.close()
    print(f"saved: {out}")
    print(f"表 {len(TABLES)} 个 / 字段 {cols} 条 / 枚举 {len(ENUMS)} 条 / 索引 {len(INDEXES)} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
