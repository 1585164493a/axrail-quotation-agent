# 7:00–8:00 成本 / 追踪 / 改进 · 中英双版（对应新版 /cost 与 /traces）

> 题目原话：**7:00–8:00 cost per quote, logs or traces, and what you would improve.**
> 英文是录屏念的，中文是等义全文。对应字幕：第 40–51 条（7:00–8:30）。
>
> **录屏前先做一次报价**，`/traces` 左侧历史才有内容。

---

## 过渡

**EN**
> So what does all this cost, and how would you debug it?

**中文**
> 这套东西要花多少钱，出了问题又怎么查？

---

## ① 成本：打开 `/cost`

【屏幕】`http://127.0.0.1:8765/cost`

**EN**
> "Cost per quote. This page is live: it reads CloudWatch for this account and prices the work item
> by item — no estimate typed by hand.
>
> One quote is about one Chinese fen — a bit over a tenth of a US cent.
>
> And the biggest item is not the model. It is Memory events: three events per quote. The model call
> is a fallback, header mapping is cached per template, and Lambda is five percent of the total."

**中文**
> 每份报价的成本。这一页是实时的：从 CloudWatch 读这个账号的调用量，再按单价逐项算，没有一个数字是我手填的。
>
> 一份报价大约一分钱人民币，十分之一美分多一点。
>
> 而且最大的一项不是模型——是 Memory 事件，每份报价三条。模型只是兜底，表头映射按模板缓存，Lambda 只占 5%。

【屏幕】指顶部大数字与 `measured` 那两行；再从上往下指条形图。

**念的时候可以说出的数**

| 位置 | 数字 |
|---|---|
| 大数字 | ¥0.0116 / quote（≈ US$0.0016，≈ 1.2 分） |
| measured | 812 次 Lambda 调用 · 平均 629.8 ms · 最大 8,087.6 ms（近 24 小时） |
| 条形图 | Memory $0.00075 › Model $0.00052 › Runtime $0.00026 › Lambda $0.00008 › S3 $0.00002 |
| 右下卡片 | 对照：估价员一份约 20 分钟 |

---

## ② 追踪：打开 `/traces`

【屏幕】`http://127.0.0.1:8765/traces`

**EN**
> "Traces. Two layers, answering different questions.
>
> On the left, every quote from this session, newest first — RFQ number, total, how many tool calls,
> how long it took.
>
> On the right, the tool calls themselves: which tool, how many milliseconds, and what went in and
> what came out. Quote email took eleven hundred milliseconds and returned three priced lines, two
> held and one conflict. Then the reply, the quotation PDF, the review list."

**中文**
> 追踪。两层，回答的是不同问题。
>
> 左边是本次会话的每一次报价，最新的在上面：RFQ 号、总额、调了几次工具、花了多久。
>
> 右边就是工具调用本身：调了哪个工具、多少毫秒、输入是什么、输出是什么。
> quote_email 用了 1.1 秒，返回三行报价、两行挂起、一个冲突；然后是回信、报价单 PDF、复核清单。

【屏幕】点左侧历史里的一条，让右栏刷新；鼠标悬停某一行的 Input/Output（有完整内容）。

**EN**
> "And underneath, the business layer: for that quotation, every line's rule chain — material, machine
> time, finishing, setup, margin, tier, total — each with a rule id and an amount. That is why
> 'which file, which row, which rule' already has an answer when a price looks wrong."

**中文**
> 下面还有业务层：这一份报价里每一行的规则链——材料、机时、表面处理、工装、毛利、档位、总额，每条带规则号和金额。
> 所以价格看起来不对时，“哪个文件、哪一行、哪条规则”已经有答案。

**这一屏会显示的真实内容**

```
1  quote_email        1165 ms  in={key=inbox/02_rfq_full_attachments.eml, mode=both, …}
                               out={rfq_no=RFQ-2026-118, customer=Example Customer Sdn Bhd,
                                    lines=[3], held=[2], conflicts=[1]…}
2  render_reply        189 ms  in={}                     out={reply_email=Subject: Quotation…
3  render_quote_pdf    259 ms  in={output=pdf}           out={pdf_url=https://…, s3_key=quotes/…}
4  render_review_pdf   309 ms  in={output=review, …}     out={pdf_url=…, s3_key=…}
```

---

## ③ 改进

**EN**
> "Three things I would improve.
>
> One: charts. OCR reads the labels but not the values plotted, so a drawing whose quantity only
> exists inside a bar chart is still unreadable. That needs a vision model.
>
> Two: approvals. They land in a queue and someone can approve them in the page, but nobody gets an
> email yet. That needs SES, and it is the next thing I would wire.
>
> Three: the confidence weights — ninety, seventy, sixty, forty-five — are my judgement today, not
> learned. The right version fits them to labelled quotes."

**中文**
> 三件事会改进。
>
> 第一，图表。OCR 能读到标签，读不到画在图里的数值，所以数量只写在柱状图里的图纸还是读不出来。这需要视觉模型。
>
> 第二，审批。现在会进队列、页面上可以批准，但没人收到邮件。需要 SES，是我接下来第一个要接的。
>
> 第三，可信度权重——90/70/60/45——现在是我的判断，不是学出来的。正确做法是用标注过的报价去拟合。

---

## 收尾（接下一段或结束）

**EN**
> "So: a fraction of a cent per quote, tool-level traces with input and output, and three honest gaps."

**中文**
> 一句话：一份报价不到两分钱、工具级的追踪带输入输出、三个还没补上的缺口。

---

## 三句别念错

1. 不说 "free" → **"about one Chinese fen per quote"**
2. 不说 "logs" → **"tool-level traces: which tool, how long, what went in and out"**
3. 不说 "we monitor everything" → **"two layers: platform logs, and a business trace per line"**

## 屏幕顺序（照着做）

```
1. 先在 / 报一次价（约 8 秒）
2. 打开 /cost          停 20 秒，讲数字 + 条形图
3. 打开 /traces        停 25 秒，点一条历史，指工具调用表
4. 往下滚到规则链      停 15 秒
5. 讲三个改进          停 20 秒
```
