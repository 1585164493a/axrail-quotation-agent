"""按实测语速（约 70 词/分钟）把整份脚本压缩到 ~600 词，并重排字幕。

旧稿 1021 词 → 实测 3 分钟只讲了第一段（211 词），因此按 70 wpm 重新配时长。
"""

import io
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

ROOT = Path(r"D:\pythoncode\axrail-quotation-agent")
MD = ROOT / "docs" / "demo-script.final.md"
SUB = ROOT / "tools" / "make_subtitles.py"

WPM = 70.0          # 实测语速
MIN_DUR = 3.5       # 单句最短秒数

# (英文, 中文, 分组)
BEATS: list[tuple[str, str, str]] = [
    # ── 架构 + 必答
    ("For the brief, I built one path from a mixed-format RFQ to a delivered quote.",
     "针对题目，我做了一条从多格式询价到报价交付的完整链路。", "arch"),
    ("Five layers: email into S3, Runtime runs agent dot py, Gateway exposes fourteen tools, the tools do the work, deliverables back to S3.",
     "五层：邮件进 S3，Runtime 跑 agent.py，Gateway 暴露十四个工具，工具干活，交付物回 S3。", "arch"),
    ("Inside the tools, eight steps from ingest to render — and the model only reads text. Everything else is code.",
     "工具里八步，从接入到交付；模型只读文字，其余全是代码。", "arch"),
    ("Question one: I use three. Runtime hosts the agent, Gateway exposes the fourteen tools with IAM auth, and Memory keeps state between calls.",
     "必答题一：我用三样。Runtime 托管 agent，Gateway 带 IAM 鉴权暴露十四个工具，Memory 保存调用之间的状态。", "q1"),
    ("Four I skip: Identity — one caller; Code Interpreter — prices stay pure; Browser — nothing to browse; deep tracing — logs are enough.",
     "另外四项不用：Identity（单调用方）、Code Interpreter（价格要纯函数）、Browser（没网页）、深度追踪（日志够用）。", "q1"),
    ("Question two: from my LangGraph stack I keep three things — visible flow, plain-function tools, and a human sign-off.",
     "必答题二：LangGraph 里我留三样——流程可见、工具是函数、有人点头。", "q2"),
    ("I replace hosting, my own MCP server and the Mongo checkpointer with Runtime, Gateway and Memory — and no framework, since the flow is straight.",
     "托管、自建 MCP、Mongo checkpointer 换成 Runtime、Gateway、Memory；链路是直的，不用框架。", "q2"),
    # ── 演示
    ("Let me run the sample RFQ. The front end is a small local UI, in tools ui py.",
     "演示样例 RFQ。前端是个本地小界面，代码在 tools/ui.py。", "demo"),
    ("I pick the email, tick what to read — body only first — and generate.", "选邮件，勾选要读的内容，先只勾正文，然后生成。", "demo"),
    ("Here are the lines and the suggested price. Click how for the pricing logic and the sources.",
     "这是提取出的行和建议价。点 how 看计算逻辑和出处。", "demo"),
    ("Click why for the confidence — the score is rules, the sentence is the model.",
     "点 why 看置信度——分数由规则算出，解释那句话是模型写的。", "demo"),
    ("Scroll to discount: sliding recomputes margin and quote. The email's requested discount goes to Needs sign-off, as a reference.",
     "往下是折扣：拖动即重算毛利率和报价；邮件里的期望折扣放进 Needs sign-off 作参考。", "demo"),
    ("Sliding also regenerates the PDF and the reply. Above policy, it cannot be approved directly — it routes to approval.",
     "拖动同时重新生成 PDF 和回信；超过政策线不能直接批，走审批。", "demo"),
    ("Five lines, but not all can be quoted: a held section explains each, and a conflicts box for multi-source disagreement.",
     "五行里不是每行都能报价：held 栏逐行解释，Conflicts 栏处理多源冲突。", "demo"),
    ("Generate at this discount produces the review list, the reply and the quotation PDF.",
     "点这个折扣生成，得到复核清单、回信和报价单 PDF。", "demo"),
    ("At the bottom, attachment previews and the original file; the top navigation has the other pages.",
     "最下面是附件预览和原件；顶部导航是其它页面。", "demo"),
    # ── 问题
    ("Now the problems — decided, asked, assumed.", "现在讲问题：它决定的、问人的、我假设的。", "prob"),
    ("Decided: quantity from the most authoritative document, discount from the tier, unpriceable lines held, policy breaches routed to approval.",
     "它决定的：数量取最权威文件，折扣按档位，算不出的挂起，越线自动进审批。", "prob"),
    ("Asked: the spacer's quantity, the titanium price and its tight tolerance, the drawing-versus-sheet conflict, and the fifteen percent discount.",
     "问人的：垫片数量、钛合金价格与超紧公差、图纸与表格的冲突、15% 折扣。", "prob"),
    ("Assumed — and the table shows it: twenty-five percent is a margin, not a markup; tiers apply per line; fifty thousand needs a manager; eight percent caps the discount; a missing value is held.",
     "假设都在表里：25% 是毛利率不是加价率；档位按行；五万要经理签字；8% 是折扣上限；缺失值挂起。", "prob"),
    # ── 成本与追踪
    ("Cost: this page reads CloudWatch live. One quote is about one fen — and the biggest item is Memory, not the model.",
     "成本：这页实时读 CloudWatch。一份约一分钱，最大项是 Memory，不是模型。", "cost"),
    ("Traces: left is every quote this session; right, the tool calls — which tool, how long, what went in and out.",
     "追踪：左边是本次会话每次报价；右边是工具调用——哪个工具、多久、输入输出。", "cost"),
    ("Below, the rule chain per line. Three things I would improve — each one is a gap, not a bug.",
     "下面是每行规则链。三件要改进的事——每件都是缺口，不是 bug。", "cost"),
    ("One: charts. OCR reads the labels on a drawing, but not the values plotted inside a bar or a curve — so a quantity that only exists in the chart is still invisible to me.",
     "一，图表。OCR 能读图纸上的标签，读不到柱状图或曲线里画出的数值——所以只存在于图里的数量，我现在看不到。", "cost"),
    ("Two: approvals. They land in a queue and someone can approve them in the page, but nobody gets an email — that needs SES, and it is the first thing I would wire next.",
     "二，审批。会进队列、页面上能批准，但没人收到邮件——需要 SES，是我接下来第一个要接的。", "cost"),
    ("Three: the confidence weights — ninety, seventy, sixty, forty-five — are my judgement, not learned; they should be fitted to labelled quotes.",
     "三，可信度权重——90/70/60/45——是我的判断不是学来的；应该用标注过的报价去拟合。", "cost"),
    # ── 收尾
    ("So: rules handle the documents, a person handles the rest, and I wrote down everything in between.",
     "一句话：文件里有的规则处理，没有的交给人，中间的全部写成假设。", "end"),
]


def duration_for(text: str) -> float:
    words = len(text.split())
    return max(MIN_DUR, round(words / WPM * 60, 1))


def build_sections() -> str:
    groups = {
        "arch": ("## 0:00–1:30 · 架构 + 两个必答题", "架构与必答题"),
        "q1": ("## 0:00–1:30 · 架构 + 两个必答题", ""),
        "q2": ("## 0:00–1:30 · 架构 + 两个必答题", ""),
        "demo": ("## 1:30–5:00 · 界面演示", "演示"),
        "prob": ("## 5:00–7:00 · 问题：决定 / 问人 / 假设", "问题"),
        "cost": ("## 7:00–8:30 · 成本 / 追踪 / 改进", "成本与追踪"),
        "end": ("## 收尾", "收尾"),
    }
    out: list[str] = []
    seen: set[str] = set()
    for english, chinese, group in BEATS:
        heading, _ = groups[group]
        if heading not in seen:
            out.append("")
            out.append(heading)
            out.append("")
            seen.add(heading)
        out.append(f"**EN**")
        out.append(f"> {english}")
        out.append("")
        out.append(f"**中文**")
        out.append(f"> {chinese}")
        out.append("")
    return "\n".join(out)


def build_cues() -> str:
    lines: list[str] = []
    for english, chinese, _group in BEATS:
        duration = duration_for(english)
        safe_en = english.replace('"', "'")
        safe_zh = chinese.replace('"', "'")
        lines.append(f'    ({duration}, "{safe_en}", "{safe_zh}", 0),')
    return "CUES: list[tuple[float, str, str, float]] = [\n" + "\n".join(lines) + "\n]\n"


HEADER = """# 录屏口播 · 定稿（按 70 词/分钟压缩）

> 实测语速约 70 词/分钟，所以全稿压到 ~480 词，念完约 7 分钟，留出操作时间。
> **英文是念出来的**，中文是同义对照。时间窗仍对齐：1:30 / 5:00 / 7:00。

"""


def main() -> None:
    MD.write_text(HEADER + build_sections(), encoding="utf-8")
    total_words = sum(len(english.split()) for english, _c, _g in BEATS)
    print(f"script: {len(BEATS)} beats, {total_words} words (~{total_words / WPM:.1f} min)")

    text = SUB.read_text(encoding="utf-8")
    start = text.index("CUES: list[")
    end = text.index("\n]\n", start) + len("\n]\n")
    SUB.write_text(text[:start] + build_cues() + text[end:], encoding="utf-8")
    print("CUES rewritten:", len(BEATS), "cues")


if __name__ == "__main__":
    main()
