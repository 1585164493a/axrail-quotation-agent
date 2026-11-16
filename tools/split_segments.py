"""把逐字稿按录制段落切成中英对照的 txt（英文在上、中文在下）。

数据来源：docs/subtitles/demo.bilingual.srt —— 每条字幕就是一对 1:1 的中英文，
所以切出来的稿子天然对齐，不需要另外翻译。
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"D:\pythoncode\axrail-quotation-agent")
SRT = ROOT / "docs" / "subtitles" / "demo.bilingual.srt"
OUT = ROOT / "docs" / "segments"

CJK = re.compile(r"[\u4e00-\u9fff]")

# (文件名, 起始秒, 标题)
SEGMENTS = [
    ("seg1_architecture.txt", 0, "段 1 · 架构 + 两个必答题"),
    ("seg2_demo.txt", 93, "段 2 · 界面演示五步"),
    ("seg3_problems.txt", 300, "段 3 · 问题：决定 / 问人 / 假设"),
    ("seg4_cost_traces.txt", 420, "段 4 · 成本 / 追踪 / 改进"),
    ("seg5_closing.txt", 470, "段 5 · 收尾"),
]


def parse_srt(path: Path) -> list[tuple[float, str, str]]:
    """返回 [(开始秒, 英文, 中文)]。"""
    cues: list[tuple[float, str, str]] = []
    blocks = [b for b in path.read_text(encoding="utf-8").strip().split("\n\n") if b.strip()]
    for block in blocks:
        lines = block.splitlines()
        timing = lines[1]
        match = re.match(r"(\d\d):(\d\d):(\d\d)", timing)
        if not match:
            continue
        start = int(match.group(1)) * 3600 + int(match.group(2)) * 60 + int(match.group(3))
        body = lines[2:]
        first_cjk = next((i for i, line in enumerate(body) if CJK.search(line)), len(body))
        english = " ".join(body[:first_cjk]).strip()
        chinese = "".join(body[first_cjk:]).strip()
        cues.append((start, english, chinese))
    return cues


def main() -> None:
    cues = parse_srt(SRT)
    print("cues:", len(cues))
    OUT.mkdir(parents=True, exist_ok=True)

    for index, (filename, start_sec, title) in enumerate(SEGMENTS):
        end_sec = SEGMENTS[index + 1][1] if index + 1 < len(SEGMENTS) else 10**6
        picked = [cue for cue in cues if start_sec <= cue[0] < end_sec]
        if not picked:
            print(f"  ! {filename}: no cues in {start_sec}-{end_sec}")
            continue

        minutes, seconds = divmod(start_sec, 60)
        lines = [f"{title}   ({minutes}:{seconds:02d} 开始)", "=" * 60, ""]
        for number, (_start, english, chinese) in enumerate(picked, start=1):
            lines.append(f"[{number:02d}] {english}")
            lines.append(f"     中文：{chinese}")
            lines.append("")

        path = OUT / filename
        path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
        words = sum(len(english.split()) for _s, english, _c in picked)
        print(f"{filename}: {len(picked)} 句 · {words} 词 · ~{words / 140:.1f} min")


if __name__ == "__main__":
    main()
