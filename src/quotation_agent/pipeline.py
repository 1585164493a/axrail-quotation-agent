"""端到端流水线：一封邮件进来，一份报价出去。

    ingest_email()   原件入库 + 解析邮件头/正文 → stage_email / stage_attachment
    parse_attachments()  附件解析 → stage_block
    build_quote()        块 → CanonicalRFQ → 定价 → mart_rfq

tools/ 下的脚本只做 CLI，业务编排都在这里，测试可以直接调用。
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .extract import hybrid_blocks
from .identity import resolve_customer
from .ingest.email_reader import parse_headers, read_bytes
from .llm import bedrock_extract_lines
from .parsers import dispatch
from .store.db import (
    finish_run,
    get_blob,
    save_blocks,
    save_raw_email,
    stage_envelope,
    start_run,
    update_attachment_parse,
)

PARSER_VERSION = "1"


def _stage_email(conn: sqlite3.Connection, raw_id: int, data: bytes, filename: str,
                 run_id: int, staging: Path) -> dict:
    """解析一封邮件并写 stage：信封字段 + 正文零件行 + 附件。"""
    envelope = read_bytes(data, filename, staging)
    resolution = resolve_customer(envelope)

    # 正文提取：正则先跑，抽不全就用模型兜底（默认开启；LLM_EXTRACTION=0 可关闭）
    llm = None if os.environ.get("LLM_EXTRACTION") == "0" else bedrock_extract_lines
    body_blocks, body_warnings = hybrid_blocks(envelope.body_text, llm=llm)
    envelope.warnings.extend(body_warnings)

    stage_id = stage_envelope(conn, raw_id, envelope, run_id=run_id, resolution=resolution)
    if body_blocks:
        save_blocks(conn, stage_id, None, body_blocks, run_id=run_id)
    return {
        "stage_email_id": stage_id,
        "customer": resolution.company,
        "level": resolution.level,
        "attachments": len(envelope.attachments),
        "body_rows": len(body_blocks),
    }


def ingest_email(conn: sqlite3.Connection, path: str | Path, staging: str | Path) -> dict:
    """一封邮件：原件（含信封字段）入库 → 解析正文与附件 → 写 stage。"""
    p = Path(path)
    data = p.read_bytes()
    headers = parse_headers(data)
    raw_id = save_raw_email(conn, data, headers=headers, filename=p.name,
                            source_ref="local-import", stored_path=str(p))

    run_id = start_run(conn, "email_reader", PARSER_VERSION, raw_email_id=raw_id)
    try:
        info = _stage_email(conn, raw_id, data, p.name, run_id, Path(staging))
        finish_run(conn, run_id, "ok")
    except Exception as exc:
        finish_run(conn, run_id, "failed", str(exc))
        raise
    return {"file": p.name, "raw_id": raw_id, "run_id": run_id, **info}


def reparse_email(conn: sqlite3.Connection, raw_email_id: int, staging: str | Path,
                  parser_version: str = "2") -> dict:
    """用当前解析器重跑一份已入库的原件（解析器改了不用让客户重发）。"""
    row = conn.execute("SELECT * FROM raw_email WHERE id = ?", (raw_email_id,)).fetchone()
    if not row:
        raise SystemExit(f"no raw_email with id={raw_email_id}")

    data = get_blob(conn, row["blob_sha256"])
    filename = row["filename"] or f"raw-{raw_email_id}.eml"
    run_id = start_run(conn, "email_reader", parser_version, raw_email_id=raw_email_id)
    try:
        info = _stage_email(conn, raw_email_id, data, filename, run_id, Path(staging))
        finish_run(conn, run_id, "ok")
    except Exception as exc:
        finish_run(conn, run_id, "failed", str(exc))
        raise
    return {"file": filename, "raw_id": raw_email_id, "run_id": run_id, **info}


def _materialise(conn: sqlite3.Connection, att, scratch: Path) -> Path:
    """拿到可读路径：落盘文件还在就用它，否则从 blob 还原。"""
    if att["local_path"] and Path(att["local_path"]).exists():
        return Path(att["local_path"])

    raw = conn.execute(
        "SELECT blob_sha256 FROM raw_attachment WHERE id = ?", (att["raw_attachment_id"],)
    ).fetchone()
    if raw is None:
        raise FileNotFoundError(f"{att['filename']} has neither a staged file nor raw bytes")

    scratch.mkdir(parents=True, exist_ok=True)
    target = scratch / f"{att['id']}__{att['filename']}"
    target.write_bytes(get_blob(conn, raw["blob_sha256"]))
    return target


def parse_one(conn: sqlite3.Connection, att, scratch: Path) -> dict:
    """解析一个附件并写块；失败也留痕。"""
    path = _materialise(conn, att, scratch)
    run_id = start_run(conn, "attachment_parser", PARSER_VERSION,
                       raw_attachment_id=att["raw_attachment_id"])
    try:
        result = dispatch(path)
    except Exception as exc:
        finish_run(conn, run_id, "failed", str(exc))
        update_attachment_parse(conn, att["id"], "failed", "attachment_parser", PARSER_VERSION, error=str(exc))
        return {"file": att["filename"], "ok": False, "blocks": 0, "warnings": [], "error": str(exc)}

    if not result.ok:
        finish_run(conn, run_id, "failed", result.error)
        update_attachment_parse(conn, att["id"], "failed", "attachment_parser", PARSER_VERSION,
                                error=result.error, warnings=result.warnings)
        return {"file": att["filename"], "ok": False, "blocks": 0,
                "warnings": result.warnings, "error": result.error}

    conn.execute("DELETE FROM stage_block WHERE stage_attachment_id = ?", (att["id"],))
    n = save_blocks(conn, att["stage_email_id"], att["id"], result.blocks, run_id=run_id)
    finish_run(conn, run_id, "ok")
    update_attachment_parse(conn, att["id"], "ok", "attachment_parser", PARSER_VERSION,
                           warnings=result.warnings)
    return {"file": att["filename"], "ok": True, "blocks": n, "warnings": result.warnings, "error": ""}


def parse_attachments(conn: sqlite3.Connection, scratch: str | Path, reparse_all: bool = False) -> list[dict]:
    """处理所有 pending 附件（reparse_all=True 则重跑全部）。"""
    where = "" if reparse_all else "WHERE a.status = 'pending'"
    atts = conn.execute(f"SELECT a.* FROM stage_attachment a {where} ORDER BY a.id").fetchall()
    return [parse_one(conn, att, Path(scratch)) for att in atts]


def full_run(conn: sqlite3.Connection, path: str | Path, staging: str | Path, scratch: str | Path) -> dict:
    """一封邮件走完全程，返回报价对象。"""
    from .quote.build import build_quote

    info = ingest_email(conn, path, staging)
    parse_attachments(conn, scratch)
    info["quote"] = build_quote(conn, info["stage_email_id"])
    return info
