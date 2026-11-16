# 面试稿（中英对照）· AI Quotation Agent

> 用法：中文用来准备思路，英文用来**念**（视频旁白必须英文）。
> 每段都能在括号标注的时长内说完，语速按 140 词/分钟估。

---

## 0. 事实速查（背下来，别记错）

| 项 | 数字 |
|---|---|
| 样例 RFQ 总额 | **74,684.00 MYR** |
| 三行单价 | BRK-100 26.86 · SHF-220 54.52 · CVR-310 50.35 |
| 两行挂起 | SPC-050（数量 TBC）· HSG-400（Ti Gr5 无价） |
| 一行冲突 | CVR-310 数量：xlsx 1000 vs 图纸 800 |
| 题目算例 | 0.40×18 + 6×2 + 1.50 + 250/500 = **21.20** |
| Runtime 工具数 | **14**（price_line / build_quote / quote_email / render_reply / render_quote_pdf / render_review_pdf / reprice_quote / submit_approval / list_approvals / decide_approval / list_emails / read_email / preview_attachments / get_prices） |
| 测试 | **174 个，约 4 秒** |
| 可控性评分 | 表格 0.90 · PDF 0.70 · 正文 0.60 · 模型 0.45；低于 **0.55** 标红 |
| 审批阈值 | 总额 ≥ **50,000**；折扣 > **8%** |
| 区域 | 现 **ap-southeast-2**；生产建议 **ap-southeast-1** |
| 每份报价成本 | 确定性路径 **0 模型调用**；兜底一次约 1–2k token |
| OCR | Amazon Rekognition（Textract 被本账号 SCP 拒绝） |

---

## 1. 电梯陈述（90 秒）

### 中文

我做的是一个给 CNC 加工厂用的**报价 Agent**。客户发来一封询价邮件，正文里可能写了零件，也可能只有附件——Excel 零件表、PPT 规格页、PDF 图纸，甚至是扫描件。

它做四件事：把零件抽出来、用**确定性代码**算价、把该人看的东西标出来、然后产出报价单 PDF、复核清单和回信草稿。

我用的是 Amazon Bedrock AgentCore：Runtime 跑编排、Gateway 把工具按 MCP 暴露、Memory 存状态。

最关键的一条设计：**模型只负责读文字，价格永远来自代码**。样例这份询价，只用正文、只用附件、两者都用，报出来都是 **74,684 MYR**，一分不差。

### English

I built a quotation agent for a CNC machine shop. A customer sends an RFQ email — the parts may be in the body, or only in attachments: an Excel part list, a PowerPoint spec slide, a PDF drawing, sometimes a scanned page.

The agent does four things: it extracts the parts, prices them with **deterministic code**, flags everything a person should look at, and produces a quotation PDF, an internal review list and a reply email draft.

It runs on Amazon Bedrock AgentCore: Runtime for orchestration, Gateway to expose the tools over MCP, Memory for state.

The one design rule that matters: **the model only reads text — prices always come from code.** For the sample RFQ, body only, attachments only, or both, all give **74,684 MYR**, to the cent.

---

## 2. 架构走查（3 分钟，对着架构图讲）

### 中文

（指着图）从左到右五层。

**第一层，输入**：邮件进 S3，原文原样保存，附件单独落盘。

**第二层，Runtime**：`agent.py` 只做编排——收请求、调工具、写 Memory，**里面没有一行算术**。

**第三层，Gateway**：MCP 协议、AWS IAM 鉴权，把 Lambda 上的 14 个工具暴露成 `tools___build_quote` 这样的名字。

**第四层，Lambda 工具**：真正的活都在这。流水线是 ingest → extract → normalise → confidence → price → approval → render。

**第五层，交付物**：报价单 PDF、复核清单 PDF、回信草稿，都写到 S3 给一小时有效的链接；需要签字的进审批队列。

下面两块是我的重点。黄色那块是**模型介入的四个点**，全是可选的兜底：正文抽不全、表头认不出、单个值读不懂、两个来源打架。白色那块是**模型永远不做的事**：不出价格、不做审批、不算可控性、不写 PDF。

为什么这样切？因为报价是要签字的商业文件。模型可以帮你读，但不能帮你算。

### English

(Point at the diagram.) Five layers, left to right.

**Inputs.** The email lands in S3 exactly as received; attachments are staged separately.

**Runtime.** `agent.py` is orchestration only — take the request, call the tools, write Memory. There is not a single arithmetic operation in it.

**Gateway.** MCP protocol, AWS IAM auth, exposing fourteen Lambda tools as `tools___build_quote` and friends.

**Lambda tools.** The real work. The pipeline is ingest → extract → normalise → confidence → price → approval → render.

**Deliverables.** Quotation PDF, review-list PDF, reply draft — written to S3 with one-hour links. Anything that needs a signature goes to the approval queue.

Two bands below matter most. The amber one lists the **four model touchpoints**, all optional fallbacks: body extraction, header mapping, single-value interpretation, conflict arbitration. The white one is what the model **never** does: no price, no approval decision, no confidence score, no PDF content.

Why this split? A quotation is a commercial document someone signs. The model may read; it may not calculate.

---

## 3. 现场演示（6 步，约 4 分钟）

**Step 1 — 打开收件箱** `/inbox`
- CN：这里是 S3 里的真实邮件，按公司域名和联系人筛选。
- EN: This is the live inbox in S3, filtered by company domain and contact.

**Step 2 — 选一封，看正文和附件原件**
- CN：附件能直接打开原件——PDF 内嵌预览，Excel 逐格显示。我要的是**证据**，不是我的转述。
- EN: Attachments open as the original file — PDFs inline, spreadsheets cell by cell. I want evidence, not my summary.

**Step 3 — 回主页面，点「Attachments + body」**
- CN：一次调用走 Runtime → Gateway → Lambda。约六秒，因为中间有一次模型兜底。
- EN: One call goes Runtime → Gateway → Lambda. About six seconds, because there is one model fallback in the middle.

**Step 4 — 讲报价**
- CN：三行报价、两行挂起。总额 74,684。挂起的行不是「什么都没有」——数量没定，我照样把材料费和机时费算出来了；材料没价，我把数量和工装费列出来，采购只要补一个数。
- EN: Three lines priced, two held. Total 74,684. A held line is not empty: with the quantity missing, material and machine cost are still computed; with the material missing, the quantity and setup cost are shown, so procurement only fills one gap.

**Step 5 — 点 `how?` 和 `why?`**
- CN：`how?` 是这一行的八步推导，每步带出处；`why?` 是可控性打分——CVR-310 是 0.30，因为 Excel 说 1000、图纸说 800。
- EN: `how?` shows the eight-step derivation with a source per step. `why?` shows confidence — CVR-310 scores 0.30 because the spreadsheet says 1,000 and the drawing says 800.

**Step 6 — 拖折扣、生成、提交审批**
- CN：拖到 12%，利润和毛利率实时重算；点生成，表格和 PDF 一起变成 12% 那版；提交审批，状态变成待经理。
- EN: Slide to 12% — profit and margin recompute. Generate, and the table and the PDF both switch to the 12% version. Submit, and the status becomes pending manager.

**Step 7 — 打开审批页和价格页**
- CN：审批页能看到为什么批、哪些行需要人看；价格页直接读定价代码里的常量，不存在两份价格表。
- EN: The approval page shows why, and which lines need a human; the price page reads the constants from the pricing code — there is no second price list.

---

## 4. 必答问题一：哪些部分用了 AgentCore，哪些没有，为什么

### 中文

**用了三样**：

**Runtime**——因为它解决的是「把一段代码变成一个有地址、能扩缩容、有日志的服务」。我的 agent 只需要编排，不需要自己写 HTTP 服务、管容器。

**Gateway**——因为它把「工具」和「谁能调」这两件事从业务代码里剥离出来。我加一个工具只改工具定义，agent 侧不用动；鉴权交给 IAM。

**Memory**——因为 Runtime 是无状态的，一次报价要跨多个工具调用，我需要把 received → priced → rendered 这三次状态记下来。

**没用四样**：

**Identity**——我只有一种调用方，IAM 角色够了。

**Code Interpreter**——价格必须来自我自己的纯函数，不能来自一段现场执行的 Python。

**Browser**——没有网页要抓。

**Observability 的深度功能**——CloudWatch 日志已经够排查，没有额外的 trace 需求。

一句话：**用了解决「托管、暴露、状态」的三样，没用「计算、浏览、额外身份」的四样。**

### English

**Three capabilities, yes.**

**Runtime**, because it turns a piece of code into an addressable service with scaling and logs. My agent only orchestrates; I do not want to run a web server or manage containers.

**Gateway**, because it separates "what a tool is" and "who may call it" from business code. Adding a tool is a schema change, not an agent change; auth is IAM.

**Memory**, because Runtime is stateless and a quote spans several tool calls — I record received → priced → rendered.

**Four capabilities, no.**

**Identity** — I have one caller; an IAM role is enough.
**Code Interpreter** — prices must come from my own pure functions, never from code executed on the fly.
**Browser** — there is nothing to browse.
**Deep Observability** — CloudWatch logs are enough to debug this.

In one line: **yes to hosting, exposure and state; no to computation, browsing and extra identity.**

---

## 5. 必答问题二：和 LangGraph / LangChain 生产栈比，留什么、换什么

### 中文

我在供应链 AI 助手里用过 LangGraph。它的好处是**状态机显式**：节点、边、检查点都看得见，复杂分支好推理，也能单测每个节点。这部分我会**留着**——我的定价流水线就是按这个思路写的：每个阶段都是纯函数，可以单独测。

我会**换掉**三样：

**一、运行平台。** LangGraph 要自己托管，扩缩容、日志、冷启动都是我的事。AgentCore Runtime 把这些接走，我只需要一个 `agent.py`。

**二、工具边界。** LangGraph 里工具是进程内的函数，谁能调靠代码自查。Gateway 把它变成协议层的 MCP 工具，鉴权和审计在网关，不在业务代码里。

**三、记忆。** 以前是 Postgres 加一层自研状态表；现在是 Memory 的事件，TTL 由平台管。

**我还会保留一条**：不把定价权交给模型。LangGraph 很容易写成「让模型选下一个节点」，我明确不用——流程是固定的，模型的自由度只留在读文字那一步。

一句话：**图的思维方式留着，运行和集成那层换成托管的。**

### English

I have used LangGraph in a supply-chain AI assistant. What I keep is the **explicit state machine**: visible nodes, edges and checkpoints; easy to reason about and to unit-test. My pricing pipeline is written that way — every stage is a pure function I can test alone.

Three things I replace.

**Hosting.** With LangGraph I own deployment, scaling, logs and cold starts. AgentCore Runtime takes that away; I ship an `agent.py`.

**Tool boundary.** In LangGraph tools are in-process functions, and who may call them is a code convention. Gateway makes them MCP tools at the protocol layer, with auth and audit outside business code.

**Memory.** I used Postgres plus a home-grown state table; now it is Memory events with platform-managed TTL.

One thing I keep deliberately: the model does not get pricing authority. It is easy to write a LangGraph that lets the model choose the next node; I do not. The flow is fixed, and the model's freedom stops at reading text.

In one line: **keep the graph thinking, replace the hosting and integration layer.**

---

## 6. 追问速答（每题 30–60 秒）

**Q: 为什么不让模型直接算价？**
CN：因为报价要签字。模型会算错、会说得很像对的，而且同一封邮件问两次可能给两个价。代码不会。
EN: Because a quote gets signed. A model can be wrong while sounding confident, and the same email can produce two different prices. Code cannot.

**Q: 模型在哪一步被调用？**
CN：只有一处是必须的——正文抽不全时的结构化抽取。另外三处是兜底：表头映射、单个值解释、冲突仲裁。整齐的询价，全程零模型调用。
EN: Exactly one mandatory place — structured extraction when the regex is incomplete. Three more are fallbacks: header mapping, single-value interpretation, conflict arbitration. A clean RFQ makes zero model calls.

**Q: 附件和正文冲突怎么办？**
CN：不自动解决。按来源权重取权威值（表格 0.90 > 图纸 0.70 > 正文 0.60 > 模型 0.45），同时记一条冲突，报价单、复核清单、回信三处都写明。CVR-310 就是 1000 和 800 的例子。
EN: Not auto-resolved. Take the weighted source, keep the conflict record, and state it in the quote, the review list and the reply. CVR-310 is the 1,000 versus 800 case.

**Q: 可信度怎么算的？**
CN：按来源给权重，多来源一致加分，矛盾降到 0.30，缺失 0.40，整行取数量/材料/公差三项最低分；低于 0.55 标红并进审批理由。权重是经验判断，不是训练出来的——这点我会直说。
EN: Weight by source, bonus for agreement, 0.30 for a conflict, 0.40 for a missing value, and the line takes the minimum over quantity, material and tolerance. Below 0.55 it is flagged and becomes an approval reason. The weights are judgement, not trained — I say so.

**Q: 扫描件怎么读的？**
CN：Textract 在这个账号被 SCP 拒绝，所以用 Rekognition DetectText，逐页判断：没有文字层、或者有图但结构读不出，就送 OCR；低于 80% 置信度的行丢掉。OCR 会丢标点，所以字段是按内容特征抓的，不靠逗号。
EN: Textract is denied by this account's SCP, so I use Rekognition DetectText. The decision is per page: no text layer, or an image page with no usable structure. Lines below 80% confidence are dropped. OCR drops punctuation, so fields are harvested by pattern, not by commas.

**Q: 成本多少？**
CN：确定性路径零模型调用；一次兜底约一两千 token，按模板缓存后同一客户只花一次。AWS 侧是一次 Lambda 加几百毫秒 Runtime。整份报价的成本可以忽略。
EN: Zero model calls on the deterministic path; a fallback is one to two thousand tokens, cached per template. On AWS it is one Lambda invocation and a few hundred milliseconds of runtime. The cost per quote is negligible.

**Q: 为什么部署在悉尼，题目建议新加坡？**
CN：这个账号的区域被锁定在 ap-southeast-2。生产我会选 ap-southeast-1，离马来西亚最近，数据不出区域。
EN: The account is pinned to Sydney. In production I would choose Singapore: closest to Malaysia, and customer data stays in-region.

**Q: 审批怎么通知经理？**
CN：现在是写进 S3 的审批队列，页面上能看到并批准/驳回；没有真的发邮件，因为发信要 SES 权限。这一步我明确说是没做完的。
EN: Today it writes to an approval queue in S3, visible and actionable in the UI. It does not email the manager yet — that needs SES. I am explicit that this part is not finished.

**Q: 为什么要做 review list？**
CN：题目要求「what was flagged and why, plus approval status」。所以那一页就是：谁要签字、为什么、哪几行要人看、每个价格追到哪一行哪条规则。
EN: The brief asks for what was flagged and why, plus approval status. So that page is exactly that: who signs, why, which lines need a human, and where each price came from.

**Q: 174 个测试都测了什么？**
CN：定价算例和档位、三种输入路径同价、14 个工具、可信度打分、审批流转、OCR 与结构映射、解析器的边界情况。跑一遍四秒，不联网。
EN: The pricing example and tiers, equal quotes across three input paths, all fourteen tools, confidence scoring, the approval flow, OCR and structure mapping, and parser edge cases. Four seconds, offline.

**Q: 如果客户表格格式又变了？**
CN：表头认不出时会先试结构映射（模型给列→字段），通过五道校验才采用，并按模板指纹缓存；下次同一模板不再调模型。映射不通过就退回文本收割，仍不行就挂起问人。
EN: When the header is unrecognisable, structure mapping proposes column-to-field, passes five checks, and is cached by template fingerprint — the same template never pays twice. If mapping fails, text harvest runs; if that fails, the line is held for a human.

**Q: 你最大的取舍是什么？**
CN：宁可报不出价，也不猜。挂起会让人觉得不够智能，但商业文件里，一个错价的代价远大于一句「这个我们要确认」。
EN: I would rather not quote than guess. Holding a line looks less impressive, but in a commercial document a wrong price costs far more than "we need to confirm this one".

---

## 7. 三句话别说错

1. **别说「模型算价格」**——要说「模型读文字，代码算价格」。
2. **别说「审批已经通了」**——要说「审批队列和状态流转通了，通知还没接」。
3. **别说「全部自动化」**——要说「能自动的自动，不能算的挂起并说明缺什么」。

## 8. 被问住时怎么接

> "That part I have not built — here is how I would do it."

然后给一句具体方案（比如发信走 SES、扫描件接 Textract），不要硬编。诚实是这套东西的加分项，因为它本来就是按「宁可挂起也不猜」设计的。
