"""录屏前的全面自检：凭证、界面、六页 JS、报价链路、追踪、文件齐备。

用法：python tools/preflight.py
"""

from __future__ import annotations

import io
import json
import re
import socket
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8765"
results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS " if ok else "FAIL "), name, ("· " + detail if detail else ""))


def get(path: str, timeout: int = 120) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(URL + path, timeout=timeout) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()
    except Exception as exc:  # noqa: BLE001
        return 0, f"{type(exc).__name__}: {exc}"


def post(path: str, payload: dict, timeout: int = 300) -> dict:
    request = urllib.request.Request(
        URL + path, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode())


# 1. 凭证
try:
    import boto3

    session = boto3.Session(profile_name="aws", region_name="ap-southeast-2")
    identity = session.client("sts").get_caller_identity()
    record("AWS credentials", True, identity["Arn"].split("/")[-2])
except Exception as exc:  # noqa: BLE001
    record("AWS credentials", False, f"{type(exc).__name__}: {exc}"[:100])

# 2. 界面在跑
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(1.0)
    up = sock.connect_ex(("127.0.0.1", 8765)) == 0
record("UI server on 8765", up, "python tools/ui.py" if not up else "")

# 3. 六个页面 + JS 语法
PAGES = ["/", "/inbox", "/approvals", "/prices", "/cost", "/traces"]
if up:
    for page in PAGES:
        status, html = get(page)
        ok = status == 200 and "<script>" in html
        if ok:
            match = re.search(r"<script>(.*?)</script>", html, re.S)
            temp = Path(r"D:\pythoncode\_pf.js")
            temp.write_text(match.group(1), encoding="utf-8", errors="replace")
            result = subprocess.run(["node", "--check", str(temp)], capture_output=True, text=True)
            ok = result.returncode == 0
        record(f"page {page}", ok, "" if ok else html[:80])

# 4. 收件箱
if up:
    status, body = get("/api/emails")
    try:
        emails = json.loads(body)
        names = [e["name"] for e in emails.get("emails", [])]
        record("inbox", len(names) >= 10, f"{len(names)} emails")
        for required in ("01_rfq_body_only.eml", "02_rfq_full_attachments.eml",
                         "rfq_prose_priced.eml", "20261116-scanned-request.eml",
                         "20261116-vendor-template.eml"):
            record(f"  has {required}", any(required in name for name in names))
    except Exception as exc:  # noqa: BLE001
        record("inbox", False, str(exc)[:80])

# 5. 报价链路
if up:
    try:
        data = post("/api/quote", {"email_key": "inbox/02_rfq_full_attachments.eml", "mode": "both"})
        quote = data["quote"]
        record("quote total 74684", abs(quote["total"] - 74684.0) < 0.01, str(quote["total"]))
        record("three priced lines", len(quote["lines"]) == 3, str(len(quote["lines"])))
        record("two held lines", len(quote["held"]) == 2, str([h["reason"] for h in quote["held"]]))
        cvr = next((l for l in quote["lines"] if l["part_no"] == "CVR-310"), {})
        record("CVR-310 conflict 0.30", abs(float(cvr.get("confidence", 0)) - 0.30) < 0.01, str(cvr.get("confidence")))
        record("quote PDF", bool(data.get("pdf_url")), str(data.get("pdf_bytes")) + " bytes")
        record("review PDF", bool(data.get("review_url")))
        record("reply draft", "Dear" in (data.get("reply_email") or ""))
        record("tool calls recorded", len(data.get("tool_calls") or []) >= 4, str(len(data.get("tool_calls") or [])))
    except Exception as exc:  # noqa: BLE001
        record("quote flow", False, f"{type(exc).__name__}: {exc}"[:120])

# 6. 折扣联动
if up:
    try:
        data = post("/api/quote", {"email_key": "inbox/02_rfq_full_attachments.eml", "mode": "both"})
        quote = data["quote"]
        repriced = post("/api/reprice", {"quote": quote, "discount_rate": 0.12})
        record("discount 12% lowers total", repriced["total"] < quote["total"],
               f"{quote['total']} -> {repriced['total']}")
        record("reply follows discount", bool(repriced.get("reply_email")))
        record("approval flags policy", any("8%" in r for r in (repriced.get("approval") or {}).get("reasons", [])))
    except Exception as exc:  # noqa: BLE001
        record("discount flow", False, str(exc)[:120])

# 7. 成本与追踪接口
if up:
    try:
        status, body = get("/api/costs")
        costs = json.loads(body)
        record("cost page data", status == 200 and costs.get("total_usd", 0) > 0,
               f"${costs.get('total_usd')} / quote")
    except Exception as exc:  # noqa: BLE001
        record("cost page data", False, str(exc)[:80])
    try:
        status, body = get("/api/traces")
        traces = json.loads(body)
        record("trace history", bool(traces.get("history")), f"{len(traces.get('history') or [])} entries")
        record("runtime logs", bool(traces.get("runtime")), f"{len(traces.get('runtime') or [])} runs")
    except Exception as exc:  # noqa: BLE001
        record("trace data", False, str(exc)[:80])

# 8. 录制素材
for rel in ("docs/architecture.png", "docs/transcript.md", "docs/prompter-phone.html",
            "docs/demo-script.final.md", "docs/segments/seg1_architecture.txt",
            "docs/segments/seg2_demo.txt", "docs/segments/seg3_problems.txt",
            "docs/segments/seg4_cost_traces.txt", "docs/segments/seg5_closing.txt"):
    path = ROOT / rel
    record(f"file {rel}", path.exists(), f"{path.stat().st_size // 1024} KB" if path.exists() else "")

# 汇总
failed = [name for name, ok, _ in results if not ok]
print()
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    print("needs fixing:")
    for name in failed:
        print("  -", name)
else:
    print("all checks passed - ready to record.")
