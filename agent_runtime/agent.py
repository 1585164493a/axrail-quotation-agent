"""AgentCore Runtime 上的 agent 入口。

职责：**编排**，不计算。
- 收到的请求（正文或已解析的块）交给 Gateway 上的 MCP 工具；
- 把状态写进 AgentCore Memory；
- 把工具返回的报价原样带回。

数字全部来自 Gateway 后面的 Lambda（同一套确定性定价代码），
这里没有一行算术——模型和 agent 都不产生价格。
"""

from __future__ import annotations

import json
import os
import urllib.request
import uuid

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from botocore.auth import SigV4Auth
from botocore.awsrequest import AWSRequest

REGION = os.environ.get("AWS_REGION", "ap-southeast-2")


def _gateway_url() -> str:
    """Gateway 的 MCP 端点；环境变量里可能已经带了 /mcp，别重复拼。"""
    base = (os.environ.get("GATEWAY_URL") or "").rstrip("/")
    if not base:
        raise RuntimeError("GATEWAY_URL is not set")
    return base if base.endswith("/mcp") else f"{base}/mcp"


GATEWAY_URL = _gateway_url()
MEMORY_ID = os.environ.get("MEMORY_ID", "")
ACTOR_ID = os.environ.get("ACTOR_ID", "estimator")

app = BedrockAgentCoreApp()


def _signed_post(url: str, payload: dict) -> dict:
    """用 SigV4 调 Gateway 的 MCP 端点。"""
    body = json.dumps(payload).encode("utf-8")
    request = AWSRequest(method="POST", url=url, data=body, headers={"Content-Type": "application/json"})
    credentials = boto3.Session().get_credentials().get_frozen_credentials()
    SigV4Auth(credentials, "bedrock-agentcore", REGION).add_auth(request)

    http_request = urllib.request.Request(url, data=body, headers=dict(request.headers))
    with urllib.request.urlopen(http_request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))


def list_tools() -> list[str]:
    response = _signed_post(
        GATEWAY_URL,
        {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "tools/list", "params": {}},
    )
    return [tool.get("name", "") for tool in (response.get("result") or {}).get("tools", [])]


def resolve_tool(name: str) -> str:
    """Gateway 会给工具名加上 target 前缀（tools___build_quote），这里按后缀对上。"""
    for available in list_tools():
        if available == name or available.endswith(f"___{name}"):
            return available
    return name


TOOL_CALLS: list[dict] = []  # 本次请求调过的工具，返回给 UI 做追踪


def _brief(value, depth: int = 0):
    """把任意结果压短：列表说条数，字典列前几个键，长文本给开头。"""
    if isinstance(value, list):
        return f"[{len(value)}]"
    if isinstance(value, dict):
        if depth >= 2:
            return "{" + ", ".join(list(value.keys())[:4]) + "}"
        pairs = [f"{k}={_brief(v, depth + 1)}" for k, v in list(value.items())[:6]]
        return "{" + ", ".join(pairs) + "}"
    if isinstance(value, str):
        return value if len(value) <= 60 else value[:59] + "…"
    return value


def _summarise(value, limit: int = 260) -> str:
    """把工具输入/输出压成一行，够看懂、又不刷屏。"""
    try:
        text = str(_brief(value))
    except Exception:  # noqa: BLE001
        text = str(value)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def call_tool(name: str, arguments: dict) -> dict:
    """调一个 MCP 工具，返回它解析后的结果；顺带记一次调用轨迹。"""
    import time as _time

    started = _time.time()
    response = _signed_post(
        GATEWAY_URL,
        {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "tools/call",
         "params": {"name": resolve_tool(name), "arguments": arguments}},
    )
    if "error" in response:
        raise RuntimeError(f"gateway error: {response['error']}")

    content = (response.get("result") or {}).get("content") or []
    for item in content:
        if item.get("type") == "text":
            parsed = json.loads(item["text"])
            # 兼容 Lambda 的旧信封形态 {"statusCode":..., "body": "..."}
            if isinstance(parsed, dict) and "body" in parsed and "statusCode" in parsed:
                body = parsed["body"]
                result = json.loads(body) if isinstance(body, str) else parsed
            else:
                result = parsed
            TOOL_CALLS.append({
                "tool": name,
                "ms": round((_time.time() - started) * 1000),
                "input": _summarise({k: v for k, v in arguments.items()
                                     if k not in {"quote", "blocks", "body_text"}}),
                "output": _summarise(result or {}),
                "keys": sorted((result or {}).keys())[:12],
            })
            return result
    return {}


def remember(session_id: str, state: str, detail: dict) -> None:
    """把状态推进写进 Memory（一个状态一条事件，不多写）。"""
    if not MEMORY_ID:
        return
    try:
        from datetime import datetime, timezone

        client = boto3.client("bedrock-agentcore", region_name=REGION)
        client.create_event(
            memoryId=MEMORY_ID,
            actorId=ACTOR_ID,
            sessionId=session_id,
            eventTimestamp=datetime.now(timezone.utc),
            payload=[{"conversational": {
                "role": "USER",
                "content": {"text": json.dumps({"state": state, **detail}, ensure_ascii=False)[:4000]},
            }}],
        )
    except Exception as exc:  # 记忆失败不能影响报价
        print(f"memory write skipped: {type(exc).__name__}: {exc}")


@app.entrypoint
def quote_agent(payload: dict) -> dict:
    """一次调用 = 一份报价。

    payload:
        session_id   续跑用；不给就新建
        email_key    S3 里的 .eml 路径（给了它就不用传正文）
        rfq_no, customer, body_text, blocks
    """
    session_id = payload.get("session_id") or f"sess-{uuid.uuid4().hex[:12]}"
    TOOL_CALLS.clear()
    email_key = payload.get("email_key", "")
    remember(session_id, "received", {"rfq_no": payload.get("rfq_no", ""), "email": email_key})

    # 只传调用方真正给了的字段：没给就让工具从邮件本身去读
    # （否则会把 "RFQ-UNKNOWN" 覆盖到邮件里解析出来的 RFQ 号上）
    arguments: dict = {}
    if payload.get("rfq_no"):
        arguments["rfq_no"] = payload["rfq_no"]
    if payload.get("customer"):
        arguments["customer"] = payload["customer"]

    if email_key:
        # 从 S3 读整封邮件；mode 决定只用正文 / 只用附件 / 两者都用
        arguments["key"] = email_key
        if payload.get("mode"):
            arguments["mode"] = payload["mode"]
        # UI 的勾选：正文 + 指定附件（给了就不看 mode）
        if payload.get("include_body") is not None:
            arguments["include_body"] = bool(payload["include_body"])
        if payload.get("include_attachments") is not None:
            arguments["include_attachments"] = list(payload["include_attachments"])
        quote = call_tool("quote_email", arguments)
    else:
        if payload.get("blocks"):
            arguments["blocks"] = payload["blocks"]
        if payload.get("body_text"):
            arguments["body_text"] = payload["body_text"]
        arguments.setdefault("rfq_no", "RFQ-UNKNOWN")
        quote = call_tool("build_quote", arguments)
    if quote.get("error"):
        # 工具直接报了错（比如什么都没勾）：别再往下渲染空报价
        return {"session_id": session_id, "error": str(quote["error"]), "quote": quote,
                "tool_calls": list(TOOL_CALLS)}

    remember(session_id, "priced", {"total": quote.get("total"), "lines": len(quote.get("lines", []))})

    reply = call_tool("render_reply", {"quote": quote})
    remember(session_id, "rendered", {"quote_no": f"Q-{quote.get('rfq_no') or arguments.get('rfq_no', '')}"})

    # PDF 交给工具生成（写进 S3，返回 1 小时有效的预签名链接）
    pdf = {}
    try:
        pdf = call_tool("render_quote_pdf", {"quote": quote, "output": "pdf"})
        remember(session_id, "pdf", {"key": pdf.get("s3_key", "")})
    except Exception as exc:  # PDF 失败不影响报价本身
        print(f"pdf skipped: {type(exc).__name__}: {exc}")

    # 人工复核清单（标记 / 理由 / 审批状态 / 溯源）
    review = {}
    try:
        status = "pending_manager" if (quote.get("approval") or {}).get("required") else "not_required"
        review = call_tool("render_review_pdf", {"quote": quote, "output": "review", "approval_status": status})
    except Exception as exc:
        print(f"review list skipped: {type(exc).__name__}: {exc}")

    return {
        "session_id": session_id,
        "tools": list_tools(),
        "quote": quote,
        "reply_email": reply.get("reply_email", ""),
        "quote_text": reply.get("quote_text", ""),
        "pdf_url": pdf.get("pdf_url", ""),
        "pdf_bytes": pdf.get("bytes", 0),
        "review_url": review.get("pdf_url", ""),
        "tool_calls": list(TOOL_CALLS),
    }


if __name__ == "__main__":
    app.run()
