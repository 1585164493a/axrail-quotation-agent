"""生成双语字幕：含段落过渡句 + 生词表支撑的念稿。

时间轴对齐题目分镜：
  0:00–1:30  架构 + 两个必答题
  1:30–5:00  同一 RFQ 两种格式，同一报价 + PDF + 回信
  5:00–7:00  这份询价的问题：决定了什么 / 问了人什么 / 假设了什么
  7:00–8:00  成本 / 日志追踪 / 改进
  8:00–8:45  可选：兜底真的会触发
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

OUT = Path(r"D:\pythoncode\axrail-quotation-agent\docs\subtitles")

# (朗读秒数, 英文, 中文, 后面的留白秒数)
CUES: list[tuple[float, str, str, float]] = [
    (12.9, "For the brief, I built one path from a mixed-format RFQ to a delivered quote.", "针对题目，我做了一条从多格式询价到报价交付的完整链路。", 0),
    (19.7, "Five layers: email into S3, Runtime runs agent dot py, Gateway exposes fourteen tools, the tools do the work, deliverables back to S3.", "五层：邮件进 S3，Runtime 跑 agent.py，Gateway 暴露十四个工具，工具干活，交付物回 S3。", 0),
    (17.1, "Inside the tools, eight steps from ingest to render — and the model only reads text. Everything else is code.", "工具里八步，从接入到交付；模型只读文字，其余全是代码。", 0),
    (19.7, "Question one: I use three. Runtime hosts the agent, Gateway exposes the fourteen tools with IAM auth, and Memory keeps state between calls.", "必答题一：我用三样。Runtime 托管 agent，Gateway 带 IAM 鉴权暴露十四个工具，Memory 保存调用之间的状态。", 0),
    (20.6, "Four I skip: Identity — one caller; Code Interpreter — prices stay pure; Browser — nothing to browse; deep tracing — logs are enough.", "另外四项不用：Identity（单调用方）、Code Interpreter（价格要纯函数）、Browser（没网页）、深度追踪（日志够用）。", 0),
    (16.3, "Question two: from my LangGraph stack I keep three things — visible flow, plain-function tools, and a human sign-off.", "必答题二：LangGraph 里我留三样——流程可见、工具是函数、有人点头。", 0),
    (21.4, "I replace hosting, my own MCP server and the Mongo checkpointer with Runtime, Gateway and Memory — and no framework, since the flow is straight.", "托管、自建 MCP、Mongo checkpointer 换成 Runtime、Gateway、Memory；链路是直的，不用框架。", 0),
    (15.4, "Let me run the sample RFQ. The front end is a small local UI, in tools ui py.", "演示样例 RFQ。前端是个本地小界面，代码在 tools/ui.py。", 0),
    (12.9, "I pick the email, tick what to read — body only first — and generate.", "选邮件，勾选要读的内容，先只勾正文，然后生成。", 0),
    (14.6, "Here are the lines and the suggested price. Click how for the pricing logic and the sources.", "这是提取出的行和建议价。点 how 看计算逻辑和出处。", 0),
    (12.9, "Click why for the confidence — the score is rules, the sentence is the model.", "点 why 看置信度——分数由规则算出，解释那句话是模型写的。", 0),
    (16.3, "Scroll to discount: sliding recomputes margin and quote. The email's requested discount goes to Needs sign-off, as a reference.", "往下是折扣：拖动即重算毛利率和报价；邮件里的期望折扣放进 Needs sign-off 作参考。", 0),
    (17.1, "Sliding also regenerates the PDF and the reply. Above policy, it cannot be approved directly — it routes to approval.", "拖动同时重新生成 PDF 和回信；超过政策线不能直接批，走审批。", 0),
    (17.1, "Five lines, but not all can be quoted: a held section explains each, and a conflicts box for multi-source disagreement.", "五行里不是每行都能报价：held 栏逐行解释，Conflicts 栏处理多源冲突。", 0),
    (12, "Generate at this discount produces the review list, the reply and the quotation PDF.", "点这个折扣生成，得到复核清单、回信和报价单 PDF。", 0),
    (13.7, "At the bottom, attachment previews and the original file; the top navigation has the other pages.", "最下面是附件预览和原件；顶部导航是其它页面。", 40),
    (6, "Now the problems — decided, asked, assumed.", "现在讲问题：它决定的、问人的、我假设的。", 0),
    (16.3, "Decided: quantity from the most authoritative document, discount from the tier, unpriceable lines held, policy breaches routed to approval.", "它决定的：数量取最权威文件，折扣按档位，算不出的挂起，越线自动进审批。", 0),
    (16.3, "Asked: the spacer's quantity, the titanium price and its tight tolerance, the drawing-versus-sheet conflict, and the fifteen percent discount.", "问人的：垫片数量、钛合金价格与超紧公差、图纸与表格的冲突、15% 折扣。", 0),
    (29.1, "Assumed — and the table shows it: twenty-five percent is a margin, not a markup; tiers apply per line; fifty thousand needs a manager; eight percent caps the discount; a missing value is held.", "假设都在表里：25% 是毛利率不是加价率；档位按行；五万要经理签字；8% 是折扣上限；缺失值挂起。", 53),
    (18.9, "Cost: this page reads CloudWatch live. One quote is about one fen — and the biggest item is Memory, not the model.", "成本：这页实时读 CloudWatch。一份约一分钱，最大项是 Memory，不是模型。", 0),
    (18, "Traces: left is every quote this session; right, the tool calls — which tool, how long, what went in and out.", "追踪：左边是本次会话每次报价；右边是工具调用——哪个工具、多久、输入输出。", 0),
    (17.1, "Below, the rule chain per line. Three things I would improve — each one is a gap, not a bug.", "下面是每行规则链。三件要改进的事——每件都是缺口，不是 bug。", 0),
    (30, "One: charts. OCR reads the labels on a drawing, but not the values plotted inside a bar or a curve — so a quantity that only exists in the chart is still invisible to me.", "一，图表。OCR 能读图纸上的标签，读不到柱状图或曲线里画出的数值——所以只存在于图里的数量，我现在看不到。", 0),
    (29.1, "Two: approvals. They land in a queue and someone can approve them in the page, but nobody gets an email — that needs SES, and it is the first thing I would wire next.", "二，审批。会进队列、页面上能批准，但没人收到邮件——需要 SES，是我接下来第一个要接的。", 0),
    (18.9, "Three: the confidence weights — ninety, seventy, sixty, forty-five — are my judgement, not learned; they should be fitted to labelled quotes.", "三，可信度权重——90/70/60/45——是我的判断不是学来的；应该用标注过的报价去拟合。", 0),
    (14.6, "So: rules handle the documents, a person handles the rest, and I wrote down everything in between.", "一句话：文件里有的规则处理，没有的交给人，中间的全部写成假设。", 3),
]


def stamp(seconds: float) -> str:
    hours, rest = divmod(seconds, 3600)
    minutes, secs = divmod(rest, 60)
    whole = int(secs)
    millis = int(round((secs - whole) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    return f"{int(hours):02d}:{int(minutes):02d}:{whole:02d},{millis:03d}"


def wrap(text: str, width: int = 46) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if len(candidate) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def build(track: str) -> str:
    blocks: list[str] = []
    cursor = 0.0
    for index, (duration, english, chinese, pause) in enumerate(CUES, start=1):
        start, end = cursor, cursor + duration
        cursor = end + pause
        if track == "en":
            body = wrap(english)
        elif track == "zh":
            body = wrap(chinese, width=24)
        else:
            body = wrap(english) + wrap(chinese, width=24)
        blocks.append(f"{index}\n{stamp(start)} --> {stamp(end)}\n" + "\n".join(body) + "\n")
    return "\n".join(blocks)


def marks() -> dict[str, str]:
    """段落起点，用来核对时间窗。"""
    wanted = ["So how does it actually work", "That is the design", "Now the same RFQ",
              "Both formats produce", "That is the happy path", "So what does all this cost",
              "One last thing"]
    found: dict[str, str] = {}
    cursor = 0.0
    for duration, english, _chinese, pause in CUES:
        start, end = cursor, cursor + duration
        for prefix in wanted:
            if english.startswith(prefix):
                found[prefix] = stamp(start)
        cursor = end + pause
    found["end"] = stamp(cursor)
    return found


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for track, name in (("bilingual", "demo.bilingual.srt"), ("en", "demo.en.srt"), ("zh", "demo.zh.srt")):
        path = OUT / name
        path.write_text(build(track), encoding="utf-8")
        print(f"{name}: {len(CUES)} cues, {path.stat().st_size} bytes")
    for label, when in marks().items():
        print(f"  {when}  {label}")
