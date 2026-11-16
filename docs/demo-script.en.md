# Demo narration — English (full script)

> Record this. 0:00–9:06. Screen cues in square brackets. Pauses marked ⏸.
> Chinese twin: `demo-script.zh.md`. Bilingual master: `demo-script.md`. Subtitles: `subtitles/`.

---

## 0:00–1:30 · Architecture + both required questions

[Screen: `docs/architecture.png`, full screen]

> A CNC shop gets RFQs as an email plus Excel, PowerPoint, PDF, sometimes a scan. An estimator reads
> it, prices it, writes back. I built an agent that does the legwork — and it never produces a number
> itself.

> Five layers. Email to S3. Runtime runs agent dot py. Gateway exposes fourteen tools. The tools do the
> work. Deliverables go back to S3. Inside the tools, eight steps: ingest, parse, extract, interpret,
> normalise, price, review, render. The model only reads text — prices, discounts, approval are all code.

> Question one: I use three. Runtime for hosting, Gateway for tools and auth, Memory for state. Four I
> don't use: Identity, Code Interpreter, Browser, deep observability. One caller — and prices must stay
> in my code.

> Question two: from my LangGraph production stack I keep visible flow, testable steps, and a human
> saying yes. I replace hosting, my own MCP server and the Mongo checkpointer with Runtime, Gateway and
> Memory. And no framework here — the flow is straight-line, so functions beat a graph.

---

## 1:30–5:00 · Two formats, same quote

[Screen: workbench `/`, pick the sample email]

> That is the design. Now let me run the actual sample RFQ — twice, in two formats.

> Format A: the email body alone. No attachments. One click.

[Screen: only "Email body" ticked, Generate]

> Three lines priced, two held, total seventy-four thousand six hundred and eighty-four ringgit.
> BRK-100 at twenty-six eighty-six is the brief's own worked example: cost twenty-one twenty, then
> margin, then the five-percent volume tier.

[Screen: switch to the email with attachments, tick all three files, Generate]

> Now the same RFQ, but this time with the attachments — the Excel part list, the PowerPoint spec and
> the PDF drawing, each ticked separately.

> Same three prices. Same total: seventy-four thousand six hundred and eighty-four. That equality is
> the requirement, and it is a test, not a claim.

[Screen: click `how?` on a line]

> The trace shows which cell each field came from, and whether a rule, the model or OCR read it.

[Screen: open the quotation PDF, then the reply draft panel]

> Both formats produce the same two documents: a quotation PDF for the customer, and a reply draft.
> The reply asks for the two things we cannot answer — the spacer quantity and a titanium price — and
> it does not promise the fifteen percent. Because of the amount, the holds and the discount request,
> it also enters the approval queue.

---

## 5:00–7:00 · Problems: decided / asked a person / assumed

[Screen: back to the workbench result]

> That is the happy path. Now the problems — and I'll split them three ways: what it decided, what it
> asked a person, and what I assumed.

> First, what it decided on its own. Quantity comes from the most authoritative document — drawing
> first, then spreadsheet, then email. Discount comes from the quantity tier: five percent from five
> hundred pieces, eight from a thousand. If a line cannot be priced, it is held — not guessed. And if
> the total or the discount crosses policy, it routes itself to approval.

[Screen: point at SPC-050, HSG-400, CVR-310, then `/approvals`]

> Second, what it asked a person. The spacer: quantity still to follow, so the setup cost cannot be
> spread — held, and the reply asks the buyer. The valve housing: titanium grade five is not on our
> price list, and the tolerance is tighter than any standard rate — two gaps on one line, so
> procurement and engineering. CVR-310: the drawing says eight hundred, the sheets say a thousand — it
> quotes the weighted source and flags the conflict for a human. And the fifteen percent discount:
> above our eight percent ceiling, so the sales manager decides.

[Screen: stay on the quote, or cut to the README known limits]

> Third, what I assumed. Thirty days validity. Twenty-five percent is a gross margin, so price is cost
> divided by zero point seven five — not cost plus twenty-five percent. The tier applies per line, from
> that line's own quantity. Fifty thousand ringgit is where a manager signs, eight percent is the
> discount ceiling, and a missing value is held, never filled in. All of it is in the README, not
> buried in code.

---

## 7:00–8:00 · Cost, traces, improvements

[Screen: the `Model calls this quote:` row]

> Cost per quote. The deterministic path makes zero model calls — the UI says so. When a fallback runs
> it is one call of one to two thousand tokens, and header mapping is cached by template fingerprint.
> On AWS it is one Lambda invocation, a few hundred milliseconds of Runtime and a few kilobytes in S3:
> a fraction of a cent, against twenty minutes of an estimator's time.

[Screen: CloudWatch logs, then `how?` again]

> Traces, two layers. Platform: every Runtime invocation has a session id and CloudWatch logs.
> Business: every parse run records which parser version produced which rows — so "which file, which
> row, which rule" already has an answer, and the review list repeats it for the person signing off.

> Three things I would improve. Charts: OCR reads labels but not plotted values, so a quantity that
> lives only in a bar chart is still unreadable — that needs a vision model. Approvals: they land in a
> queue, but nobody gets an email — that needs SES. And the confidence weights: ninety, seventy,
> sixty, forty-five are my judgement, not learned — they should be fitted to labelled quotes.

---

## 8:00–9:06 · Optional: the fallbacks really fire

[Screen: `/inbox`, pick the prose RFQ, back to `/`, body only, Generate]

> One last thing, if you have a minute: the fallbacks really do fire. This RFQ is prose — "maybe five
> hundred of them, about a tenth of a millimetre". The regex reads nothing, so the model reads it: one
> call, confidence forty-five hundredths. Below the threshold, so both lines go to a human.

[Screen: tick the scanned job card as well, Generate]

> Add the scanned job card and OCR contributes a second independent document. Confidence rises to
> seventy-five hundredths — and the total does not move.

---

## If something breaks

| What you see | Say |
|---|---|
| Blank page | "Let me reload — the UI is a local shell." |
| Empty list / 401 | "Credentials expired — re-authenticating." |
| Empty quote | "Nothing ticked — let me tick the body." |
| Slow first call | "First call after idle takes a few seconds." |

## Three lines not to say

1. Not "the model calculates the price" → **"the model reads text, the code prices."**
2. Not "approvals are automated" → **"the queue and status work; the notification is not built."**
3. Not "fully automatic" → **"what can be priced is priced; what cannot is held with the missing field named."**
