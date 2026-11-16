"""从 PyPI 直接取 Linux 轮子，组装 Lambda 部署包（不依赖 pip 解析器）。

为什么不用 pip download --platform：在本机解析下来极慢（几分钟不动），
而我们要的东西是固定清单，直接按文件名挑轮子更快、更可控。

用法：python tools/package_lambda.py
"""

from __future__ import annotations

import json
import shutil
import ssl
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
STAGE = BUILD / "lambda"
WHEELS = BUILD / "wheels"
ZIP_PATH = BUILD / "quotation-agent-tools.zip"

PY = "cp312"
OS = "manylinux"

# 包名 -> 允许的轮子类型
PACKAGES = {
    "openpyxl": ["py3-none-any"],
    "et-xmlfile": ["py3-none-any"],
    "python-pptx": ["py3-none-any"],
    "python-docx": ["py3-none-any"],
    "pypdf": ["py3-none-any"],
    "typing-extensions": ["py3-none-any"],
    "XlsxWriter": ["py3-none-any"],
    "lxml": [f"{PY}-{OS}"],
    "pillow": [f"{PY}-{OS}"],
}

CTX = ssl.create_default_context()


def _fetch(url: str, timeout: int = 60) -> bytes:
    """带重试的下载：这台机器上 TLS 偶发 EOF，重试一次就好。"""
    import time

    last: Exception | None = None
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "python"})
            with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
                return r.read()
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"failed after retries: {url}: {last}")


def pick_wheel(files: list[dict], accept: list[str]) -> dict | None:
    for f in files:
        name = f["filename"]
        if not name.endswith(".whl"):
            continue
        if any(token in name for token in accept):
            if f"{PY}-{OS}" in accept and "x86_64" not in name:
                continue
            return f
    return None


def main() -> int:
    for d in (STAGE, WHEELS):
        if d.exists():
            shutil.rmtree(d)
        d.mkdir(parents=True)

    total = 0
    for package, accept in PACKAGES.items():
        meta = json.loads(_fetch(f"https://pypi.org/pypi/{package}/json"))
        wheel = pick_wheel(meta["urls"], accept)
        if wheel is None:
            print(f"  MISS {package} ({accept})")
            continue
        target = WHEELS / wheel["filename"]
        target.write_bytes(_fetch(wheel["url"], timeout=180))
        total += 1
        print(f"  {package:<20} {wheel['filename']}  {wheel['size'] // 1024} KB")

    for whl in WHEELS.glob("*.whl"):
        with zipfile.ZipFile(whl) as z:
            z.extractall(STAGE)

    # 我们的代码
    shutil.copytree(ROOT / "src" / "quotation_agent", STAGE / "quotation_agent")
    for junk in STAGE.rglob("__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)

    if ZIP_PATH.exists():
        ZIP_PATH.unlink()
    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as z:
        for path in STAGE.rglob("*"):
            if path.is_file():
                z.write(path, path.relative_to(STAGE))

    size_mb = ZIP_PATH.stat().st_size / 1024 / 1024
    print(f"\npackage: {ZIP_PATH}  ({size_mb:.1f} MB, {total} wheels)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
