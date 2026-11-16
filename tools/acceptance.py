"""交付前总验收：仓库、文档、代码、线上资源、演示素材，逐项打勾。"""

import io
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"D:\pythoncode\axrail-quotation-agent")
REMOTE = "https://github.com/1585164493a/axrail-quotation-agent"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(("PASS  " if ok else "FAIL  ") + name + (f"  · {detail}" if detail else ""))


def run(args: list[str], cwd: Path = ROOT) -> tuple[int, str]:
    proc = subprocess.run(args, cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


# ---------- 1. 仓库状态 ----------
print("\n== repo ==")
env_prefix = {"GIT_SSH": r"C:\Windows\System32\OpenSSH\ssh.exe"}
code, out = run(["git", "status", "--porcelain"])
check("working tree clean", out.strip() == "", out.strip()[:80])

code, out = run(["git", "log", "--oneline", "-1"])
check("has commits", code == 0, out.strip()[:60])

code, out = run(["git", "rev-parse", "HEAD"])
local = out.strip()
code, out = run(["git", "rev-parse", "origin/main"])
check("pushed to origin", local == out.strip(), f"{local[:8]} vs {out.strip()[:8]}")

code, out = run(["git", "ls-files"])
files = out.strip().splitlines()
check("tracked files", len(files) > 100, f"{len(files)} files")

big = []
for rel in files:
    path = ROOT / rel
    if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
        big.append(f"{rel} {path.stat().st_size // 1024 // 1024} MB")
check("no file over 2 MB", not big, "; ".join(big))

# ---------- 2. 关键文件 ----------
print("\n== files ==")
required = [
    "README.md", "README.zh.md", "pyproject.toml", "uv.lock", ".gitignore",
    "src/quotation_agent/lambda_handler.py", "agent_runtime/agent.py",
    "tools/ui.py", "tools/deploy_lambda.py", "tools/deploy_runtime.py",
    "docs/architecture.png", "docs/architecture.md", "docs/aws-deployment.md",
    "docs/gateway-tools.json", "docs/cost.md", "docs/walkthrough.md",
    "docs/db-schema.xlsx", "docs/transcript.md", "docs/submission-email.md",
    "docs/screenshots/01-workbench.png", "docs/screenshots/02-how-why.png",
    "docs/screenshots/03-cost.png", "docs/screenshots/04-traces.png",
]
missing = [rel for rel in required if not (ROOT / rel).exists()]
check("required files present", not missing, ", ".join(missing))

# ---------- 3. 测试 ----------
print("\n== tests ==")
code, out = run([str(ROOT / ".venv" / "Scripts" / "python.exe"), "-m", "unittest", "discover", "-s", "tests"])
tail = [line.strip() for line in out.splitlines() if line.startswith("Ran ") or line.strip() == "OK"]
check("test suite", code == 0, " | ".join(tail))

# ---------- 4. 文档一致性 ----------
print("\n== docs ==")
readme = (ROOT / "README.md").read_text(encoding="utf-8")
check("README has 5 required sections", all(marker in readme for marker in
      ["## Setup", "## Run the web UI", "## Tests", "## Known limits"]), "")
check("README mentions 178 tests", "178 tests" in readme)
check("README has screenshots", readme.count("docs/screenshots/") == 4)
check("README uses uv run", "uv run python" in readme)
check("demo-script.md removed", not (ROOT / "docs" / "demo-script.md").exists())

code, out = run([str(ROOT / ".venv" / "Scripts" / "python.exe"), r"D:\pythoncode\_axrail_notes\check_links.py"])
check("no broken local links", "no broken local links" in out, out.strip().splitlines()[-1] if out else "")

# ---------- 5. 线上资源 ----------
print("\n== aws ==")
try:
    import boto3

    session = boto3.Session(profile_name="aws", region_name="ap-southeast-2")
    control = session.client("bedrock-agentcore-control")
    runtimes = control.list_agent_runtimes().get("agentRuntimes", [])
    runtime = next((r for r in runtimes if r["agentRuntimeName"] == "quotation_agent"), None)
    check("runtime READY", bool(runtime) and runtime.get("status") == "READY",
          runtime.get("agentRuntimeId", "-") if runtime else "not found")

    gateway = control.get_gateway(gatewayIdentifier="quotation-agent-gw-boa2n2neqb")
    check("gateway available", gateway.get("status") in {"READY", "AVAILABLE"}, gateway.get("status", ""))

    lambda_client = session.client("lambda")
    function = lambda_client.get_function_configuration(FunctionName="quotation-agent-tools")
    check("lambda active", function.get("State") == "Active",
          f"{function.get('Runtime')} {function.get('LastModified', '')[:10]}")
except Exception as exc:  # noqa: BLE001
    check("aws resources", False, f"{type(exc).__name__}: {exc}"[:100])

# ---------- 6. 界面与报价 ----------
print("\n== live app ==")
try:
    for path, name in (("/", "workbench"), ("/inbox", "inbox"), ("/approvals", "approvals"),
                       ("/prices", "prices"), ("/cost", "cost"), ("/traces", "traces"),
                       ("/assumptions", "assumptions")):
        with urllib.request.urlopen("http://127.0.0.1:8765" + path, timeout=60) as response:
            check(f"page {path}", response.status == 200, name)

    payload = json.dumps({"email_key": "inbox/02_rfq_full_attachments.eml", "mode": "both"}).encode()
    request = urllib.request.Request("http://127.0.0.1:8765/api/quote", data=payload,
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=300) as response:
        quote = json.loads(response.read().decode())["quote"]
    check("quote reproduces 74,684", abs(quote["total"] - 74684.0) < 0.01, str(quote["total"]))
    check("3 priced / 2 held", len(quote["lines"]) == 3 and len(quote["held"]) == 2)
except Exception as exc:  # noqa: BLE001
    check("live app", False, f"{type(exc).__name__}: {exc}"[:100])

# ---------- 7. 远端可访问 ----------
print("\n== remote ==")
try:
    with urllib.request.urlopen("https://raw.githubusercontent.com/1585164493a/axrail-quotation-agent/main/README.md", timeout=60) as response:
        remote_readme = response.read().decode()
    check("remote README loads", response.status == 200, f"{len(remote_readme)} bytes")
    check("remote README has screenshots", remote_readme.count("docs/screenshots/") == 4)
except Exception as exc:  # noqa: BLE001
    check("remote README", False, f"{type(exc).__name__}: {exc}"[:100])

# ---------- 汇总 ----------
failed = [name for name, ok, _ in results if not ok]
print()
print(f"{len(results) - len(failed)}/{len(results)} checks passed")
if failed:
    print("not passing:")
    for name in failed:
        print("  -", name)
