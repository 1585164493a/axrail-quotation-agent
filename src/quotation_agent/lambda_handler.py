"""Lambda 入口：把确定性工具暴露给 AgentCore Gateway。

设计要点：
- **无状态**：不碰数据库、不读本地文件。输入是块，输出是报价，纯函数式。
- **数字只来自代码**：这个函数里没有模型调用，Gateway 调它只是执行代码。
- **兼容多种事件形态**：Gateway 的 MCP Lambda target 传参格式随版本有差异，
  这里同时接受 {"tool"/"name"/"toolName"} 与 {"input"/"arguments"}。

工具清单（与 Gateway 的 toolSchema 一一对应）：
    price_line        单行定价，返回成本/售价/折扣/追溯
    build_quote       一组块 → 完整报价（行、挂起、冲突、审批）
    render_reply      报价 → 英文回信草稿
    render_quote_pdf  报价 → PDF，写进 S3 并返回预签名链接
"""

from __future__ import annotations

import json
import os
import uuid
from typing import Any

from .quote.build import render_text
from .quote.model import Approval, CanonicalLine, CanonicalRFQ, HeldLine, PricedLine, Quote, Trace
from .quote.normalise import candidates_from_blocks, merge
from .quote.pricing import price_line as _price_line
from .quote.render import render_quote_pdf, render_reply_email


def _ok(payload: Any) -> dict:
    """MCP 工具返回值：直接返回业务结果，Gateway 会把它序列化成文本。"""
    return payload if isinstance(payload, dict) else {"result": payload}


def _err(message: str) -> dict:
    return {"error": message}


def _infer_tool(args: dict) -> str:
    """Gateway 调 Lambda target 时只传参数、不传工具名，靠参数形状判断。

    这是 Lambda target 的固有约束：一个 target 一个 Lambda，参数就是全部信息。
    PDF 与回信都以 quote 为输入，所以用 output="pdf" 区分。
    """
    if args.get("key"):
        if args.get("preview"):
            return "preview_attachments"
        if args.get("read"):
            return "read_email"
        return "quote_email"
    if args.get("decision"):
        return "decide_approval"
    if args.get("s3_key"):
        return "decide_approval"
    if "quote" in args and args.get("submit"):
        return "submit_approval"
    if "quote" in args and str(args.get("output", "")).lower() == "review":
        return "render_review_pdf"
    if "quote" in args and "discount_rate" in args:
        return "reprice_quote"
    if "quote" in args:
        return "render_quote_pdf" if str(args.get("output", "")).lower() == "pdf" else "render_reply"
    if {"rfq_no", "body_text", "blocks"} & set(args):
        return "build_quote"
    if "part_no" in args:
        return "price_line"
    return "list_emails" if "prefix" in args else (
        "list_approvals" if args.get("list_approvals") else ("get_prices" if args.get("prices") else "")
    )


def _extract_call(event: dict) -> tuple[str, dict]:
    """从事件里取工具名与参数，兼容 Gateway 的几种传参形态（含只传参数的情况）。"""
    tool = event.get("tool") or event.get("name") or event.get("toolName") or ""
    args = event.get("input") or event.get("arguments") or event.get("args") or {}

    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    args = dict(args)

    if not args:
        # Gateway 的 Lambda target 只把工具参数摊平传过来
        meta = {"tool", "name", "toolName", "input", "arguments", "args"}
        args = {k: v for k, v in event.items() if k not in meta}

    if not tool:
        tool = _infer_tool(args)
    return str(tool), args


def tool_price_line(args: dict) -> dict:
    from .quote.model import CanonicalLine

    line = CanonicalLine(
        part_no=str(args.get("part_no", "")),
        description=str(args.get("description", "")),
        material=str(args.get("material", "")),
        material_raw=str(args.get("material", "")),
        qty=args.get("qty"),
        tol_mm=args.get("tol_mm"),
        mass_kg=args.get("mass_kg"),
        cycle_min=args.get("cycle_min"),
        finish=str(args.get("finish", "")),
        refs=["gateway.call"],
    )
    result = _price_line(line)
    if isinstance(result, PricedLine):
        return {
            "status": "priced",
            "part_no": line.part_no,
            "unit_cost": result.unit_cost,
            "list_price": result.base_price,
            "discount_rate": result.discount_rate,
            "unit_price": result.unit_price,
            "line_total": result.line_total,
            "trace": [t.as_text() for t in result.trace],
        }
    if isinstance(result, HeldLine):
        return {"status": "held", "part_no": line.part_no, "reason": result.reason, "detail": result.detail}
    return {"status": "unknown"}


def _assemble(blocks: list[dict], rfq_no: str, customer: str,
              warnings: list[str] | None = None, body_text: str = "") -> dict:
    """块 → 报价（定价 + 审批），build_quote 与 quote_email 共用。"""
    from .llm import usage_snapshot
    from .quote.build import requested_discount
    from .quote.pricing import APPROVAL_TOTAL_THRESHOLD, POLICY_MAX_DISCOUNT

    _install_value_interpreter()

    rfq = merge(candidates_from_blocks(blocks), rfq_no=rfq_no, customer=customer)
    priced, held = [], []
    for line in rfq.lines:
        result = _price_line(line)
        (priced if isinstance(result, PricedLine) else held).append(result)

    total = round(sum(p.line_total for p in priced), 2)

    # 审批判断：金额阈值 / 有挂起行 / 越权折扣 / 有冲突
    reasons: list[str] = []
    if total >= APPROVAL_TOTAL_THRESHOLD:
        reasons.append(f"Quotation total {total:,.2f} MYR exceeds the {APPROVAL_TOTAL_THRESHOLD:,.0f} MYR threshold")
    if held:
        reasons.append(f"{len(held)} line(s) cannot be priced yet (engineering / procurement)")
    wanted = requested_discount(body_text)
    if wanted > POLICY_MAX_DISCOUNT:
        reasons.append(f"Customer requested {wanted:.0%} discount, above the {POLICY_MAX_DISCOUNT:.0%} policy limit")
    if rfq.conflicts:
        reasons.append(f"{len(rfq.conflicts)} source conflict(s) (e.g. quantity or material disagree between documents)")
    low_confidence = [line for line in rfq.lines if line.confidence < 0.55]
    if low_confidence:
        reasons.append(
            f"{len(low_confidence)} line(s) need a human check "
            f"(low confidence in quantity / material / tolerance)"
        )

    return {
        "rfq_no": rfq.rfq_no,
        "customer": rfq.customer,
        "lines": [
            {
                "part_no": p.line.part_no,
                "description": p.line.description,
                "material": p.line.material,
                "qty": p.line.qty,
                "unit_cost": p.unit_cost,
                "list_price": p.base_price,
                "discount_rate": p.discount_rate,
                "unit_price": p.unit_price,
                # 数量档位后的成交价；滑杆折扣在它之上叠加，重算时不被覆盖
                "tier_unit_price": p.unit_price,
                "line_total": p.line_total,
                "refs": p.line.refs,
                "trace": [t.as_text() for t in p.trace],
                "trace_data": [
                    {"rule": t.rule, "detail": t.detail, "amount": t.amount, "source": t.source}
                    for t in p.trace
                ],
                "confidence": p.line.confidence,
                "confidence_label": p.line.confidence_label,
                "flags": p.line.flags,
                "field_confidence": p.line.field_confidence,
                "field_sources": p.line.field_sources,
                "field_values": {
                    "material": p.line.material,
                    "qty": p.line.qty,
                    "tolerance": p.line.tol_raw or p.line.tol_mm,
                    "mass": p.line.mass_kg,
                    "cycle": p.line.cycle_min,
                    "finish": p.line.finish,
                    "description": p.line.description,
                },
            }
            for p in priced
        ],
        "held": [
            {"part_no": h.line.part_no, "reason": h.reason, "detail": h.detail, "refs": h.line.refs,
             "qty": h.line.qty, "material": h.line.material, "partial": h.partial}
            for h in held
        ],
        "conflicts": [f"{c.part_no}.{c.field_name}: {c.describe()}" for c in rfq.conflicts],
        "conflict_notes": _conflict_notes(rfq.conflicts),
        "warnings": warnings or [],
        "total": total,
        "model_usage": usage_snapshot(),
        "approval": {"required": bool(reasons), "reasons": reasons},
    }


def _body_blocks(body_text: str) -> tuple[list[dict], list[str]]:
    """正文 → 块（正则优先，抽不全调模型）。"""
    from .extract import hybrid_blocks
    from .llm import extract_lines

    llm = None if os.environ.get("LLM_EXTRACTION") == "0" else extract_lines
    blocks, warnings = hybrid_blocks(body_text, llm=llm)
    return [
        {"filename": "email body", "block_type": b["block_type"], "locator": b["locator"],
         "ordinal": b.get("ordinal", 0), "row": b.get("row")}
        for b in blocks
    ], warnings


def tool_build_quote(args: dict) -> dict:
    """给定块或正文，出一份报价。"""
    from .llm import reset_usage

    reset_usage()
    blocks = args.get("blocks") or []
    warnings: list[str] = []
    if not blocks and args.get("body_text"):
        blocks, warnings = _body_blocks(str(args["body_text"]))

    return _assemble(
        blocks,
        rfq_no=str(args.get("rfq_no", "RFQ-UNKNOWN")),
        customer=str(args.get("customer", "")),
        warnings=warnings,
        body_text=str(args.get("body_text", "")),
    )


def _email_bucket() -> str:
    bucket = os.environ.get("EMAIL_BUCKET") or os.environ.get("PDF_BUCKET")
    if not bucket:
        raise RuntimeError("EMAIL_BUCKET (or PDF_BUCKET) is not configured")
    return bucket


def _s3():
    import boto3

    return boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-southeast-2"))


def tool_list_emails(args: dict) -> dict:
    """列出 S3 里待报价的邮件（供前端下拉框用，含附件名）。"""
    from email import policy
    from email.parser import BytesParser

    from .ingest.email_reader import parse_headers

    def attachment_names(raw: bytes) -> list[str]:
        try:
            message = BytesParser(policy=policy.default).parsebytes(raw)
            return [part.get_filename() for part in message.walk() if part.get_filename()]
        except Exception:  # noqa: BLE001
            return []

    prefix = str(args.get("prefix") or os.environ.get("EMAIL_PREFIX", "inbox/"))
    limit = int(args.get("limit") or 25)
    domain_filter = str(args.get("domain") or "").strip().lower()
    contact_filter = str(args.get("contact") or "").strip().lower()
    bucket = _email_bucket()
    client = _s3()

    listing = client.list_objects_v2(Bucket=bucket, Prefix=prefix, MaxKeys=limit)
    emails = []
    for obj in listing.get("Contents", []):
        key = obj["Key"]
        if key.endswith("/"):
            continue
        item = {
            "key": key,
            "size": obj["Size"],
            "modified": obj["LastModified"].isoformat(timespec="seconds"),
            "name": key.rsplit("/", 1)[-1],
        }
        try:  # 只为了显示主题/发件人/附件，读失败不影响列表
            raw = client.get_object(Bucket=bucket, Key=key)["Body"].read()
            if len(raw) < 5_000_000:
                headers = parse_headers(raw)
                sender = headers.get("sender_email", "") or headers.get("from", "")
                item["subject"] = headers.get("subject", "")
                item["from"] = sender
                item["attachments"] = attachment_names(raw)
                item["domain"] = sender.split("@")[-1].lower() if "@" in sender else ""
                # 联系人取邮箱前缀（nurul@… → nurul），显示名单独存
                item["contact"] = sender.split("@")[0].lower() if "@" in sender else ""
                item["contact_name"] = headers.get("sender_name", "")
        except Exception:  # noqa: BLE001
            item["subject"], item["from"], item["attachments"] = "", "", []
            item["domain"], item["contact"] = "", ""

        if domain_filter and item.get("domain", "") != domain_filter:
            continue
        if contact_filter and contact_filter not in str(item.get("contact", "")).lower():
            continue
        emails.append(item)

    # 按域名聚一下，前端可以直接做成筛选器
    companies: dict[str, dict] = {}
    for item in emails:
        domain = item.get("domain", "")
        if not domain:
            continue
        bucket_entry = companies.setdefault(domain, {"domain": domain, "count": 0, "contacts": []})
        bucket_entry["count"] += 1
        contact = item.get("contact", "")
        if contact and contact not in bucket_entry["contacts"]:
            bucket_entry["contacts"].append(contact)

    return {"bucket": bucket, "prefix": prefix, "count": len(emails), "emails": emails,
            "companies": sorted(companies.values(), key=lambda c: -c["count"])}


def _quote_email(args: dict) -> dict:
    """从 S3 读一封 .eml（含附件）→ 拆正文与附件 → 出报价。"""
    import tempfile
    from pathlib import Path

    from .extract import hybrid_blocks
    from .ingest.email_reader import read_bytes
    from .llm import extract_lines, reset_usage
    from .parsers import dispatch

    reset_usage()

    key = str(args.get("key") or "")
    if not key:
        return _err("key is required (S3 object key of the .eml file)")

    mode = str(args.get("mode") or "both").lower()
    if mode not in {"body", "attachments", "both"}:
        mode = "both"

    # 可选：精确勾选要读哪些部分（UI 用）
    include_body = args.get("include_body")
    include_attachments = args.get("include_attachments")
    if include_body is None and include_attachments is None:
        include_body = mode in {"body", "both"}
        include_attachments = None if mode in {"attachments", "both"} else []
    else:
        include_body = True if include_body is None else bool(include_body)
        if include_attachments is not None:
            include_attachments = [str(name) for name in include_attachments]

    if not include_body and include_attachments == []:
        return _err("nothing selected: tick the body or at least one attachment")

    bucket = _email_bucket()
    raw = _s3().get_object(Bucket=bucket, Key=key)["Body"].read()

    # Lambda 里 /tmp 可写；本地/测试可用 SCRATCH_DIR 指到工作区
    scratch_root = Path(os.environ.get("SCRATCH_DIR") or tempfile.gettempdir())
    staging = scratch_root / f"rfq-{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True, exist_ok=True)
    envelope = read_bytes(raw, Path(key).name, staging)

    warnings: list[str] = []
    blocks: list[dict] = []

    # 正文
    if include_body:
        llm = None if os.environ.get("LLM_EXTRACTION") == "0" else extract_lines
        body_blocks, body_warnings = hybrid_blocks(envelope.body_text, llm=llm)
        warnings.extend(body_warnings)
        blocks.extend(
            {"filename": "email body", "block_type": b["block_type"], "locator": b["locator"],
             "ordinal": b.get("ordinal", 0), "row": b.get("row")}
            for b in body_blocks
        )

    # 附件（None = 全部；列表 = 只读勾选的那几个）
    if include_attachments != []:
        mapper = _mapping_mapper()
        for attachment in getattr(envelope, "attachments", []):
            if include_attachments is not None and attachment.filename not in include_attachments:
                continue
            try:
                result = dispatch(attachment.path, mapper=mapper)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"{attachment.filename}: parse failed ({type(exc).__name__})")
                continue
            warnings.extend(f"{attachment.filename}: {w}" for w in result.warnings)
            if not result.ok:
                warnings.append(f"{attachment.filename}: {result.error}")
                continue
            for block in result.blocks:
                block = dict(block)
                block["filename"] = attachment.filename
                blocks.append(block)

    quote = _assemble(
        blocks,
        rfq_no=str(args.get("rfq_no") or (envelope.rfq_ids[0] if envelope.rfq_ids else "") or "RFQ-UNKNOWN"),
        customer=str(args.get("customer") or envelope.customer_name or envelope.sender_name or ""),
        warnings=warnings,
        body_text=envelope.body_text if mode in {"body", "both"} else "",
    )
    quote["mode"] = mode
    quote["source"] = {
        "email_key": key,
        "subject": envelope.subject,
        "from": f"{envelope.sender_name} <{envelope.sender_email}>".strip(" <>"),
        "attachments": [a.filename for a in getattr(envelope, "attachments", [])],
    }
    return quote


def _block_to_text(block: dict) -> str:
    """把任意块压成一行可读文本（用于附件内容预览）。"""
    if block.get("row"):
        return " | ".join(f"{k}: {v}" for k, v in block["row"].items() if v not in (None, ""))
    if block.get("text"):
        return str(block["text"]).strip()
    if block.get("value") is not None:
        return f"{block.get('key', '')}: {block['value']}".strip(": ")
    return ""


CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls": "application/vnd.ms-excel",
    ".pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


def _upload_attachment(filename: str, path: str) -> str:
    """把附件单独存一份到 S3，返回 1 小时有效的下载链接。

    为什么要单独存：附件原本封在 .eml 里，没有独立地址；
    有了独立对象，界面才能"打开原件"。
    """
    from pathlib import Path

    bucket = _email_bucket()
    client = _s3()
    digest = __import__("hashlib").sha256(Path(path).read_bytes()).hexdigest()[:12]
    key = f"attachments/{digest}-{filename}"
    suffix = Path(filename).suffix.lower()
    # 不设 ContentType 的话浏览器会把它当二进制直接下载，PDF 也就没法内嵌预览
    extra = {
        "ContentType": CONTENT_TYPES.get(suffix, "application/octet-stream"),
        "ContentDisposition": f'inline; filename="{filename}"',
    }
    # 每次都覆盖上传：老对象可能缺 ContentType，浏览器就会当二进制下载
    client.upload_file(path, bucket, key, ExtraArgs=extra)
    return client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)


def _render_original(filename: str, path: str) -> dict:
    """把原件的内容按"原样"读出来给前端画（不是我们归一化后的行）。

    - xlsx：每个 sheet 的每个单元格
    - pptx：每页的形状文字与表格
    - docx：每个段落与表格
    - pdf：不在这里解析，交给浏览器内嵌
    """
    from pathlib import Path

    suffix = Path(filename).suffix.lower()
    try:
        if suffix == ".xlsx":
            import openpyxl

            workbook = openpyxl.load_workbook(path, data_only=True, read_only=True)
            sheets = []
            for sheet in workbook.worksheets:
                rows = []
                for row in sheet.iter_rows(values_only=True):
                    rows.append(["" if cell is None else str(cell) for cell in row])
                    if len(rows) >= 300:
                        break
                while rows and not any(rows[-1]):
                    rows.pop()
                if rows:
                    sheets.append({"name": sheet.title, "rows": rows})
            workbook.close()
            return {"kind": "sheet", "sheets": sheets}

        if suffix == ".pptx":
            from pptx import Presentation

            presentation = Presentation(path)
            slides = []
            for index, slide in enumerate(presentation.slides, start=1):
                texts: list[str] = []
                tables: list[list[list[str]]] = []
                for shape in slide.shapes:
                    if getattr(shape, "has_text_frame", False) and shape.text_frame.text.strip():
                        texts.append(shape.text_frame.text.strip())
                    if getattr(shape, "has_table", False):
                        table = [[cell.text.strip() for cell in row.cells] for row in list(shape.table.rows)]
                        tables.append(table)
                slides.append({"index": index, "texts": texts, "tables": tables})
            return {"kind": "slides", "slides": slides}

        if suffix == ".docx":
            import docx

            document = docx.Document(path)
            paragraphs = [p.text.strip() for p in document.paragraphs if p.text.strip()]
            tables = [[[cell.text.strip() for cell in row.cells] for row in table.rows]
                      for table in document.tables]
            return {"kind": "doc", "paragraphs": paragraphs, "tables": tables}
    except Exception as exc:  # noqa: BLE001
        return {"kind": "unsupported", "error": f"{type(exc).__name__}: {exc}"}

    return {"kind": "pdf" if suffix == ".pdf" else "unsupported"}


def tool_preview_attachments(args: dict) -> dict:
    """把一封邮件里每个附件的内容摊开，并给出原件下载链接。"""
    import tempfile
    from pathlib import Path

    from .ingest.email_reader import read_bytes
    from .parsers import dispatch

    max_rows = int(args.get("max_rows") or 40)
    max_chars = int(args.get("max_chars") or 4000)
    key = str(args.get("key") or "")
    if not key:
        return _err("key is required")

    bucket = _email_bucket()
    raw = _s3().get_object(Bucket=bucket, Key=key)["Body"].read()

    scratch_root = Path(os.environ.get("SCRATCH_DIR") or tempfile.gettempdir())
    staging = scratch_root / f"preview-{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True, exist_ok=True)
    envelope = read_bytes(raw, Path(key).name, staging)

    attachments = []
    for attachment in getattr(envelope, "attachments", []):
        item: dict = {
            "filename": attachment.filename,
            "size": attachment.size_bytes,
            "content_type": attachment.content_type,
            "ok": True,
            "error": "",
            "warnings": [],
            "rows": [],
            "row_count": 0,
            "text": "",
            "url": "",
            "original": {},
        }
        try:
            item["url"] = _upload_attachment(attachment.filename, attachment.path)
        except Exception as exc:  # noqa: BLE001
            item["warnings"].append(f"could not create a download link ({type(exc).__name__})")

        # 原件内容（给前端直接画出来，不是归一化后的行）
        item["original"] = _render_original(attachment.filename, attachment.path)

        try:
            result = dispatch(attachment.path)
        except Exception as exc:  # noqa: BLE001
            item["ok"] = False
            item["error"] = f"{type(exc).__name__}: {exc}"
            attachments.append(item)
            continue

        item["warnings"].extend(result.warnings)
        if not result.ok:
            item["ok"] = False
            item["error"] = result.error
            attachments.append(item)
            continue

        rows = [{"locator": b.get("locator", ""), "values": b["row"]} for b in result.blocks if b.get("row")]
        item["row_count"] = len(rows)
        item["rows"] = rows[:max_rows]

        lines = [line for line in (_block_to_text(b) for b in result.blocks) if line]
        item["text"] = "\n".join(lines)[:max_chars]
        attachments.append(item)

    return {
        "email_key": key,
        "subject": envelope.subject,
        "from": f"{envelope.sender_name} <{envelope.sender_email}>".strip(" <>"),
        "attachments": attachments,
    }


def tool_read_email(args: dict) -> dict:
    """读一封邮件的信封与正文（不解析附件、不报价），供前端"收件箱"详情页用。"""
    import tempfile
    from pathlib import Path

    from .ingest.email_reader import read_bytes

    key = str(args.get("key") or "")
    if not key:
        return _err("key is required")

    bucket = _email_bucket()
    raw = _s3().get_object(Bucket=bucket, Key=key)["Body"].read()

    scratch_root = Path(os.environ.get("SCRATCH_DIR") or tempfile.gettempdir())
    staging = scratch_root / f"read-{uuid.uuid4().hex[:8]}"
    staging.mkdir(parents=True, exist_ok=True)
    envelope = read_bytes(raw, Path(key).name, staging)

    return {
        "key": key,
        "subject": envelope.subject,
        "from": f"{envelope.sender_name} <{envelope.sender_email}>".strip(" <>"),
        "sender_email": envelope.sender_email,
        "recipients": envelope.recipients,
        "date": envelope.date.isoformat() if envelope.date else "",
        "rfq_ids": envelope.rfq_ids,
        "customer": envelope.customer_name,
        "body_text": envelope.body_text,
        "attachments": [
            {"filename": a.filename, "size": a.size_bytes, "content_type": a.content_type}
            for a in getattr(envelope, "attachments", [])
        ],
    }


def tool_reprice_quote(args: dict) -> dict:
    """按给定折扣重算一份报价：单价、合计、利润、毛利率、审批影响。

    为什么放在工具里而不是前端算：定价规则（毛利、四舍五入、审批阈值）
    只有一份实现，前端滑杆只是调用它，不能自己算出一套数字。
    """
    from .quote.pricing import APPROVAL_TOTAL_THRESHOLD, POLICY_MAX_DISCOUNT

    payload = args.get("quote") or {}
    try:
        discount = float(args.get("discount_rate", 0.0))
    except (TypeError, ValueError):
        discount = 0.0
    discount = max(0.0, min(0.5, discount))

    lines = []
    total = 0.0
    total_cost = 0.0
    for item in payload.get("lines") or []:
        qty = int(item.get("qty") or 0)
        cost = float(item.get("unit_cost") or 0.0)
        base_price = float(item.get("tier_unit_price") or item.get("unit_price") or 0.0)
        list_price = float(item.get("list_price") or base_price)
        unit = round(base_price * (1 - discount), 2)
        line_total = round(unit * qty, 2)
        line_cost = round(cost * qty, 2)
        total += line_total
        total_cost += line_cost
        lines.append({
            "part_no": item.get("part_no"),
            "qty": qty,
            "unit_cost": cost,
            "list_price": list_price,
            "discount_rate": discount,
            "unit_price": unit,
            "line_total": line_total,
            "line_cost": line_cost,
            "line_profit": round(line_total - line_cost, 2),
        })

    total = round(total, 2)
    total_cost = round(total_cost, 2)
    profit = round(total - total_cost, 2)
    margin = round(profit / total, 4) if total else 0.0

    reasons = list((payload.get("approval") or {}).get("reasons") or [])
    # 金额和折扣的理由要按新数字重算，不能沿用旧的
    reasons = [r for r in reasons if "discount" not in r.lower() and "threshold" not in r.lower()]
    if discount > POLICY_MAX_DISCOUNT:
        reasons.append(
            f"Proposed {discount:.0%} discount is above the {POLICY_MAX_DISCOUNT:.0%} policy limit"
        )
    if total >= APPROVAL_TOTAL_THRESHOLD:
        reasons.append(f"Quotation total {total:,.2f} MYR exceeds the {APPROVAL_TOTAL_THRESHOLD:,.0f} MYR threshold")

    return {
        "lines": lines,
        "total": total,
        "total_cost": total_cost,
        "profit": profit,
        "margin": margin,
        "discount_rate": discount,
        "approval": {"required": bool(reasons), "reasons": reasons},
    }


def _approval_prefix() -> str:
    return os.environ.get("APPROVAL_PREFIX", "approvals/")


def tool_submit_approval(args: dict) -> dict:
    """把一份需要签字的报价提交给经理（落成 S3 里的一条待审批记录）。"""
    from datetime import datetime, timezone

    quote = args.get("quote") or {}
    if not isinstance(quote, dict) or not quote.get("lines"):
        return _err("quote with at least one priced line is required")

    rfq_no = str(quote.get("rfq_no") or "RFQ-UNKNOWN")
    stamp = datetime.now().astimezone()  # 本地时区，避免审批时间显示成 UTC
    record = {
        "id": f"{rfq_no}-{stamp.strftime('%Y%m%d-%H%M%S')}",
        "rfq_no": rfq_no,
        "customer": quote.get("customer", ""),
        "total": quote.get("total"),
        "status": "pending_manager",
        "submitted_at": stamp.isoformat(timespec="seconds"),
        "requested_by": str(args.get("requested_by") or "sales"),
        "proposed_discount": float(args.get("discount_rate") or 0.0),
        "reasons": list((quote.get("approval") or {}).get("reasons") or []),
        "flags": [
            {"part_no": line.get("part_no"), "confidence": line.get("confidence"),
             "flags": line.get("flags") or []}
            for line in quote.get("lines") or []
            if (line.get("flags") or []) or float(line.get("confidence") or 1) < 0.55
        ],
        "held": [{"part_no": h.get("part_no"), "reason": h.get("reason")} for h in quote.get("held") or []],
        "conflicts": list(quote.get("conflicts") or []),
    }

    bucket = _email_bucket()
    key = f"{_approval_prefix()}{record['id']}.json"
    _s3().put_object(Bucket=bucket, Key=key, Body=json.dumps(record, ensure_ascii=False).encode("utf-8"),
                     ContentType="application/json")
    return {"id": record["id"], "status": record["status"], "s3_key": key,
            "submitted_at": record["submitted_at"], "reasons": record["reasons"]}


def tool_list_approvals(args: dict) -> dict:
    """列出待审批 / 已审批的报价（最新在前）。"""
    limit = int(args.get("limit") or 20)
    bucket = _email_bucket()
    client = _s3()
    listing = client.list_objects_v2(Bucket=bucket, Prefix=_approval_prefix(), MaxKeys=100)
    objects = sorted(listing.get("Contents", []), key=lambda o: o["LastModified"], reverse=True)[:limit]

    items = []
    for obj in objects:
        try:
            raw = client.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            record = json.loads(raw.decode("utf-8"))
            record["s3_key"] = obj["Key"]
            items.append(record)
        except Exception:  # noqa: BLE001
            continue

    again = str(args.get("_dummy") or "")
    _ = again
    return {"count": len(items), "items": items}


def tool_decide_approval(args: dict) -> dict:
    """经理批复：approved / rejected（demo 里用来演示状态流转）。"""
    from datetime import datetime, timezone

    key = str(args.get("s3_key") or "")
    decision = str(args.get("decision") or "").lower()
    if decision not in {"approved", "rejected"}:
        return _err("decision must be approved or rejected")
    if not key.startswith(_approval_prefix()):
        return _err("s3_key must point at an approval record")

    bucket = _email_bucket()
    client = _s3()
    record = json.loads(client.get_object(Bucket=bucket, Key=key)["Body"].read().decode("utf-8"))
    record["status"] = decision
    record["decided_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    record["decided_by"] = str(args.get("decided_by") or "sales manager")
    client.put_object(Bucket=bucket, Key=key, Body=json.dumps(record, ensure_ascii=False).encode("utf-8"),
                      ContentType="application/json")
    return {"id": record.get("id"), "status": record["status"], "decided_at": record["decided_at"],
            "decided_by": record["decided_by"]}


def _quote_from_payload(payload: dict) -> Quote:
    """把 build_quote 的 JSON 还原成 Quote 对象。

    **不重新定价**：单价与合计直接沿用上游算好的值，
    重算会因字段不全而把已报价的行变成"算不出"（这是踩过的坑）。
    """
    rfq = CanonicalRFQ(
        rfq_no=str(payload.get("rfq_no", "")),
        customer=str(payload.get("customer", "")),
    )
    quote = Quote(rfq=rfq, quote_no=str(payload.get("quote_no") or f"Q-{rfq.rfq_no}"))

    for item in payload.get("lines") or []:
        line = CanonicalLine(
            part_no=str(item.get("part_no", "")),
            description=str(item.get("description", "")),
            material=str(item.get("material", "")),
            qty=item.get("qty"),
            refs=list(item.get("refs") or []),
            confidence=float(item.get("confidence") or 1.0),
            flags=list(item.get("flags") or []),
            field_confidence=dict(item.get("field_confidence") or {}),
        )
        traces = [
            Trace(rule=str(t.get("rule", "")), detail=str(t.get("detail", "")),
                  amount=float(t.get("amount") or 0.0), source=str(t.get("source", "")))
            for t in (item.get("trace_data") or [])
        ]
        quote.priced.append(PricedLine(
            line=line,
            unit_cost=float(item.get("unit_cost") or 0.0),
            base_price=float(item.get("list_price") or item.get("unit_price") or 0.0),
            discount_rate=float(item.get("discount_rate") or 0.0),
            unit_price=float(item.get("unit_price") or 0.0),
            line_total=float(item.get("line_total") or 0.0),
            trace=traces,
        ))

    for item in payload.get("held") or []:
        line = CanonicalLine(part_no=str(item.get("part_no", "")))
        quote.held.append(HeldLine(line, str(item.get("reason", "")), str(item.get("detail", ""))))

    approval = payload.get("approval") or {}
    quote.approval = Approval(
        required=bool(approval.get("required")),
        reasons=list(approval.get("reasons") or []),
    )
    return quote


def _upload_pdf(data: bytes, quote_no: str, suffix: str = "") -> dict:
    """把 PDF 上传到 S3 并返回预签名链接。"""
    bucket = os.environ.get("PDF_BUCKET")
    if not bucket:
        import base64

        return {"pdf_base64": base64.b64encode(data).decode("ascii"), "bytes": len(data),
                "note": "PDF_BUCKET not configured; returned base64"}

    import boto3

    key = f"quotes/{quote_no}{suffix}-{uuid.uuid4().hex[:6]}.pdf"
    client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-southeast-2"))
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/pdf")
    url = client.generate_presigned_url("get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600)
    return {"pdf_url": url, "s3_key": key, "bytes": len(data), "quote_no": quote_no}


def tool_render_review_pdf(args: dict) -> dict:
    """报价 → 人工复核清单 PDF（标记 / 理由 / 审批状态 / 溯源）。"""
    import tempfile
    from pathlib import Path

    from .quote.render import render_review_pdf

    payload = args.get("quote") or args
    quote = _quote_from_payload(payload)
    status = str(args.get("approval_status") or "not_required")

    tmp_path = Path(tempfile.gettempdir()) / f"{quote.quote_no}-review-{uuid.uuid4().hex[:8]}.pdf"
    render_review_pdf(quote, tmp_path, approval_status=status)
    data = tmp_path.read_bytes()
    tmp_path.unlink(missing_ok=True)

    result = _upload_pdf(data, quote.quote_no, suffix="-review")
    result["approval_status"] = status
    return result


def tool_get_prices(args: dict) -> dict:
    """把现在生效的价格表、机时费率、表面处理、毛利与折扣规则原样返回。

    单一事实来源：这个页面显示的就是定价代码里用的常量，
    改了 pricing.py 页面就跟着变，不存在两份价格表。
    """
    from .quote.pricing import (
        APPROVAL_TOTAL_THRESHOLD,
        DISCOUNT_TIERS,
        FINISH_PRICE,
        MACHINE_TIERS,
        MARGIN,
        MATERIAL_PRICE,
        POLICY_MAX_DISCOUNT,
        SETUP_PER_LINE,
    )

    return {
        "currency": "MYR",
        "materials": [
            {"material": name, "price_per_kg": price}
            for name, price in sorted(MATERIAL_PRICE.items())
        ],
        "machine_rates": [
            {"process": name, "tolerance_upto_mm": upper, "rate_per_min": rate}
            for _lower, upper, name, rate in MACHINE_TIERS
        ],
        "finishes": [{"finish": name, "price_per_piece": price} for name, price in sorted(FINISH_PRICE.items())],
        "setup_per_line": SETUP_PER_LINE,
        "margin": MARGIN,
        "discount_tiers": [{"from_qty": qty, "rate": rate} for qty, rate in DISCOUNT_TIERS],
        "approval_threshold_myr": APPROVAL_TOTAL_THRESHOLD,
        "policy_max_discount": POLICY_MAX_DISCOUNT,
    }


def tool_quote_email(args: dict) -> dict:
    """一封邮件 → 完整报价（mode 控制只用正文 / 只用附件 / 两者）。"""
    return _quote_email(args)


def _install_value_interpreter() -> None:
    """P2：默认开启，LLM_VALUES=0 关闭。"""
    from .quote import normalise

    if os.environ.get("LLM_VALUES") == "0":
        normalise.set_value_interpreter(None)
        return

    from .llm import complete_json
    from .quote.values import interpret_with_model

    normalise.set_value_interpreter(
        lambda text, kind: interpret_with_model(text, kind, lambda p: complete_json(p, purpose="values"))
    )


def _mapping_mapper():
    """P1：表头认不出来时的结构映射（默认开启，LLM_MAPPING=0 关闭）。"""
    if os.environ.get("LLM_MAPPING") == "0":
        return None

    from .llm import complete_json
    from .parsers.mapping_cache import default_cache
    from .parsers.table_mapper import map_columns

    cache = default_cache()

    def mapper(rows):
        return map_columns(rows, llm=lambda prompt: complete_json(prompt, purpose="mapping"), cache=cache)

    return mapper


def _conflict_notes(conflicts):
    """P3：默认开启，LLM_ARBITRATION=0 关闭（只给建议，不改数）。"""
    if os.environ.get("LLM_ARBITRATION") == "0" or not conflicts:
        return []

    from .llm import complete_json
    from .quote.arbitration import annotate

    try:
        return annotate(conflicts, lambda p: complete_json(p, purpose="arbitration"))
    except Exception:  # noqa: BLE001
        return []


def tool_render_reply(args: dict) -> dict:
    """报价 → 英文回信草稿 + 纯文本报价单。"""
    quote = _quote_from_payload(args.get("quote") or args)
    return {"reply_email": render_reply_email(quote), "quote_text": render_text(quote)}


def tool_render_quote_pdf(args: dict) -> dict:
    """报价 → PDF 文件。写进 S3，返回可点击的预签名链接。

    为什么用 S3 + 预签名：MCP 工具返回的是文本，不能直接回传二进制。
    写文件到 /tmp 再上传，链接 1 小时有效。
    """
    import base64
    import tempfile

    payload = args.get("quote") or args
    quote = _quote_from_payload(payload)

    tmp_path = os.path.join(tempfile.gettempdir(), f"{quote.quote_no}-{uuid.uuid4().hex[:8]}.pdf")
    render_quote_pdf(quote, tmp_path)
    with open(tmp_path, "rb") as handle:
        data = handle.read()
    os.remove(tmp_path)

    bucket = os.environ.get("PDF_BUCKET")
    if not bucket:
        # 没有配置桶：退回 base64，调用方自己存
        return {"pdf_base64": base64.b64encode(data).decode("ascii"), "bytes": len(data),
                "note": "PDF_BUCKET not configured; returned base64"}

    import boto3

    key = f"quotes/{quote.quote_no}-{uuid.uuid4().hex[:6]}.pdf"
    client = boto3.client("s3", region_name=os.environ.get("AWS_REGION", "ap-southeast-2"))
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/pdf")
    url = client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=3600
    )
    return {"pdf_url": url, "s3_key": key, "bytes": len(data), "quote_no": quote.quote_no}


TOOLS = {
    "price_line": tool_price_line,
    "build_quote": tool_build_quote,
    "render_reply": tool_render_reply,
    "render_quote_pdf": tool_render_quote_pdf,
    "list_emails": tool_list_emails,
    "quote_email": tool_quote_email,
    "preview_attachments": tool_preview_attachments,
    "read_email": tool_read_email,
    "reprice_quote": tool_reprice_quote,
    "submit_approval": tool_submit_approval,
    "list_approvals": tool_list_approvals,
    "decide_approval": tool_decide_approval,
    "render_review_pdf": tool_render_review_pdf,
    "get_prices": tool_get_prices,
}


def handler(event: dict, context: Any = None) -> dict:
    """AWS Lambda 入口。"""
    if isinstance(event, str):
        try:
            event = json.loads(event)
        except json.JSONDecodeError:
            return _err("event is not JSON")

    tool, args = _extract_call(event or {})
    if not tool:
        return _ok({"tools": sorted(TOOLS)})
    func = TOOLS.get(tool)
    if func is None:
        return _err(f"unknown tool: {tool} (available: {', '.join(sorted(TOOLS))})")

    try:
        return _ok(func(args))
    except Exception as exc:  # 工具失败要明确回错误，不要静默
        return _err(f"{type(exc).__name__}: {exc}")
