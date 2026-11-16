"""手机提词页重做：恢复横屏 + 难词加中文拟声（可开关）。

- 横屏：@media (orientation: landscape) + ⛶ 按钮（全屏并尝试锁定横屏）
- 读音：难词用 <ruby> 标注中文拟声，底部「读音」按钮可开关
"""

from __future__ import annotations

import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"D:\pythoncode\axrail-quotation-agent")
SOURCE = ROOT / "docs" / "demo-script.final.md"
OUT = ROOT / "docs" / "prompter-phone.html"

CJK = re.compile(r"[\u4e00-\u9fff]")

# 难词 → 中文拟声（只帮助开口，重音用大写标）
PRON = {
    "py": "P-Y 两个字母",
    "MCP": "EM-SEE-PEE",
    "IAM": "AI-EM",
    "S3": "ES-THREE",
    "PDF": "PEE-DEE-EF",
    "RFQ": "AR-EF-CUE",
    "UI": "YU-I",
    "twenty-five": "TWEN-ti-faiv",
    "underneath": "UN-der-neeth",
    "attachment": "uh-TACH-ment",
    "attachments": "uh-TACH-ments",
    "customer's": "KUS-tuh-merz",
    "deliverables": "di-LIV-er-uh-bulz",
    "disagreement": "dis-uh-GREE-ment",
    "engineering": "en-ji-NEER-ing",
    "everything": "EV-ri-thing",
    "extraction": "ik-STRAK-shun",
    "interpretation": "in-tuh-pri-TEI-shun",
    "milliseconds": "MI-li-sek-unds",
    "mixed-format": "MIKST-FOR-mat",
    "multi-source": "MUL-ti-SORS",
    "navigation": "na-vi-GEI-shun",
    "observability": "ub-zer-vuh-BIL-uh-ti",
    "production": "pruh-DUK-shun",
    "recomputes": "ree-kum-PYOOts",
    "references": "REF-er-en-siz",
    "regenerates": "ree-JEN-er-eits",
    "requirement": "ri-KWAI-er-ment",
    "straight-line": "STREIT-LAIN",
    "themselves": "them-SELVZ",
    "architecture": "AA-ki-tek-cher",
    "architect": "AA-ki-tekt",
    "quotation": "阔-TEI-神",
    "estimator": "ES-ti-mei-ter",
    "legwork": "LEG-werk",
    "orchestration": "哦-kis-TREI-神",
    "arithmetic": "呃-RITH-muh-tik",
    "ingest": "in-JEST",
    "normalise": "NO-muh-laiz",
    "confidence": "KON-fi-dens",
    "arbitration": "啊-bi-TREI-神",
    "tolerance": "TOL-er-ens",
    "procurement": "pruh-KYOO-ment",
    "deterministic": "di-tuh-muh-NIS-tik",
    "authoritative": "aw-THO-ri-tuh-tiv",
    "artefacts": "AA-ti-fakts",
    "capabilities": "kei-puh-BIL-uh-tiz",
    "interpreter": "in-TUH-pri-ter",
    "infrastructure": "IN-fruh-struk-cher",
    "assumption": "uh-SUMP-shun",
    "traceability": "trei-suh-BIL-uh-ti",
    "aluminium": "a-lyuh-MIN-ee-um",
    "titanium": "ti-TEI-nee-um",
    "stainless": "STEIN-les",
    "anodise": "A-nuh-daiz",
    "millimetre": "MI-li-mee-ter",
    "machining": "muh-SHEE-ning",
    "margin": "MAA-jin",
    "threshold": "THRESH-old",
    "spreadsheet": "SPRED-sheet",
    "sub-agents": "sub-EI-jents",
    "checkpointer": "CHECK-point-er",
    "webhook": "WEB-hook",
    "confidence": "KON-fi-dens",
}

PATTERN_CACHE: re.Pattern[str] | None = None


def annotate(text: str) -> str:
    """把难词包成 <ruby>词<rt>拟声</rt></ruby>。"""
    global PATTERN_CACHE
    if PATTERN_CACHE is None:
        words = sorted(PRON, key=len, reverse=True)
        PATTERN_CACHE = re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I)

    def replace(match: re.Match) -> str:
        word = match.group(0)
        hint = PRON.get(word.lower())
        if not hint:
            return word
        # 用括号小字，兼容所有手机浏览器（ruby 在部分 WebView 里会挤成一行）
        return f'{word}<span class="hint"> ({hint})</span>'

    return PATTERN_CACHE.sub(replace, text)


def collect() -> list[tuple[str, str, str]]:
    items: list[tuple[str, str, str]] = []
    heading = "Opening"
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        value = " ".join(buffer).strip()
        buffer = []
        if not value:
            return
        if CJK.search(value):
            if items and items[-1][2] == "":
                section, english, _ = items[-1]
                items[-1] = (section, english, value)
            else:
                items.append((heading, "", value))
        else:
            items.append((heading, value, ""))

    for raw in SOURCE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## ") or line.startswith("### "):
            flush()
            heading = line.lstrip("# ").strip()
            continue
        if line.startswith("> "):
            buffer.append(line[2:].strip())
        else:
            flush()
    flush()
    return items


def build(items: list[tuple[str, str, str]]) -> str:
    blocks: list[str] = []
    for section, english, chinese in items:
        parts = ['<section class="beat">', f'<div class="sec">{section}</div>']
        if english:
            parts.append(f'<p class="en">{annotate(english)}</p>')
        if chinese:
            parts.append(f'<p class="zh">{chinese}</p>')
        parts.append("</section>")
        blocks.append("".join(parts))
    content = "\n".join(blocks)

    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Prompter</title>
<style>
  :root {{ --en: 26px; --zh: 18px; }}
  * {{ box-sizing: border-box; -webkit-tap-highlight-color: transparent; }}
  html, body {{ margin:0; padding:0; background:#0d1219; color:#eef4fa;
                font-family:-apple-system,"Segoe UI",Roboto,sans-serif; }}
  #doc {{ padding: 7vh 18px 46vh; }}
  .beat {{ margin-bottom: 24px; }}
  .sec {{ font-size: 11px; letter-spacing:.12em; text-transform:uppercase; color:#4d6478; margin-bottom:6px; }}
  .en {{ font-size: var(--en); line-height: 1.5; margin: 0 0 8px; font-weight: 600; }}
  .zh {{ font-size: var(--zh); line-height: 1.5; margin: 0; color:#8ba1b7; }}
  .hint {{ font-size: 0.62em; color:#c9a35a; font-weight: 400; letter-spacing:.02em; }}
  body.no-hint .hint {{ display: none; }}
  @media (orientation: landscape) {{
    :root {{ --en: 30px; --zh: 19px; }}
    #doc {{ padding: 5vh 5vw 40vh; }}
    .beat {{ margin-bottom: 18px; }}
  }}
  @media (orientation: landscape) and (max-height: 430px) {{
    :root {{ --en: 25px; --zh: 16px; }}
  }}
  #bar {{ position: fixed; left:0; right:0; bottom:0; display:flex; gap:7px; align-items:center;
          padding: 9px 12px calc(9px + env(safe-area-inset-bottom)); background:rgba(13,18,25,.96);
          border-top:1px solid #1b2836; }}
  #bar button {{ background:#1b2836; color:#cfe0f0; border:1px solid #2b3b4d; border-radius:10px;
                 padding:9px 10px; font-size:13.5px; }}
  #bar button:active {{ background:#26384b; }}
  #play {{ flex: 0 0 76px; font-size:14.5px; }}
  #speed {{ flex:1; }}
  #hint {{ position:fixed; top:8px; left:0; right:0; text-align:center; font-size:11px;
           color:#4d6478; pointer-events:none; }}
</style></head><body>
<div id="hint">▶ 开始自动滚动 · 按住屏幕暂停 · ⛶ 横屏</div>
<div id="doc">
{content}
</div>
<div id="bar">
  <button id="play">▶ 开始</button>
  <button id="slower">慢</button>
  <input id="speed" type="range" min="6" max="60" value="20" step="1">
  <button id="faster">快</button>
  <button id="pron">读音</button>
  <button id="full">⛶</button>
  <button id="top">↑</button>
</div>
<script>
let playing = false, speed = 20, last = 0, pos = 0;
const playBtn = document.getElementById('play');
const slider = document.getElementById('speed');

function tick(now) {{
  if (!last) last = now;
  const dt = (now - last) / 1000;
  last = now;
  if (playing) {{
    pos += speed * dt;
    window.scrollTo(0, pos);
    if (pos + window.innerHeight >= document.body.scrollHeight - 4) {{
      playing = false;
      playBtn.textContent = '▶ 开始';
    }}
  }}
  requestAnimationFrame(tick);
}}
requestAnimationFrame(tick);

function toggle() {{
  playing = !playing;
  last = 0;
  pos = window.scrollY;
  playBtn.textContent = playing ? '⏸ 暂停' : '▶ 开始';
}}
playBtn.onclick = toggle;
document.getElementById('slower').onclick = () => {{ speed = Math.max(6, speed - 4); slider.value = speed; }};
document.getElementById('faster').onclick = () => {{ speed = Math.min(60, speed + 4); slider.value = speed; }};
document.getElementById('top').onclick = () => {{ pos = 0; window.scrollTo(0, 0); }};
slider.oninput = () => {{ speed = Number(slider.value); }};
document.getElementById('pron').onclick = (event) => {{
  document.body.classList.toggle('no-hint');
  event.target.textContent = document.body.classList.contains('no-hint') ? '读音' : '隐读音';
}};
document.getElementById('full').onclick = async () => {{
  try {{
    if (!document.fullscreenElement) {{
      await document.documentElement.requestFullscreen();
    }}
    if (screen.orientation && screen.orientation.lock) {{
      await screen.orientation.lock('landscape');
    }}
  }} catch (err) {{
    document.getElementById('hint').textContent = '请关闭手机的旋转锁定，再点 ⛶';
  }}
}};
window.addEventListener('scroll', () => {{ if (!playing) pos = window.scrollY; }});
document.getElementById('doc').addEventListener('touchstart', () => {{
  if (playing) {{ playing = false; playBtn.textContent = '▶ 继续'; }}
}});
</script>
</body></html>
"""


if __name__ == "__main__":
    items = collect()
    OUT.write_text(build(items), encoding="utf-8")
    words = sum(len((en or "").split()) for _s, en, _c in items)
    hints = sum(1 for _s, en, _c in items if en and "<ruby>" in annotate(en))
    print(f"{OUT.name}: {len(items)} paragraphs, {words} words, {hints} paragraphs with hints, {OUT.stat().st_size // 1024} KB")
