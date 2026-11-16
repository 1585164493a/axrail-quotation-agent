# 录屏脚本 · 中英对照（严格按题目的分镜）

> 题目要求的时间窗（[27] 段）：
> **0:00–1:30** 架构 + 两个必答题 · **1:30–5:00** 同一份 RFQ 跑两种格式，展示同一报价 + PDF + 回信 ·
> **5:00–7:00** 这份询价里发现的问题，以及决定了什么 / 问了人什么 / 假设了什么 ·
> **7:00–8:00** 成本、日志或追踪、你会怎么改进。
>
> 语言：**旁白必须英文**（[29] 段）。中文只用于对意思。
> 生词读音见 [`pronunciation.md`](pronunciation.md)；字幕见 [`subtitles/`](subtitles/demo.bilingual.srt)。

## 录之前

```bash
python tools/ui.py          # → http://127.0.0.1:8765
aws sts get-caller-identity --profile aws   # 确认凭证没过期
```

四个标签页按顺序摆好：`/`（工作台）、`/inbox`、`/approvals`、`/prices`；另开一张 `docs/architecture.png` 全屏。

### 数字卡（贴屏幕边）

| 项 | 值 |
|---|---|
| 总额（两种格式都一样） | 74,684.00 MYR |
| 三行单价 | 26.86 / 54.52 / 50.35 |
| 题目算例成本 | 21.20 |
| 挂起两行 | SPC-050（数量 TBC）、HSG-400（Ti Gr5 无价 + 公差 ±0.005 超能力） |
| 冲突 | CVR-310：xlsx 1000 / 图纸 800 |
| 交付物 | 报价 PDF、复核清单 PDF、回信草稿 |

---

## 0:00–1:30 · 架构 + 两个必答题

【屏幕】`docs/architecture.png` 全屏。

【EN】
> "A CNC shop gets RFQs as an email plus Excel, PowerPoint, PDF, sometimes a scan. An estimator
> reads it, prices it, writes back. I built an agent that does the legwork — and it never produces
> a number itself."

【中文】客户发邮件加附件询价；估价员读文件、算价、回信。这个 agent 干杂活，自己不出数字。

【EN】
> "Five layers. Email to S3. Runtime runs agent dot py. Gateway exposes fourteen tools. The tools
> do the work. Deliverables go back to S3.
> Inside the tools, eight steps: ingest, parse, extract, interpret, normalise, price, review, render.
> The model only reads text — prices, discounts, approval are all code."

【中文】五层：S3 → Runtime（只编排）→ Gateway（14 工具）→ Lambda（干活）→ 交付物。工具里八步，模型只读文字。

【EN】⏸
> "Question one: I use three. Runtime for hosting, Gateway for tools and auth, Memory for state.
> Four I don't use: Identity, Code Interpreter, Browser, deep observability. One caller — and
> prices must stay in my code."

【中文】必答题一：用 Runtime / Gateway / Memory；不用 Identity、Code Interpreter、Browser、深度观测。

【EN】
> "Question two: from my LangGraph production stack I keep visible flow, testable steps, and a
> human saying yes. I replace hosting, my own MCP server and the Mongo checkpointer with Runtime,
> Gateway and Memory. And no framework here — the flow is straight-line, so functions beat a graph."

【中文】必答题二：留流程可见、步骤可测、有人点头；换托管、自建 MCP、Mongo checkpointer；这里不用框架。

## 1:30–5:00 · 两种格式，同一份报价

### 1:30–2:40 · 格式 A：只用正文

【屏幕】`/` 工作台，下拉选 `RFQ-2026-118 - CNC parts…`（`01_rfq_body_only`）。只勾 **Email body**，其余不勾（这封本来就没有附件）。点 **Generate quotation**。

【EN】
> "Format A: the email body alone — no attachments. One click, and the same pipeline runs."

【中文】格式 A：只有正文，没有任何附件。

【屏幕】指报价表与总额。

【EN】⏸
> "Three lines priced, two held, total seventy-four thousand six hundred and eighty-four ringgit.
> BRK-100 at twenty-six eighty-six is the brief's own worked example: cost twenty-one twenty,
> then margin, then the five-percent volume tier."

【中文】三行报价、两行挂起、合计 74,684；BRK-100 的 26.86 就是题目算例。

### 2:40–3:55 · 格式 B：Excel + PowerPoint（+ 图纸）

【过渡】

> **EN** "Now the same RFQ, but this time with the attachments."
>
> **中文** 现在同一份 RFQ，这次加上附件。

【屏幕】下拉切到 `02_rfq_full_attachments`。勾选列表出现三个附件：全勾。点 **Generate quotation**。

【EN】
> "Format B: the same RFQ, but now the Excel part list, the PowerPoint spec and the PDF drawing —
> all three ticked separately, so you can see which file contributed what."

【中文】格式 B：同一份 RFQ，勾上 Excel、PPT、PDF 三个附件（可逐个勾）。

【EN】⏸
> "Same three prices. Same total: seventy-four thousand six hundred and eighty-four. That
> equality is the requirement, and it is a test, not a claim — `test_same_quote` asserts it."

【中文】同样的三行、同样的 74,684。这个相等是测试钉住的（`test_same_quote`）。

【屏幕】点 `how?`，指一行公式与字段来源表。

【EN】
> "Same money, but more evidence: the trace shows which cell each field came from, and whether a
> rule, the model, or OCR read it."

【中文】钱一样，但证据更多：每个字段的出处与读取方式都列出来。

### 3:55–5:00 · 交付物：报价 PDF + 回信草稿

【过渡】

> **EN** "Both formats produce the same two documents: a quotation PDF and a reply draft."
>
> **中文** 两种格式产出同两份文件：报价 PDF 和回信草稿。

【屏幕】点子行里的 **PDF** 链接，浏览器打开报价单；回来切到回信草稿面板。

【EN】⏸
> "Two artefacts from the same dataset: the quotation PDF for the customer, and the reply email
> draft. The reply asks for the two things we cannot answer — the spacer quantity, and a price
> for the titanium housing — and it does not promise the fifteen percent."

【中文】同一份数据出两样：客户拿的报价 PDF、给估价员用的回信草稿；回信只问两件算不出的东西，不承诺 15% 折扣。

【屏幕】切 `/approvals` 一眼（不细讲）。

【EN】
> "Because of the amount, the holds and the discount request, it also lands in the approval queue."

【中文】因为金额、挂起和折扣请求，同时进了审批队列。

---

## 5:00–7:00 · 问题：决定了什么 / 问了人什么 / 假设了什么

题目把这一段拆成三问，我按同样顺序讲。

【过渡】

> **EN** "That is the happy path. Now the problems — and I'll split them three ways: what it decided,
> what it asked a person, and what I assumed."
>
> **中文** 顺利的部分讲完了。现在讲问题，我分三段：它自己决定了什么、问了人什么、我假设了什么。

### ① 它自己决定了什么（what it decided）

【屏幕】回到 `/` 的格式 B 结果，指报价行。

> **EN** "Quantity comes from the most authoritative document — drawing, then spreadsheet, then email.
> Discount comes from the quantity tier: five percent from five hundred, eight from a thousand.
> If a line cannot be priced, it is held — not guessed. And if the total or the discount crosses
> policy, it routes itself to approval."
>
> **中文** 数量取最权威的文件（图纸 > 表格 > 正文）；折扣按数量档位；算不出就挂起；越线自动进审批。

### ② 它问了人什么（what it asked a person）

【屏幕】依次指 SPC-050、HSG-400、CVR-310 三行，再切 `/approvals`。

> **EN**⏸
> "The spacer: quantity still to follow, so setup cannot be spread. Held, and the reply asks the buyer.
> The valve housing: titanium grade five is not on our price list, and the tolerance is tighter than
> any standard rate — two gaps on one line, so procurement and engineering.
> CVR-310: the drawing says eight hundred, the sheets say a thousand. It quotes the weighted source
> and flags the conflict for a human.
> And the fifteen percent discount: above our eight percent ceiling, so the sales manager decides."
>
> **中文** 垫片数量待定→问客户；阀体钛合金无价 + 公差超能力→问采购和工程；CVR-310 图纸 800/表格 1000→留给人确认；15% 折扣→问经理。

### ③ 我假设了什么（what you assumed）

【屏幕】停在报价页，或切到 README 的 known limits。

> **EN**⏸
> "And three things I assumed, because the brief leaves them open: thirty days validity;
> twenty-five percent is gross margin, so price is cost divided by zero point seven five;
> and the tier applies per line, from that line's quantity.
> Fifty thousand ringgit is where a manager signs, eight percent is the discount ceiling, and a
> missing value is held, never filled in. All of it is in the README, not buried in code."
>
> **中文** 三个假设：30 天有效；25% 是毛利率（售价 = 成本 ÷ 0.75）；档位按每行数量。另加两条政策假设：5 万签字线、8% 折扣上限；缺失值一律挂起。全部写在 README。

## 7:00–8:25 · 成本、日志/追踪、改进

### 成本：打开 `/cost`（有数、有图）

【屏幕】浏览器打开 `http://127.0.0.1:8765/cost`

> **EN** "Cost per quote — this page is live: it reads CloudWatch for this account and prices the
> work item by item. One quote is about one Chinese fen — roughly fifteen hundredths of a US cent.
> The biggest item is not the model: it is Memory events. The model is a fallback, and header mapping
> is cached per template, so a repeat customer never pays twice."
>
> **中文** 这一页是实时的：从 CloudWatch 读调用量，按单价逐项算。一份报价约一分钱（≈0.0016 美元）。
> 最大一项不是模型，而是 Memory 事件；模型只是兜底，而且表头映射按模板缓存。

【屏幕】指着条形图，从上往下数：Memory → Model → Runtime → Lambda → S3。

### 追踪：打开 `/traces`（两层）

【屏幕】切到 `http://127.0.0.1:8765/traces`

> **EN** "Two layers of trace. On the left, platform: every Runtime invocation with its session id and
> duration — four point seven seconds, seven and a half, two point three. On the right, the Lambda
> REPORT lines with duration, billed duration and memory."
>
> **中文** 两层追踪。左边是平台层：每次 Runtime 调用的 session id 和耗时；右边是 Lambda 的
> REPORT 行，带耗时、计费时长和内存。

【屏幕】往下滚到业务追踪，指着某个件号的规则链。

> **EN**⏸ "And this is the business layer: for the last quotation, every line's rule chain — material,
> machine time, finishing, setup, margin, tier, total — each with a rule id and an amount. That is why
> 'which file, which row, which rule' already has an answer when a price looks wrong."
>
> **中文** 这就是业务层：最近一次报价，每一行的规则链（材料、机时、表面处理、工装、毛利、档位、总额），
> 每条带规则号和金额。所以价格看起来不对时，"哪个文件、哪一行、哪条规则"已经有答案。

### 改进

> **EN** "Three things I would improve: charts — OCR reads labels but not plotted values; approvals —
> they queue but do not email the manager; and the confidence weights — ninety, seventy, sixty,
> forty-five are my judgement, not learned from labelled quotes."
>
> **中文** 三个改进：图表语义（需要视觉模型）、审批通知（需要 SES）、可信度权重（应该用标注数据拟合）。

## 8:25–9:06 · 可选补充：兜底真的会触发（超时就砍掉）

【过渡】

> **EN** "One last thing, if you have a minute: the fallbacks really do fire."
>
> **中文** 最后一点，如果有时间：兜底是真的会触发的。

【屏幕】`/inbox` 选 `rfq_prose_priced`，回 `/` 只勾正文 → 生成；再全勾 → 生成。

【EN】
> "One extra, if time allows: this RFQ is prose — 'maybe five hundred of them, about a tenth of
> a millimetre'. The regex reads nothing, so the model reads it: one call, confidence
> forty-five hundredths, which is below the threshold, so it goes to a human. Add the scanned
> job card and OCR contributes a second independent document — confidence rises to seventy-five,
> and the total does not move."

【中文】补充：口语询价只有模型读得出来（0.45，低于阈值必须人工）；加上扫描件后两份独立文件印证，升到 0.75，金额不变。

---

## 出错应急

| 现象 | 处理 | 口播 |
|---|---|---|
| 页面空白 | Ctrl+F5 | "Let me reload — the UI is a local shell." |
| 列表空 / 401 | 凭证过期，`aws login` | "Credentials expired — re-authenticating." |
| 报价为空 | 勾选为空或该邮件没有零件行 | "Nothing ticked — let me tick the body." |
| 冷启动慢 | 首次 3–6 秒 | "First call after idle takes a few seconds." |

## 三句别念错

1. 不是 "the model calculates the price" → **"the model reads text, the code prices"**
2. 不是 "approvals are automated" → **"the queue and status work; the notification is not built"**
3. 不是 "fully automatic" → **"what can be priced is priced; what cannot is held with the missing field named"**
