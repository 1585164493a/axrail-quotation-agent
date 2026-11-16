"""录屏前的一键准备（分屏模式）。

左 70%：Edge 演示窗口（OBS 只采集它）
右 30%：记事本，打开当前段的中英逐字稿（不会被录进去）

用法：
    python tools/demo_ready.py --seg 2      # 准备第 2 段
    python tools/demo_ready.py              # 只做准备，不排列窗口
"""

from __future__ import annotations

import argparse
import ctypes
import io
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8765"
SEGMENTS = ROOT / "docs" / "segments"
PROFILE = os.environ.get("AWS_PROFILE", "aws")

SEGMENT_FILES = {
    1: "seg1_architecture.txt",
    2: "seg2_demo.txt",
    3: "seg3_problems.txt",
    4: "seg4_cost_traces.txt",
    5: "seg5_closing.txt",
}

user32 = ctypes.windll.user32


# ---------------------------------------------------------------- 窗口操作
def screen_size() -> tuple[int, int]:
    return user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)


def find_window(*keywords: str) -> int | None:
    """按标题关键字找第一个可见窗口。"""
    found: list[int] = []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def callback(hwnd, _lparam):
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return True
        buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buffer, length + 1)
        title = buffer.value.lower()
        if all(word.lower() in title for word in keywords):
            found.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return found[0] if found else None


def move_window(hwnd: int, x: int, y: int, width: int, height: int) -> None:
    user32.MoveWindow(hwnd, x, y, width, height, True)
    user32.SetForegroundWindow(hwnd)


def split_screen(segment: int | None, script_kind: str = "notepad") -> None:
    width, height = screen_size()
    browser = find_window("edge") or find_window("chrome")
    if not browser:
        print("  ! 没找到浏览器窗口，先手动打开演示页面再跑一次")
        return
    move_window(browser, 0, 0, int(width * 0.7), height)
    print(f"  browser -> 0,0 {int(width * 0.7)}x{height}")

    if segment is None:
        return

    script = SEGMENTS / SEGMENT_FILES.get(segment, "")
    if not script.exists():
        print(f"  ! 找不到稿子 {script.name}")
        return

    if script_kind == "edge":
        # 第二个浏览器窗口：--new-window 才会新开窗口，否则只是新标签
        subprocess.Popen(["cmd", "/c", "start", "", "msedge", "--new-window", script.as_uri()])
        time.sleep(3.0)
        notepad = find_window(script.name) or find_window(script.stem) or find_window(".txt")
    else:
        subprocess.Popen(["notepad.exe", str(script)])
        time.sleep(2.0)
        notepad = find_window(script.name) or find_window("notepad")
    if notepad:
        move_window(notepad, int(width * 0.7), 0, int(width * 0.3), height)
        print(f"  notepad -> {int(width * 0.7)},0 {int(width * 0.3)}x{height}  ({script.name})")
    else:
        print(f"  稿子已打开：{script}")

    # 最后把演示窗口提到前面：右侧稿子仍然可见，但焦点在浏览器上
    user32.ShowWindow(browser, 9)      # SW_RESTORE
    user32.BringWindowToTop(browser)
    user32.SetForegroundWindow(browser)


# ---------------------------------------------------------------- 环境准备
def port_open(port: int = 8765) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def check_credentials() -> bool:
    try:
        import boto3

        session = boto3.Session(profile_name=PROFILE,
                                region_name=os.environ.get("AWS_REGION", "ap-southeast-2"))
        identity = session.client("sts").get_caller_identity()
        print(f"  credentials OK: {identity['Arn'].split('/')[-2]}")
        return True
    except Exception as exc:  # noqa: BLE001
        print(f"  credentials FAILED: {type(exc).__name__}: {exc}")
        print("  -> aws login --region ap-southeast-2 --profile aws")
        return False


def start_ui() -> None:
    if port_open():
        print("  UI already running on 8765")
        return
    print("  starting tools/ui.py …")
    subprocess.Popen([sys.executable, str(ROOT / "tools" / "ui.py")], cwd=str(ROOT),
                     creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0))
    for _ in range(30):
        time.sleep(1)
        if port_open():
            print("  UI is up")
            return
    print("  UI did not come up in 30 s")


def warm_quote() -> None:
    payload = json.dumps({"email_key": "inbox/02_rfq_full_attachments.eml", "mode": "both"}).encode()
    request = urllib.request.Request(f"{URL}/api/quote", data=payload,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            quote = json.loads(response.read().decode())["quote"]
        print(f"  warm-up quote: total {quote['total']} · lines {len(quote['lines'])}")
    except Exception as exc:  # noqa: BLE001
        print(f"  warm-up failed: {type(exc).__name__}: {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a recording session (split screen)")
    parser.add_argument("--seg", type=int, choices=[1, 2, 3, 4, 5], help="which segment to show on the right")
    parser.add_argument("--arrange", action="store_true", help="move windows into a 70/30 split")
    parser.add_argument("--no-warm", action="store_true", help="skip the warm-up quote")
    parser.add_argument("--script", choices=["notepad", "edge"], default="notepad",
                        help="where to show the verbatim script: notepad or a second browser window")
    args = parser.parse_args()

    print("1) credentials")
    ok = check_credentials()

    print("2) UI server")
    start_ui()

    if not args.no_warm:
        print("3) warm-up quote (so /traces has history)")
        warm_quote()

    print("4) pages")
    for path in ("/inbox", "/"):
        webbrowser.open(URL + path)
        time.sleep(0.6)

    if args.arrange:
        print("5) split screen")
        split_screen(args.seg, args.script)
    else:
        print("5) layout: 不分屏（稿子在手机上）")

    print("\n录制清单")
    print("  OBS：窗口采集 → 选 Edge；画布 1920x1080；MKV；Ctrl+Shift+R 开始")
    print("  右侧记事本不会被录进去（只采集 Edge 窗口）")
    print("  手机提词页：docs/prompter-phone.html（发到微信文件传输助手，手机浏览器打开）")
    print("  按 Alt+Tab 切到 Edge —— Windows 不允许脚本抢焦点")
    print("  OBS 里把来源缩放滤镜设成 Lanczos，放大后文字更清晰")
    print("  关微信/QQ，开专注助手；每段开头留 2 秒静音")
    if not ok:
        print("\n!! 凭证无效，先 aws login")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
