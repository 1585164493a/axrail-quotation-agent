# Transcript — what was actually said

> 这是录制时实际念的英文稿（27 句，约 553 词）。与 `docs/demo-script.final.md` 的差异：
> 最后"三个改进"按加长版讲（每条一句）。
> 用途：YouTube 字幕底稿、README 引用、或提交邮件里的说明。

For the brief, I built one path from a mixed-format RFQ to a delivered quote. Five layers: email into S3, Runtime runs agent dot py, Gateway exposes fourteen tools, the tools do the work, deliverables back to S3. Inside the tools, eight steps from ingest to render — and the model only reads text. Everything else is code.

Question one: I use three. Runtime hosts the agent, Gateway exposes the fourteen tools with IAM auth, and Memory keeps state between calls. Four I skip: Identity — one caller; Code Interpreter — prices stay pure; Browser — nothing to browse; deep tracing — logs are enough. Question two: from my LangGraph stack I keep three things — visible flow, plain-function tools, and a human sign-off.

I replace hosting, my own MCP server and the Mongo checkpointer with Runtime, Gateway and Memory — and no framework, since the flow is straight. Let me run the sample RFQ. The front end is a small local UI, in tools ui py. I pick the email, tick what to read — body only first — and generate.

Here are the lines and the suggested price. Click how for the pricing logic and the sources. Click why for the confidence — the score is rules, the sentence is the model. Scroll to discount: sliding recomputes margin and quote. The email's requested discount goes to Needs sign-off, as a reference.

Sliding also regenerates the PDF and the reply. Above policy, it cannot be approved directly — it routes to approval. Five lines, but not all can be quoted: a held section explains each, and a conflicts box for multi-source disagreement. Generate at this discount produces the review list, the reply and the quotation PDF.

At the bottom, attachment previews and the original file; the top navigation has the other pages. Now the problems — decided, asked, assumed. Decided: quantity from the most authoritative document, discount from the tier, unpriceable lines held, policy breaches routed to approval.

Asked: the spacer's quantity, the titanium price and its tight tolerance, the drawing-versus-sheet conflict, and the fifteen percent discount. Assumed — and the table shows it: twenty-five percent is a margin, not a markup; tiers apply per line; fifty thousand needs a manager; eight percent caps the discount; a missing value is held. Cost: this page reads CloudWatch live. One quote is about one fen — and the biggest item is Memory, not the model.

Traces: left is every quote this session; right, the tool calls — which tool, how long, what went in and out. Below, the rule chain per line. Three things I would improve — each one is a gap, not a bug. One: charts. OCR reads the labels on a drawing, but not the values plotted inside a bar or a curve — so a quantity that only exists in the chart is still invisible to me.

Two: approvals. They land in a queue and someone can approve them in the page, but nobody gets an email — that needs SES, and it is the first thing I would wire next. Three: the confidence weights — ninety, seventy, sixty, forty-five — are my judgement, not learned; they should be fitted to labelled quotes. So: rules handle the documents, a person handles the rest, and I wrote down everything in between.
