"""SQLite 存储层（v3）：内容寻址存储 + 实体表 + 分层。

三层结构：
    blob_store      原始字节（按 sha256 去重；小于阈值内联 BLOB，超过落文件）
    raw_email       邮件实体（母）
    raw_attachment  附件实体（子，带 raw_email_id 外键）
    parse_run       每次解析运行
    stage_*         解析结果（可由 raw 重建）
    mart_rfq        业务模型（CanonicalRFQ）

为什么邮件和附件不再塞进同一张表：
- 它们是两个实体，附件是邮件的子资源，血缘必须显式（raw_attachment.raw_email_id）；
- 字节存储和实体身份是两件事：字节按内容寻址（同一张图被两封邮件带上只存一份），
  实体按出现次数（两封邮件各有一条 raw_attachment）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from ..models import Envelope

SCHEMA_VERSION = "7"

# 小于这个字节数的内容内联存进库；更大的要求落文件，库里只留路径
INLINE_MAX_BYTES = 1024 * 1024

DDL = """
PRAGMA foreign_keys = ON;

-- ========== 内容寻址存储：同一份字节只存一次 ==========
CREATE TABLE IF NOT EXISTS blob_store (
    sha256      TEXT PRIMARY KEY,
    size_bytes  INTEGER NOT NULL,
    storage     TEXT NOT NULL CHECK (storage IN ('inline', 'file')),
    content     BLOB,                 -- storage='inline' 时有值
    file_path   TEXT,                 -- storage='file' 时有值
    created_at  TEXT NOT NULL
);

-- ========== raw 实体层 ==========
CREATE TABLE IF NOT EXISTS raw_email (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    blob_sha256   TEXT NOT NULL UNIQUE REFERENCES blob_store(sha256),
    message_id    TEXT,
    subject       TEXT,               -- 邮件名/主题（信封字段，不需解析正文）
    sender_name   TEXT,
    sender_email  TEXT,
    to_recipients TEXT,               -- 收件人 JSON 数组
    sent_at       TEXT,               -- 邮件头里的发送时间
    filename      TEXT,
    size_bytes    INTEGER NOT NULL,
    source_ref    TEXT,               -- 邮箱地址 / 上传批次 / 手工导入
    received_at   TEXT NOT NULL       -- 我们收到它的时间（与 sent_at 不同）
);

CREATE TABLE IF NOT EXISTS raw_attachment (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_email_id  INTEGER NOT NULL REFERENCES raw_email(id) ON DELETE CASCADE,
    blob_sha256   TEXT NOT NULL REFERENCES blob_store(sha256),
    filename      TEXT NOT NULL,
    mime          TEXT,
    size_bytes    INTEGER NOT NULL,
    stored_path   TEXT,               -- 落盘路径，直接能打开
    ordinal       INTEGER,            -- 在邮件里的顺序
    UNIQUE (raw_email_id, filename)
);

-- ========== 运行记录 ==========
CREATE TABLE IF NOT EXISTS parse_run (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    run_uuid           TEXT NOT NULL UNIQUE,
    raw_email_id       INTEGER REFERENCES raw_email(id) ON DELETE CASCADE,
    raw_attachment_id  INTEGER REFERENCES raw_attachment(id) ON DELETE CASCADE,
    parser             TEXT,
    parser_version     TEXT,
    started_at         TEXT NOT NULL,
    finished_at        TEXT,
    status             TEXT NOT NULL DEFAULT 'running'
                       CHECK (status IN ('running', 'ok', 'failed')),
    note               TEXT
);

-- ========== stage 层：解析结果，可重建 ==========
CREATE TABLE IF NOT EXISTS stage_email (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_email_id        INTEGER NOT NULL REFERENCES raw_email(id) ON DELETE CASCADE,
    run_id              INTEGER REFERENCES parse_run(id) ON DELETE SET NULL,
    message_id          TEXT,
    subject             TEXT,
    sender_name         TEXT,
    sender_email        TEXT,
    recipients          TEXT,
    sent_at             TEXT,
    body_text           TEXT,
    rfq_ids             TEXT,
    customer_name       TEXT,
    customer_level      TEXT CHECK (customer_level IS NULL OR customer_level IN
                                    ('high', 'medium', 'needs_review', 'draft')),
    customer_confidence REAL,
    warnings            TEXT,
    staged_at           TEXT NOT NULL,
    UNIQUE (raw_email_id, run_id)
);

CREATE TABLE IF NOT EXISTS stage_attachment (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_attachment_id  INTEGER NOT NULL REFERENCES raw_attachment(id) ON DELETE CASCADE,
    stage_email_id     INTEGER REFERENCES stage_email(id) ON DELETE CASCADE,
    run_id             INTEGER REFERENCES parse_run(id) ON DELETE SET NULL,
    filename           TEXT NOT NULL,
    content_type       TEXT,
    size_bytes         INTEGER,
    sha256             TEXT,
    local_path         TEXT,
    parser             TEXT,
    parser_version     TEXT,
    parsed_at          TEXT,
    status             TEXT NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'ok', 'failed', 'skipped')),
    error              TEXT,
    warnings           TEXT,             -- 解析告警 JSON 数组（如 needs_ocr）
    UNIQUE (stage_email_id, filename)
);

CREATE TABLE IF NOT EXISTS stage_block (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_attachment_id INTEGER REFERENCES stage_attachment(id) ON DELETE CASCADE,
    stage_email_id      INTEGER REFERENCES stage_email(id) ON DELETE CASCADE,
    run_id              INTEGER REFERENCES parse_run(id) ON DELETE SET NULL,
    block_type          TEXT NOT NULL CHECK (block_type IN ('text', 'table_row', 'kv', 'title')),
    locator             TEXT,
    ordinal             INTEGER,
    key                 TEXT,
    value               TEXT,
    row_json            TEXT,
    created_at          TEXT NOT NULL
);

-- ========== mart 层 ==========
CREATE TABLE IF NOT EXISTS mart_rfq (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    stage_email_id INTEGER REFERENCES stage_email(id) ON DELETE CASCADE,
    rfq_no         TEXT,
    customer_name  TEXT,
    payload_json   TEXT,
    built_at       TEXT NOT NULL
);

-- ========== 元数据 ==========
CREATE TABLE IF NOT EXISTS schema_meta (
    table_name  TEXT NOT NULL,
    column_name TEXT NOT NULL,
    data_type   TEXT,
    description TEXT,
    source      TEXT,                -- 这个值从哪来（邮件头 / MIME / 解析器 / 计算 / 系统生成 …）
    layer       TEXT,
    version     TEXT,
    PRIMARY KEY (table_name, column_name)
);

CREATE TABLE IF NOT EXISTS db_meta (
    key        TEXT PRIMARY KEY,
    value      TEXT,
    updated_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_raw_att_email   ON raw_attachment(raw_email_id);
CREATE INDEX IF NOT EXISTS idx_run_email       ON parse_run(raw_email_id);
CREATE INDEX IF NOT EXISTS idx_stage_email_raw ON stage_email(raw_email_id);
CREATE INDEX IF NOT EXISTS idx_stage_email_to  ON stage_email(sender_email);
CREATE INDEX IF NOT EXISTS idx_stage_att_email ON stage_attachment(stage_email_id);
CREATE INDEX IF NOT EXISTS idx_block_email     ON stage_block(stage_email_id);
CREATE INDEX IF NOT EXISTS idx_block_attach    ON stage_block(stage_attachment_id);
"""

# 表名, 字段, 类型, 含义, 层
SCHEMA_META = [
    ("blob_store", "sha256", "TEXT", "内容哈希，主键；同一份字节只存一次", "blob"),
    ("blob_store", "size_bytes", "INTEGER", "字节数", "blob"),
    ("blob_store", "storage", "TEXT", "inline（库内）/ file（落盘，库里只留路径）", "blob"),
    ("blob_store", "content", "BLOB", "内联时的原始字节，不做任何转换", "blob"),
    ("blob_store", "file_path", "TEXT", "落文件时的绝对路径", "blob"),
    ("blob_store", "created_at", "TEXT", "首次入库时间", "blob"),

    ("raw_email", "id", "INTEGER", "邮件实体编号", "raw"),
    ("raw_email", "blob_sha256", "TEXT", "指向 blob_store 的原始字节", "raw"),
    ("raw_email", "message_id", "TEXT", "邮件 Message-ID 头", "raw"),
    ("raw_email", "subject", "TEXT", "邮件名/主题（信封字段）", "raw"),
    ("raw_email", "sender_name", "TEXT", "发件人显示名", "raw"),
    ("raw_email", "sender_email", "TEXT", "发件人邮箱", "raw"),
    ("raw_email", "to_recipients", "TEXT", "收件人 JSON 数组", "raw"),
    ("raw_email", "sent_at", "TEXT", "邮件头里的发送时间", "raw"),
    ("raw_email", "filename", "TEXT", "导入时的文件名", "raw"),
    ("raw_email", "size_bytes", "INTEGER", "字节数", "raw"),
    ("raw_email", "source_ref", "TEXT", "来源：邮箱地址 / 上传批次", "raw"),
    ("raw_email", "received_at", "TEXT", "我们收到它的时间（UTC，与 sent_at 不同）", "raw"),

    ("raw_attachment", "id", "INTEGER", "附件实体编号", "raw"),
    ("raw_attachment", "raw_email_id", "INTEGER", "所属邮件（血缘）", "raw"),
    ("raw_attachment", "blob_sha256", "TEXT", "指向 blob_store 的原始字节", "raw"),
    ("raw_attachment", "filename", "TEXT", "文件名", "raw"),
    ("raw_attachment", "mime", "TEXT", "MIME 类型", "raw"),
    ("raw_attachment", "size_bytes", "INTEGER", "字节数", "raw"),
    ("raw_attachment", "stored_path", "TEXT", "落盘路径，拿到即可打开", "raw"),
    ("raw_attachment", "ordinal", "INTEGER", "在邮件里的顺序", "raw"),

    ("parse_run", "id", "INTEGER", "运行编号", "run"),
    ("parse_run", "run_uuid", "TEXT", "运行唯一标识", "run"),
    ("parse_run", "raw_email_id", "INTEGER", "解析的是哪封原始邮件", "run"),
    ("parse_run", "raw_attachment_id", "INTEGER", "解析单个附件时有值", "run"),
    ("parse_run", "parser", "TEXT", "解析器名称", "run"),
    ("parse_run", "parser_version", "TEXT", "解析器版本", "run"),
    ("parse_run", "started_at", "TEXT", "开始时间", "run"),
    ("parse_run", "finished_at", "TEXT", "结束时间", "run"),
    ("parse_run", "status", "TEXT", "running / ok / failed", "run"),
    ("parse_run", "note", "TEXT", "备注；失败原因", "run"),

    ("stage_email", "id", "INTEGER", "编号", "stage"),
    ("stage_email", "raw_email_id", "INTEGER", "对应的原始邮件", "stage"),
    ("stage_email", "run_id", "INTEGER", "哪次运行产出；同原件可有多套", "stage"),
    ("stage_email", "message_id", "TEXT", "Message-ID 头", "stage"),
    ("stage_email", "subject", "TEXT", "主题", "stage"),
    ("stage_email", "sender_name", "TEXT", "发件人显示名", "stage"),
    ("stage_email", "sender_email", "TEXT", "发件人邮箱", "stage"),
    ("stage_email", "recipients", "TEXT", "收件人 JSON 数组", "stage"),
    ("stage_email", "sent_at", "TEXT", "发送时间", "stage"),
    ("stage_email", "body_text", "TEXT", "正文纯文本", "stage"),
    ("stage_email", "rfq_ids", "TEXT", "询价编号 JSON 数组", "stage"),
    ("stage_email", "customer_name", "TEXT", "客户公司名，可空", "stage"),
    ("stage_email", "customer_level", "TEXT", "high / medium / needs_review / draft", "stage"),
    ("stage_email", "customer_confidence", "REAL", "置信分数 0–1", "stage"),
    ("stage_email", "warnings", "TEXT", "告警 JSON 数组", "stage"),
    ("stage_email", "staged_at", "TEXT", "写入时间", "stage"),

    ("stage_attachment", "id", "INTEGER", "编号", "stage"),
    ("stage_attachment", "raw_attachment_id", "INTEGER", "对应的原始附件", "stage"),
    ("stage_attachment", "stage_email_id", "INTEGER", "挂在哪封已解析邮件下", "stage"),
    ("stage_attachment", "run_id", "INTEGER", "哪次运行产出", "stage"),
    ("stage_attachment", "filename", "TEXT", "文件名", "stage"),
    ("stage_attachment", "content_type", "TEXT", "MIME 类型", "stage"),
    ("stage_attachment", "size_bytes", "INTEGER", "字节数", "stage"),
    ("stage_attachment", "sha256", "TEXT", "内容哈希", "stage"),
    ("stage_attachment", "local_path", "TEXT", "解析器读取用的落盘路径", "stage"),
    ("stage_attachment", "parser", "TEXT", "处理它的解析器", "stage"),
    ("stage_attachment", "parser_version", "TEXT", "解析器版本", "stage"),
    ("stage_attachment", "parsed_at", "TEXT", "解析时间", "stage"),
    ("stage_attachment", "status", "TEXT", "pending / ok / failed / skipped", "stage"),
    ("stage_attachment", "error", "TEXT", "失败原因", "stage"),
    ("stage_attachment", "warnings", "TEXT", "解析告警 JSON 数组（如 needs_ocr）", "stage"),

    ("stage_block", "id", "INTEGER", "编号", "stage"),
    ("stage_block", "stage_attachment_id", "INTEGER", "来自哪个附件；正文块为空", "stage"),
    ("stage_block", "stage_email_id", "INTEGER", "所属邮件", "stage"),
    ("stage_block", "run_id", "INTEGER", "产出它的运行", "stage"),
    ("stage_block", "block_type", "TEXT", "text / table_row / kv / title", "stage"),
    ("stage_block", "locator", "TEXT", "出处：sheet!单元格 / 页码 / 幻灯片号", "stage"),
    ("stage_block", "ordinal", "INTEGER", "顺序", "stage"),
    ("stage_block", "key", "TEXT", "键值块的键", "stage"),
    ("stage_block", "value", "TEXT", "值", "stage"),
    ("stage_block", "row_json", "TEXT", "表格行整行 JSON", "stage"),
    ("stage_block", "created_at", "TEXT", "写入时间", "stage"),

    ("mart_rfq", "id", "INTEGER", "编号", "mart"),
    ("mart_rfq", "stage_email_id", "INTEGER", "来源邮件", "mart"),
    ("mart_rfq", "rfq_no", "TEXT", "询价编号", "mart"),
    ("mart_rfq", "customer_name", "TEXT", "客户", "mart"),
    ("mart_rfq", "payload_json", "TEXT", "CanonicalRFQ 全文", "mart"),
    ("mart_rfq", "built_at", "TEXT", "生成时间", "mart"),

    ("schema_meta", "table_name", "TEXT", "被说明的表", "meta"),
    ("schema_meta", "column_name", "TEXT", "被说明的字段", "meta"),
    ("schema_meta", "data_type", "TEXT", "字段类型", "meta"),
    ("schema_meta", "description", "TEXT", "字段含义", "meta"),
    ("schema_meta", "layer", "TEXT", "blob / raw / run / stage / mart / meta", "meta"),
    ("schema_meta", "version", "TEXT", "对应 schema 版本", "meta"),
    ("db_meta", "key", "TEXT", "元信息键", "meta"),
    ("db_meta", "value", "TEXT", "元信息值", "meta"),
    ("db_meta", "updated_at", "TEXT", "更新时间", "meta"),
]


# 每个字段的值从哪来。键与 SCHEMA_META 一一对应，测试会校验没有漏项。
SOURCE_MAP: dict[tuple[str, str], str] = {
    # ---- blob_store ----
    ("blob_store", "sha256"): "计算：sha256(原始字节)，同时作为内容寻址键",
    ("blob_store", "size_bytes"): "计算：len(原始字节)",
    ("blob_store", "storage"): "规则：字节 ≤1 MiB 存 inline，超过则存 file",
    ("blob_store", "content"): "原始字节，入库时原样写入，未做任何转换",
    ("blob_store", "file_path"): "入库参数：调用方提供的落盘路径",
    ("blob_store", "created_at"): "系统生成：首次入库时间",
    # ---- raw_email ----
    ("raw_email", "id"): "数据库自增",
    ("raw_email", "blob_sha256"): "计算：sha256(邮件字节)；同值即同一封邮件（幂等键）",
    ("raw_email", "message_id"): "邮件头 Message-ID",
    ("raw_email", "subject"): "邮件头 Subject（MIME 编码已解码）",
    ("raw_email", "sender_name"): "邮件头 From 的显示名",
    ("raw_email", "sender_email"): "邮件头 From 的地址",
    ("raw_email", "to_recipients"): "邮件头 To，解析成地址数组后存 JSON",
    ("raw_email", "sent_at"): "邮件头 Date，转 ISO8601",
    ("raw_email", "filename"): "入库参数：导入时的文件名",
    ("raw_email", "size_bytes"): "计算：len(邮件字节)",
    ("raw_email", "source_ref"): "入库参数：调用方标注的来源（邮箱 / 批次）",
    ("raw_email", "received_at"): "系统生成：入库时刻（UTC）",
    # ---- raw_attachment ----
    ("raw_attachment", "id"): "数据库自增",
    ("raw_attachment", "raw_email_id"): "外键 → raw_email.id，表示这封附件属于哪封邮件",
    ("raw_attachment", "blob_sha256"): "计算：sha256(附件字节)",
    ("raw_attachment", "filename"): "MIME 分段头 Content-Disposition 的 filename（已清洗非法字符）",
    ("raw_attachment", "mime"): "MIME 分段头 Content-Type",
    ("raw_attachment", "size_bytes"): "计算：解码后的字节长度",
    ("raw_attachment", "stored_path"): "第一步落盘时写出的实际路径",
    ("raw_attachment", "ordinal"): "系统生成：附件在邮件中出现的顺序",
    # ---- parse_run ----
    ("parse_run", "id"): "数据库自增",
    ("parse_run", "run_uuid"): "系统生成：uuid4",
    ("parse_run", "raw_email_id"): "外键 → raw_email.id，本次解析的输入",
    ("parse_run", "raw_attachment_id"): "外键 → raw_attachment.id，解析单个附件时有值",
    ("parse_run", "parser"): "运行参数：解析器名称",
    ("parse_run", "parser_version"): "运行参数：解析器版本号",
    ("parse_run", "started_at"): "系统生成：运行开始时刻",
    ("parse_run", "finished_at"): "系统生成：运行结束时刻",
    ("parse_run", "status"): "运行结果：ok / failed",
    ("parse_run", "note"): "运行结果：异常信息或备注",
    # ---- stage_email ----
    ("stage_email", "id"): "数据库自增",
    ("stage_email", "raw_email_id"): "外键 → raw_email.id",
    ("stage_email", "run_id"): "外键 → parse_run.id，标明是哪次解析的产出",
    ("stage_email", "message_id"): "解析器 email_reader：读邮件头（与 raw_email 并存，用于校验解析是否走样）",
    ("stage_email", "subject"): "解析器 email_reader：读邮件头",
    ("stage_email", "sender_name"): "解析器 email_reader：读邮件头 From",
    ("stage_email", "sender_email"): "解析器 email_reader：读邮件头 From",
    ("stage_email", "recipients"): "解析器 email_reader：读邮件头 To，存 JSON 数组",
    ("stage_email", "sent_at"): "解析器 email_reader：读邮件头 Date",
    ("stage_email", "body_text"): "解析器：正文（text/plain 优先，只有 HTML 时转文本）",
    ("stage_email", "rfq_ids"): "解析器：正则从主题与正文提取询价编号（RFQ / Enquiry / 询价单…）",
    ("stage_email", "customer_name"): "规则：签名行公司名正则；抓不到就留空并告警",
    ("stage_email", "customer_level"): "规则：目录 / 附件标题 / 签名三类证据加权后判定",
    ("stage_email", "customer_confidence"): "规则：证据权重之和（0–1）",
    ("stage_email", "warnings"): "解析器：告警代码列表（JSON）",
    ("stage_email", "staged_at"): "系统生成：写入时刻",
    # ---- stage_attachment ----
    ("stage_attachment", "id"): "数据库自增",
    ("stage_attachment", "raw_attachment_id"): "外键 → raw_attachment.id",
    ("stage_attachment", "stage_email_id"): "外键 → stage_email.id",
    ("stage_attachment", "run_id"): "外键 → parse_run.id",
    ("stage_attachment", "filename"): "继承自 raw_attachment.filename",
    ("stage_attachment", "content_type"): "继承自 raw_attachment.mime",
    ("stage_attachment", "size_bytes"): "继承自 raw_attachment.size_bytes",
    ("stage_attachment", "sha256"): "继承自 blob_store.sha256",
    ("stage_attachment", "local_path"): "继承：第一步落盘路径",
    ("stage_attachment", "parser"): "第二步解析时写入：处理它的解析器",
    ("stage_attachment", "parser_version"): "第二步解析时写入：解析器版本",
    ("stage_attachment", "parsed_at"): "系统生成：解析完成时刻",
    ("stage_attachment", "status"): "解析结果：pending / ok / failed / skipped",
    ("stage_attachment", "error"): "解析结果：异常信息",
    ("stage_attachment", "warnings"): "解析器：告警代码列表（JSON），如 needs_ocr",
    # ---- stage_block ----
    ("stage_block", "id"): "数据库自增",
    ("stage_block", "stage_attachment_id"): "外键 → stage_attachment.id；来自邮件正文时为空",
    ("stage_block", "stage_email_id"): "外键 → stage_email.id",
    ("stage_block", "run_id"): "外键 → parse_run.id",
    ("stage_block", "block_type"): "解析器判定：text / table_row / kv / title",
    ("stage_block", "locator"): "解析器生成：sheet!单元格 / 页码 / 幻灯片号",
    ("stage_block", "ordinal"): "解析器：块在来源中的顺序",
    ("stage_block", "key"): "解析器：键值对的键或表格列名",
    ("stage_block", "value"): "解析器：文本值或键值对的值",
    ("stage_block", "row_json"): "解析器：整行序列化为 JSON",
    ("stage_block", "created_at"): "系统生成：写入时刻",
    # ---- mart_rfq ----
    ("mart_rfq", "id"): "数据库自增",
    ("mart_rfq", "stage_email_id"): "外键 → stage_email.id",
    ("mart_rfq", "rfq_no"): "规则：取 stage_email.rfq_ids 的首个编号",
    ("mart_rfq", "customer_name"): "规则：客户识别结果（stage_email.customer_name）",
    ("mart_rfq", "payload_json"): "第三步：CanonicalRFQ 序列化",
    ("mart_rfq", "built_at"): "系统生成：生成时刻",
    # ---- 元数据 ----
    ("schema_meta", "table_name"): "源文件常量：store/db.py",
    ("schema_meta", "column_name"): "源文件常量：store/db.py",
    ("schema_meta", "data_type"): "源文件常量：store/db.py",
    ("schema_meta", "description"): "人工编写",
    ("schema_meta", "source"): "人工编写（本列）",
    ("schema_meta", "layer"): "人工标注",
    ("schema_meta", "version"): "常量：SCHEMA_VERSION",
    ("db_meta", "key"): "系统写入：init_db",
    ("db_meta", "value"): "系统写入：init_db",
    ("db_meta", "updated_at"): "系统生成：写入时刻",
}


def utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect(db_path: str | Path) -> sqlite3.Connection:
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _prepare_meta_tables(conn: sqlite3.Connection) -> None:
    """旧版本元数据表列不同时直接重建——它只是文档。"""
    cols = [row[1] for row in conn.execute("PRAGMA table_info(schema_meta)")]
    if cols and ("layer" not in cols or "source" not in cols):
        conn.execute("DROP TABLE schema_meta")
        conn.commit()


def init_db(conn: sqlite3.Connection) -> None:
    _prepare_meta_tables(conn)
    conn.executescript(DDL)
    now = utcnow()
    conn.executemany(
        "INSERT OR REPLACE INTO schema_meta "
        "(table_name, column_name, data_type, description, source, layer, version) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        [
            (t, c, dt, desc, SOURCE_MAP.get((t, c), ""), layer, SCHEMA_VERSION)
            for t, c, dt, desc, layer in SCHEMA_META
        ],
    )
    conn.executemany(
        "INSERT OR REPLACE INTO db_meta (key, value, updated_at) VALUES (?, ?, ?)",
        [
            ("schema_version", SCHEMA_VERSION, now),
            ("architecture", "blob_store + raw entities -> stage -> mart", now),
            ("application", "quotation-agent", now),
            ("description", "原件按内容寻址保存；解析结果与业务模型均可由原件重建", now),
        ],
    )
    conn.commit()


# ---------------------------------------------------------------- blob 层

def put_blob(conn: sqlite3.Connection, data: bytes, file_path: str | None = None) -> str:
    """把字节放进内容寻址存储，返回 sha256。相同内容只存一次。

    超过 INLINE_MAX_BYTES 的必须给出 file_path（字节已落盘，库里不存体）。
    """
    digest = hashlib.sha256(data).hexdigest()
    row = conn.execute("SELECT sha256 FROM blob_store WHERE sha256 = ?", (digest,)).fetchone()
    if row:
        return digest

    if len(data) <= INLINE_MAX_BYTES:
        conn.execute(
            "INSERT INTO blob_store (sha256, size_bytes, storage, content, created_at) VALUES (?, ?, 'inline', ?, ?)",
            (digest, len(data), sqlite3.Binary(data), utcnow()),
        )
    else:
        if not file_path:
            raise ValueError(
                f"内容 {len(data)} 字节超过内联阈值 {INLINE_MAX_BYTES}，必须提供 file_path"
            )
        conn.execute(
            "INSERT INTO blob_store (sha256, size_bytes, storage, file_path, created_at) VALUES (?, ?, 'file', ?, ?)",
            (digest, len(data), file_path, utcnow()),
        )
    conn.commit()
    return digest


def get_blob(conn: sqlite3.Connection, sha256: str) -> bytes:
    """取出原始字节；file 存储时从磁盘读。"""
    row = conn.execute("SELECT storage, content, file_path FROM blob_store WHERE sha256 = ?", (sha256,)).fetchone()
    if not row:
        raise KeyError(f"blob not found: {sha256}")
    if row["storage"] == "inline":
        return bytes(row["content"])
    return Path(row["file_path"]).read_bytes()


# ---------------------------------------------------------------- raw 实体层

def save_raw_email(
    conn: sqlite3.Connection,
    data: bytes,
    headers: dict | None = None,
    filename: str | None = None,
    source_ref: str | None = None,
    stored_path: str | None = None,
) -> int:
    """邮件原件入库（信封字段 + blob），返回 raw_email.id。

    headers 来自 email_reader.parse_headers()：发件人、收件人、主题、发送时间、Message-ID。
    这些字段在邮件头上就有，和"解析邮件内容"是两件事。
    """
    h = headers or {}
    digest = put_blob(conn, data, file_path=stored_path)

    # 幂等：同一封邮件（字节完全相同）只留一条原始记录，重复导入返回原 id。
    existing = conn.execute("SELECT id FROM raw_email WHERE blob_sha256 = ?", (digest,)).fetchone()
    if existing:
        return int(existing["id"])

    cur = conn.execute(
        """
        INSERT INTO raw_email
            (blob_sha256, message_id, subject, sender_name, sender_email, to_recipients,
             sent_at, filename, size_bytes, source_ref, received_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            digest,
            h.get("message_id"),
            h.get("subject"),
            h.get("sender_name"),
            h.get("sender_email"),
            json.dumps(h.get("recipients") or [], ensure_ascii=False),
            h.get("sent_at"),
            filename,
            len(data),
            source_ref,
            utcnow(),
        ),
    )
    conn.commit()
    return int(cur.lastrowid)


def save_raw_attachment(
    conn: sqlite3.Connection,
    raw_email_id: int,
    data: bytes,
    filename: str,
    mime: str | None = None,
    stored_path: str | None = None,
    ordinal: int | None = None,
) -> int:
    """附件原件入库（挂到邮件下），返回 raw_attachment.id。

    stored_path 是落盘路径，拿到就能直接打开；ordinal 保留邮件里的顺序。
    """
    digest = put_blob(conn, data, file_path=stored_path)
    existing = conn.execute(
        "SELECT id FROM raw_attachment WHERE raw_email_id = ? AND filename = ?", (raw_email_id, filename)
    ).fetchone()
    if existing:
        conn.execute(
            "UPDATE raw_attachment SET stored_path = COALESCE(?, stored_path), ordinal = COALESCE(?, ordinal) WHERE id = ?",
            (stored_path, ordinal, existing["id"]),
        )
        conn.commit()
        return int(existing["id"])
    cur = conn.execute(
        "INSERT INTO raw_attachment (raw_email_id, blob_sha256, filename, mime, size_bytes, stored_path, ordinal) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (raw_email_id, digest, filename, mime, len(data), stored_path, ordinal),
    )
    conn.commit()
    return int(cur.lastrowid)


# ---------------------------------------------------------------- 运行与 stage

def start_run(
    conn: sqlite3.Connection,
    parser: str,
    parser_version: str = "1",
    raw_email_id: int | None = None,
    raw_attachment_id: int | None = None,
) -> int:
    cur = conn.execute(
        "INSERT INTO parse_run (run_uuid, raw_email_id, raw_attachment_id, parser, parser_version, started_at, status) "
        "VALUES (?, ?, ?, ?, ?, ?, 'running')",
        (str(uuid.uuid4()), raw_email_id, raw_attachment_id, parser, parser_version, utcnow()),
    )
    conn.commit()
    return int(cur.lastrowid)


def finish_run(conn: sqlite3.Connection, run_id: int, status: str = "ok", note: str | None = None) -> None:
    conn.execute(
        "UPDATE parse_run SET status = ?, finished_at = ?, note = COALESCE(?, note) WHERE id = ?",
        (status, utcnow(), note, run_id),
    )
    conn.commit()


def stage_envelope(
    conn: sqlite3.Connection,
    raw_email_id: int,
    envelope: Envelope,
    run_id: int | None = None,
    resolution=None,
) -> int:
    """把解析结果写进 stage 层，返回 stage_email.id。"""
    existing = conn.execute(
        "SELECT id FROM stage_email WHERE raw_email_id = ? AND (run_id IS ? OR run_id = ?)",
        (raw_email_id, run_id, run_id),
    ).fetchone()
    if existing:
        stage_id = int(existing["id"])
    else:
        cur = conn.execute(
            """
            INSERT INTO stage_email (
                raw_email_id, run_id, message_id, subject, sender_name, sender_email,
                recipients, sent_at, body_text, rfq_ids, customer_name, customer_level,
                customer_confidence, warnings, staged_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                raw_email_id, run_id, envelope.message_id, envelope.subject, envelope.sender_name,
                envelope.sender_email, json.dumps(envelope.recipients, ensure_ascii=False),
                envelope.date.isoformat() if envelope.date else None, envelope.body_text,
                json.dumps(envelope.rfq_ids, ensure_ascii=False),
                resolution.company if resolution else envelope.customer_name,
                resolution.level if resolution else None,
                resolution.confidence if resolution else None,
                json.dumps(envelope.warnings, ensure_ascii=False), utcnow(),
            ),
        )
        stage_id = int(cur.lastrowid)

    for i, att in enumerate(envelope.attachments, start=1):
        path = Path(att.path)
        data = path.read_bytes() if path.exists() else b""
        att_raw_id = save_raw_attachment(
            conn, raw_email_id, data, att.filename,
            mime=att.content_type, stored_path=att.path, ordinal=i,
        )
        conn.execute(
            """
            INSERT INTO stage_attachment
                (raw_attachment_id, stage_email_id, run_id, filename, content_type, size_bytes, sha256, local_path, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
            ON CONFLICT(stage_email_id, filename) DO UPDATE SET
                raw_attachment_id = excluded.raw_attachment_id,
                size_bytes = excluded.size_bytes,
                sha256 = excluded.sha256,
                local_path = excluded.local_path
            """,
            (att_raw_id, stage_id, run_id, att.filename, att.content_type, att.size_bytes, att.sha256, att.path),
        )

    conn.commit()
    return stage_id


def update_attachment_parse(
    conn: sqlite3.Connection,
    stage_attachment_id: int,
    status: str,
    parser: str,
    parser_version: str = "1",
    error: str | None = None,
    warnings: list[str] | None = None,
) -> None:
    """记录一次附件解析的结果（成功/失败、告警、解析器版本）。"""
    conn.execute(
        "UPDATE stage_attachment SET status = ?, parser = ?, parser_version = ?, parsed_at = ?, "
        "error = ?, warnings = ? WHERE id = ?",
        (
            status, parser, parser_version, utcnow(),
            error, json.dumps(warnings or [], ensure_ascii=False), stage_attachment_id,
        ),
    )
    conn.commit()


def save_blocks(
    conn: sqlite3.Connection,
    stage_email_id: int,
    stage_attachment_id: int | None,
    blocks: list[dict],
    run_id: int | None = None,
) -> int:
    now = utcnow()
    rows = [
        (
            stage_attachment_id, stage_email_id, run_id, b["block_type"], b.get("locator", ""),
            b.get("ordinal", 0), b.get("key"), b.get("value"),
            json.dumps(b["row"], ensure_ascii=False) if "row" in b else None, now,
        )
        for b in blocks
    ]
    conn.executemany(
        "INSERT INTO stage_block (stage_attachment_id, stage_email_id, run_id, block_type, locator, ordinal, key, value, row_json, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    return len(rows)


def summary(conn: sqlite3.Connection) -> dict[str, int]:
    out: dict[str, int] = {}
    for table in (
        "blob_store", "raw_email", "raw_attachment", "parse_run",
        "stage_email", "stage_attachment", "stage_block", "mart_rfq",
        "schema_meta", "db_meta",
    ):
        try:
            out[table] = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            out[table] = -1
    return out


def sha256_file(path: str | Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
