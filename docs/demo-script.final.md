# 录屏口播 · 定稿（按 70 词/分钟压缩）

> 实测语速约 70 词/分钟，所以全稿压到 ~480 词，念完约 7 分钟，留出操作时间。
> **英文是念出来的**，中文是同义对照。时间窗仍对齐：1:30 / 5:00 / 7:00。


## 0:00–1:30 · 架构 + 两个必答题

**EN**
> For the brief, I built one path from a mixed-format RFQ to a delivered quote.

**中文**
> 针对题目，我做了一条从多格式询价到报价交付的完整链路。

**EN**
> Five layers: email into S3, Runtime runs agent dot py, Gateway exposes fourteen tools, the tools do the work, deliverables back to S3.

**中文**
> 五层：邮件进 S3，Runtime 跑 agent.py，Gateway 暴露十四个工具，工具干活，交付物回 S3。

**EN**
> Inside the tools, eight steps from ingest to render — and the model only reads text. Everything else is code.

**中文**
> 工具里八步，从接入到交付；模型只读文字，其余全是代码。

**EN**
> Question one: I use three. Runtime hosts the agent, Gateway exposes the fourteen tools with IAM auth, and Memory keeps state between calls.

**中文**
> 必答题一：我用三样。Runtime 托管 agent，Gateway 带 IAM 鉴权暴露十四个工具，Memory 保存调用之间的状态。

**EN**
> Four I skip: Identity — one caller; Code Interpreter — prices stay pure; Browser — nothing to browse; deep tracing — logs are enough.

**中文**
> 另外四项不用：Identity（单调用方）、Code Interpreter（价格要纯函数）、Browser（没网页）、深度追踪（日志够用）。

**EN**
> Question two: from my LangGraph stack I keep three things — visible flow, plain-function tools, and a human sign-off.

**中文**
> 必答题二：LangGraph 里我留三样——流程可见、工具是函数、有人点头。

**EN**
> I replace hosting, my own MCP server and the Mongo checkpointer with Runtime, Gateway and Memory — and no framework, since the flow is straight.

**中文**
> 托管、自建 MCP、Mongo checkpointer 换成 Runtime、Gateway、Memory；链路是直的，不用框架。


## 1:30–5:00 · 界面演示

**EN**
> Let me run the sample RFQ. The front end is a small local UI, in tools ui py.

**中文**
> 演示样例 RFQ。前端是个本地小界面，代码在 tools/ui.py。

**EN**
> I pick the email, tick what to read — body only first — and generate.

**中文**
> 选邮件，勾选要读的内容，先只勾正文，然后生成。

**EN**
> Here are the lines and the suggested price. Click how for the pricing logic and the sources.

**中文**
> 这是提取出的行和建议价。点 how 看计算逻辑和出处。

**EN**
> Click why for the confidence — the score is rules, the sentence is the model.

**中文**
> 点 why 看置信度——分数由规则算出，解释那句话是模型写的。

**EN**
> Scroll to discount: sliding recomputes margin and quote. The email's requested discount goes to Needs sign-off, as a reference.

**中文**
> 往下是折扣：拖动即重算毛利率和报价；邮件里的期望折扣放进 Needs sign-off 作参考。

**EN**
> Sliding also regenerates the PDF and the reply. Above policy, it cannot be approved directly — it routes to approval.

**中文**
> 拖动同时重新生成 PDF 和回信；超过政策线不能直接批，走审批。

**EN**
> Five lines, but not all can be quoted: a held section explains each, and a conflicts box for multi-source disagreement.

**中文**
> 五行里不是每行都能报价：held 栏逐行解释，Conflicts 栏处理多源冲突。

**EN**
> Generate at this discount produces the review list, the reply and the quotation PDF.

**中文**
> 点这个折扣生成，得到复核清单、回信和报价单 PDF。

**EN**
> At the bottom, attachment previews and the original file; the top navigation has the other pages.

**中文**
> 最下面是附件预览和原件；顶部导航是其它页面。


## 5:00–7:00 · 问题：决定 / 问人 / 假设

**EN**
> Now the problems — decided, asked, assumed.

**中文**
> 现在讲问题：它决定的、问人的、我假设的。

**EN**
> Decided: quantity from the most authoritative document, discount from the tier, unpriceable lines held, policy breaches routed to approval.

**中文**
> 它决定的：数量取最权威文件，折扣按档位，算不出的挂起，越线自动进审批。

**EN**
> Asked: the spacer's quantity, the titanium price and its tight tolerance, the drawing-versus-sheet conflict, and the fifteen percent discount.

**中文**
> 问人的：垫片数量、钛合金价格与超紧公差、图纸与表格的冲突、15% 折扣。

**EN**
> Assumed — and the table shows it: twenty-five percent is a margin, not a markup; tiers apply per line; fifty thousand needs a manager; eight percent caps the discount; a missing value is held.

**中文**
> 假设都在表里：25% 是毛利率不是加价率；档位按行；五万要经理签字；8% 是折扣上限；缺失值挂起。


## 7:00–8:30 · 成本 / 追踪 / 改进

**EN**
> Cost: this page reads CloudWatch live. One quote is about one fen — and the biggest item is Memory, not the model.

**中文**
> 成本：这页实时读 CloudWatch。一份约一分钱，最大项是 Memory，不是模型。

**EN**
> Traces: left is every quote this session; right, the tool calls — which tool, how long, what went in and out.

**中文**
> 追踪：左边是本次会话每次报价；右边是工具调用——哪个工具、多久、输入输出。

**EN**
> Below, the rule chain per line. Three improvements: chart semantics, approval email, and learned confidence weights.

**中文**
> 下面是每行规则链。三个改进：图表语义、审批邮件、可信度权重用数据拟合。


## 收尾

**EN**
> So: rules handle the documents, a person handles the rest, and I wrote down everything in between.

**中文**
> 一句话：文件里有的规则处理，没有的交给人，中间的全部写成假设。
