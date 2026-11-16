"""生成提词器：每次只显示一段，空格翻页；可调字号、可打印。

为什么不用自动滚动：滚动速度永远对不上语速，眼睛还得追着找位置。
一段一屏，翻页由你控制，眼睛不移动。
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"D:\pythoncode\axrail-quotation-agent")
SOURCE = ROOT / "docs" / "demo-script.final.md"
OUT = ROOT / "docs" / "teleprompter.html"

CJK = re.compile(r"[\u4e00-\u9fff]")


def collect() -> list[tuple[str, str]]:
    """返回 [(所属标题, 口播句), ...]；每屏 1 句，短句最多合并到 26 词。"""
    blocks: list[tuple[str, str]] = []
    heading = "Opening"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if buffer:
            blocks.append((heading, " ".join(buffer)))
            buffer = []

    for raw in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## ") or line.startswith("### "):
            flush()
            heading = line.lstrip("# ").strip()
            continue
        if line.startswith("> "):
            value = line[2:].strip()
            if value and not CJK.search(value):
                buffer.append(value)
    flush()

    beats: list[tuple[str, str]] = []
    splitter = re.compile(r"(?<=[.!?])\s+")
    for section, paragraph in blocks:
        for sentence in splitter.split(paragraph):
            sentence = sentence.strip()
            if not sentence:
                continue
            if beats and beats[-1][0] == section and len((beats[-1][1] + " " + sentence).split()) <= 26:
                beats[-1] = (section, beats[-1][1] + " " + sentence)
            else:
                beats.append((section, sentence))
    return beats


def build(beats: list[tuple[str, str]], compact: bool = False) -> str:
    payload = ",\n".join(
        '{"s": %s, "t": %s}' % (repr(heading)[1:-1].replace('"', '\\"'), repr(text)[1:-1].replace('"', '\\"'))
        for heading, text in beats
    )
    body_class = " class=\"compact\"" if compact else ""
    payload = (
        "[\n"
        + ",\n".join(
            '{"s": "%s", "t": "%s"}' % (heading.replace('"', "'"), text.replace('"', "'"))
            for heading, text in beats
        )
        + "\n]"
    )

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Teleprompter</title>
<style>
  :root {{ --size: 44px; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; background:#0d1219; color:#eef4fa; font-family:"Segoe UI",Arial,sans-serif;
          display:flex; flex-direction:column; height:100vh; overflow:hidden; }}
  #top {{ display:flex; align-items:center; gap:14px; padding:12px 22px; background:#131c26;
          font-size:13px; color:#8ea4bb; border-bottom:1px solid #1e2c3b; }}
  #top b {{ color:#eef4fa; }}
  #top button {{ background:#1c2a39; color:#cfe0f0; border:1px solid #2c3d50; border-radius:6px;
                 padding:5px 11px; font-size:12.5px; cursor:pointer; }}
  #stage {{ flex:1; display:flex; flex-direction:column; justify-content:center; padding:0 9vw; }}
  #section {{ font-size:15px; letter-spacing:.1em; text-transform:uppercase; color:#5f88b5; margin-bottom:22px; }}
  #beat {{ font-size:var(--size); line-height:1.42; font-weight:500; }}
  #next {{ margin-top:34px; font-size:20px; color:#4a5f75; line-height:1.45; }}
  #bottom {{ padding:10px 22px; background:#131c26; color:#6d8299; font-size:12.5px;
             display:flex; justify-content:space-between; border-top:1px solid #1e2c3b; }}
  #bar {{ height:3px; background:#1c2a39; }}
  #barfill {{ height:3px; background:#2f6bff; width:0; transition:width .15s; }}
  body.compact #stage {{ padding:0; }}
  body.compact {{ }}
  body.compact #top {{ display:none; }}
  body.compact #bar {{ display:none; }}
  body.compact #stage {{
    position:fixed; left:0; right:0; bottom:0; height:118px;
    background:rgba(10,16,24,.82); backdrop-filter:blur(3px);
    padding:10px 26px; justify-content:center; border-top:1px solid #24374b;
  }}
  body.compact #section {{ display:none; }}
  body.compact #beat {{ font-size:26px; line-height:1.3; color:#eaf2fb; }}
  body.compact #next {{ display:none; }}
  body.compact #bottom {{
    position:fixed; right:14px; bottom:122px; padding:0; background:none; border:none;
    font-size:11.5px; color:#8ea4bb;
  }}
  body.compact #bottom #words {{ display:none; }}
  @media print {{
    body {{ background:#fff; color:#111; height:auto; overflow:visible; }}
    #top, #bottom, #next, #bar {{ display:none; }}
    #stage {{ padding:0; display:block; }}
    #beat {{ font-size:15pt; line-height:1.5; page-break-inside:avoid; margin-bottom:18pt; }}
    #section {{ color:#666; font-size:10pt; }}
  }}
</style></head><body{body_class}>
<div id="top">
  <b>Teleprompter</b>
  <span id="counter">1 / 1</span>
  <button id="prev">← Back (↑)</button>
  <button id="nextBtn">Next (space)</button>
  <button id="smaller">A−</button>
  <button id="bigger">A+</button>
  <span id="hint">space = next · ↑ = back · ←→ = font</span>
</div>
<div id="bar"><div id="barfill"></div></div>
<div id="stage">
  <div id="section"></div>
  <div id="beat"></div>
  <div id="next"></div>
</div>
<div id="bottom"><span id="left"></span><span id="words"></span></div>
<script>
const BEATS = {payload};
let index = 0;

function render() {{
  const beat = BEATS[index] || {{s: '', t: ''}};
  document.getElementById('section').textContent = beat.s;
  document.getElementById('beat').textContent = beat.t;
  document.getElementById('next').textContent = (BEATS[index + 1] || {{t: ''}}).t;
  document.getElementById('counter').textContent = (index + 1) + ' / ' + BEATS.length;
  document.getElementById('barfill').style.width = ((index + 1) / BEATS.length * 100).toFixed(1) + '%';
  const remaining = BEATS.slice(index).reduce((sum, b) => sum + b.t.split(' ').length, 0);
  document.getElementById('left').textContent = 'words left: ' + remaining + '  (~' + (remaining / 140).toFixed(1) + ' min)';
  document.getElementById('words').textContent = beat.t.split(' ').length + ' words';
}}
function go(delta) {{
  index = Math.min(BEATS.length - 1, Math.max(0, index + delta));
  render();
}}
function setSize(delta) {{
  const current = parseFloat(getComputedStyle(document.documentElement).getPropertyValue('--size'));
  document.documentElement.style.setProperty('--size', Math.min(72, Math.max(24, current + delta)) + 'px');
}}
document.getElementById('prev').onclick = () => go(-1);
document.getElementById('nextBtn').onclick = () => go(1);
document.getElementById('smaller').onclick = () => setSize(-4);
document.getElementById('bigger').onclick = () => setSize(4);
window.addEventListener('keydown', (event) => {{
  if (event.code === 'Space' || event.code === 'ArrowRight' && event.shiftKey) {{ event.preventDefault(); go(1); }}
  if (event.code === 'ArrowUp') {{ event.preventDefault(); go(-1); }}
  if (event.code === 'ArrowDown') {{ event.preventDefault(); go(1); }}
  if (event.code === 'ArrowLeft') {{ event.preventDefault(); setSize(-4); }}
  if (event.code === 'ArrowRight') {{ event.preventDefault(); setSize(4); }}
  if (event.code === 'Home') {{ event.preventDefault(); index = 0; render(); }}
}});
if (location.hash.indexOf('compact') >= 0 || location.search.indexOf('compact') >= 0) {{
  document.body.classList.add('compact');
}}
render();
</script>
</body></html>
"""


if __name__ == "__main__":
    beats = collect()
    OUT.write_text(build(beats), encoding="utf-8")
    OUT.with_name("teleprompter-compact.html").write_text(build(beats, compact=True), encoding="utf-8")
    words = sum(len(text.split()) for _, text in beats)
    print(f"{OUT.name}: {len(beats)} beats, {words} words (~{words / 140:.1f} min)")
    print("longest beat:", max((len(text) for _, text in beats), default=0), "chars")
