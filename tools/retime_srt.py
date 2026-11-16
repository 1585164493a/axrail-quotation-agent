"""把字幕时间轴对齐到实际录制的视频。

两种用法：

1) 整体缩放（录制节奏和稿子差不多时）
   python tools/retime_srt.py --scale 1.18
   python tools/retime_srt.py --duration 9:40     # 直接给视频总长

2) 分段锚点（每段起点不一样时，最准）
   python tools/retime_srt.py --anchors 0=0,2:07=2:15,4:59=5:20,7:00=7:30,8:59=9:35
   左边是稿子里的时间，右边是视频里对应的时间。

输出：docs/subtitles/demo.retimed.srt（中英双语）
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"D:\pythoncode\axrail-quotation-agent")
SOURCE = ROOT / "docs" / "subtitles" / "demo.bilingual.srt"
OUT = ROOT / "docs" / "subtitles" / "demo.retimed.srt"

TIME = re.compile(r"(\d\d):(\d\d):(\d\d),(\d\d\d)")


def parse_time(text: str) -> float:
    match = TIME.match(text.strip())
    if not match:
        raise ValueError(f"bad time: {text}")
    h, m, s, ms = (int(value) for value in match.groups())
    return h * 3600 + m * 60 + s + ms / 1000


def format_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms == 1000:
        s += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse_clock(text: str) -> float:
    """0 / 2:07 / 1:02:07 都接受。"""
    parts = [float(p) for p in text.strip().split(":")] if text.strip() else []
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError(f"bad clock: {text}")


def build_mapper(anchors: list[tuple[float, float]], scale: float):
    anchors = sorted(anchors)

    def mapper(old: float) -> float:
        if not anchors:
            return old * scale
        if old <= anchors[0][0]:
            return old + (anchors[0][1] - anchors[0][0])
        for (old_a, new_a), (old_b, new_b) in zip(anchors, anchors[1:]):
            if old <= old_b:
                span_old = old_b - old_a
                if span_old <= 0:
                    return new_a
                ratio = (old - old_a) / span_old
                return new_a + ratio * (new_b - new_a)
        old_last, new_last = anchors[-1]
        return new_last + (old - old_last) * scale

    return mapper


def main() -> int:
    parser = argparse.ArgumentParser(description="Retime subtitles to the recorded video")
    parser.add_argument("--scale", type=float, default=1.0, help="uniform scale factor")
    parser.add_argument("--duration", help="video duration, e.g. 9:40 (computes scale)")
    parser.add_argument("--anchors", help="old=new pairs, e.g. 0=0,2:07=2:15,4:59=5:20")
    parser.add_argument("--source", default=str(SOURCE))
    parser.add_argument("--out", default=str(OUT))
    args = parser.parse_args()

    source = Path(args.source)
    blocks = [b for b in source.read_text(encoding="utf-8").strip().split("\n\n") if b.strip()]

    anchors: list[tuple[float, float]] = []
    if args.anchors:
        for pair in args.anchors.split(","):
            if not pair.strip():
                continue
            old_text, new_text = pair.split("=")
            anchors.append((parse_clock(old_text), parse_clock(new_text)))

    scale = args.scale
    if args.duration and not anchors:
        last_end = parse_time(blocks[-1].splitlines()[1].split("-->")[1])
        scale = parse_clock(args.duration) / last_end
        print(f"uniform scale {scale:.3f}")

    mapper = build_mapper(anchors, scale)
    out_lines: list[str] = []
    for index, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        start_text, end_text = lines[1].split("-->")
        body = lines[2:]
        new_start = mapper(parse_time(start_text))
        new_end = mapper(parse_time(end_text))
        if new_end <= new_start:
            new_end = new_start + 1.0
        out_lines.append(f"{index}\n{format_time(new_start)} --> {format_time(new_end)}\n" + "\n".join(body) + "\n")

    Path(args.out).write_text("\n".join(out_lines), encoding="utf-8")
    print(f"written: {args.out} ({len(blocks)} cues)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
