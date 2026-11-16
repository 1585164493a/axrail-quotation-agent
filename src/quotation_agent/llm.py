"""模型抽取：可在 Bedrock 与 OpenAI 兼容端点之间切换。

- `LLM_PROVIDER=bedrock`：Bedrock Converse（需要账号 allowlist）
- `LLM_PROVIDER=openai`：任何 OpenAI 兼容端点（DeepSeek、通义、本地 Ollama…）

密钥只从环境变量读，代码里不留任何 token：
    LLM_API_KEY / LLM_BASE_URL / LLM_MODEL

模型只做"照抄原文里的字段"，不允许计算、不允许补全缺失值。
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

DEFAULT_BEDROCK_MODEL = os.environ.get("EXTRACT_MODEL", "amazon.nova-micro-v1:0")
DEFAULT_OPENAI_BASE = os.environ.get("LLM_BASE_URL", "https://api.deepseek.com/v1")
DEFAULT_OPENAI_MODEL = os.environ.get("LLM_MODEL", "deepseek-chat")

PROMPT = """Extract the machined part lines from this customer RFQ email.

Rules:
- Copy values exactly as written. Do not calculate or convert anything.
- If a value is not stated (for example quantity "to follow"), use null.
- Never invent a part number, a quantity or a tolerance.

Return JSON only, in this exact shape:
{"lines":[{"part_no":"BRK-100","description":"...","material":"AL6061","qty":500,"tol_mm":0.1,"mass_kg":0.4,"cycle_min":6,"finish":"anodise"}]}

Email:
---
{body}
---
"""



def bedrock_extract_lines(body_text: str, model_id: str | None = None, region: str | None = None) -> list[dict]:
    """调 Bedrock Converse，返回结构化行列表。"""
    import boto3  # 延迟导入：不用 Bedrock 时不需要它

    schema = {
        "type": "object",
        "properties": {
            "lines": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "part_no": {"type": "string"},
                        "description": {"type": "string"},
                        "material": {"type": "string"},
                        "qty": {"type": ["integer", "null"]},
                        "tol_mm": {"type": ["number", "null"]},
                        "mass_kg": {"type": ["number", "null"]},
                        "cycle_min": {"type": ["number", "null"]},
                        "finish": {"type": "string"},
                        "evidence": {"type": "string"},
                    },
                    "required": ["part_no", "material"],
                },
            },
            "missing": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["lines"],
    }

    client = boto3.client("bedrock-runtime", region_name=region or os.environ.get("AWS_REGION", "ap-southeast-2"))
    response = client.converse(
        modelId=model_id or DEFAULT_BEDROCK_MODEL,
        messages=[{"role": "user", "content": [{"text": PROMPT.replace("{body}", body_text)}]}],
        inferenceConfig={"maxTokens": 1500, "temperature": 0},
        toolConfig={"tools": [{"toolSpec": {
            "name": "emit_rfq_lines",
            "description": "Return the extracted RFQ lines",
            "inputSchema": {"json": schema},
        }}]},
    )

    for block in response["output"]["message"]["content"]:
        if "toolUse" in block:
            payload = block["toolUse"]["input"]
            if isinstance(payload, str):
                payload = json.loads(payload)
            return payload.get("lines", [])
    return []


# ------------------------------------------------- OpenAI 兼容（DeepSeek 等）

def openai_extract_lines(
    body_text: str,
    base_url: str | None = None,
    model: str | None = None,
    api_key: str | None = None,
    timeout: int = 60,
) -> list[dict]:
    """调 OpenAI 兼容的 /chat/completions，返回结构化行列表。

    密钥只从参数或环境变量 `LLM_API_KEY` 取，不落盘、不进代码。
    """
    key = api_key or os.environ.get("LLM_API_KEY")
    if not key:
        raise RuntimeError("LLM_API_KEY is not set")

    url = (base_url or DEFAULT_OPENAI_BASE).rstrip("/") + "/chat/completions"
    body = {
        "model": model or DEFAULT_OPENAI_MODEL,
        "messages": [{"role": "user", "content": PROMPT.replace("{body}", body_text)}],
        "temperature": 0,
        "max_tokens": 1500,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise RuntimeError(f"model endpoint returned {exc.code}: {detail}") from exc

    content = payload["choices"][0]["message"]["content"]
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            # 有些端点会把 JSON 包在 ```json 里
            start, end = content.find("{"), content.rfind("}")
            content = json.loads(content[start:end + 1]) if start >= 0 else {"lines": []}
    return content.get("lines", [])


# ------------------------------------------------------------------ 用量统计

_USAGE: dict[str, int] = {}


def reset_usage() -> None:
    """每次报价开始前清零。"""
    _USAGE.clear()


def _record(purpose: str) -> None:
    _USAGE[purpose] = _USAGE.get(purpose, 0) + 1


def usage_snapshot() -> dict:
    """给响应体用：这次用没用到模型、用在哪一步。"""
    return {"calls": sum(_USAGE.values()), "by_purpose": dict(_USAGE)}


# ------------------------------------------------------------------ 统一入口

_KEY_CACHE: dict[str, str] = {}


def _api_key() -> str | None:
    """取密钥：环境变量优先，其次 SSM Parameter Store（加密参数）。

    密钥不进代码、不进镜像；SSM 那条路适合云端，环境变量那条适合本机。
    """
    key = os.environ.get("LLM_API_KEY")
    if key:
        return key

    param = os.environ.get("LLM_KEY_PARAM")
    if not param:
        return None
    if param in _KEY_CACHE:
        return _KEY_CACHE[param]

    import boto3  # 延迟导入

    client = boto3.client("ssm", region_name=os.environ.get("AWS_REGION", "ap-southeast-2"))
    value = client.get_parameter(Name=param, WithDecryption=True)["Parameter"]["Value"]
    _KEY_CACHE[param] = value
    return value


def complete_json(prompt: str, max_tokens: int = 800, purpose: str = "aux") -> str:
    """一次纯文本补全（要求返回 JSON），给结构映射/值解释这类辅助步骤用。

    purpose 只用于统计：body / mapping / values / arbitration。
    """
    _record(purpose)
    provider = (os.environ.get("LLM_PROVIDER") or "").lower()
    if not provider:
        provider = "openai" if (_api_key() or os.environ.get("LLM_KEY_PARAM")) else "bedrock"

    if provider == "openai":
        return _openai_complete(prompt, max_tokens)
    if provider == "bedrock":
        return _bedrock_complete(prompt, max_tokens)
    raise RuntimeError(f"unknown LLM_PROVIDER: {provider}")


def _openai_complete(prompt: str, max_tokens: int) -> str:
    import urllib.error
    import urllib.request

    key = _api_key()
    if not key:
        raise RuntimeError("LLM_API_KEY is not set")

    url = (os.environ.get("LLM_BASE_URL") or DEFAULT_OPENAI_BASE).rstrip("/") + "/chat/completions"
    body = {
        "model": os.environ.get("LLM_MODEL") or DEFAULT_OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:200]
        raise RuntimeError(f"model endpoint returned {exc.code}: {detail}") from exc
    return payload["choices"][0]["message"]["content"]


def _bedrock_complete(prompt: str, max_tokens: int) -> str:
    import boto3

    client = boto3.client("bedrock-runtime", region_name=os.environ.get("AWS_REGION", "ap-southeast-2"))
    response = client.converse(
        modelId=DEFAULT_BEDROCK_MODEL,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
        inferenceConfig={"maxTokens": max_tokens, "temperature": 0},
    )
    return response["output"]["message"]["content"][0]["text"]


def extract_lines(body_text: str) -> list[dict]:
    """按 LLM_PROVIDER 选择实现；默认优先 OpenAI 兼容（有 key 时），否则 Bedrock。"""
    _record("body")
    provider = os.environ.get("LLM_PROVIDER", "").lower()
    if not provider:
        provider = "openai" if (_api_key() or os.environ.get("LLM_KEY_PARAM")) else "bedrock"

    if provider == "openai":
        return openai_extract_lines(body_text, api_key=_api_key())
    if provider == "bedrock":
        return bedrock_extract_lines(body_text)
    raise RuntimeError(f"unknown LLM_PROVIDER: {provider}")
