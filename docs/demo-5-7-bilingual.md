# 5:00–7:00 问题段 · 中英双版（逐段对应）

> 题目要求把这一段拆成三问：**what it decided / what it asked a person / what you assumed**。
> 下面每一段先英文（录屏念这个），再中文（同义全文，可当字幕或口头版）。
> 对应字幕：第 24–39 条（5:00–7:00）。

---

## 开场过渡

**EN**
> That is the happy path. Now the problems — and I'll split them three ways: what it decided,
> what it asked a person, and what I assumed.

**中文**
> 顺利的部分讲完了。现在讲问题，我按三段来说：它自己决定了什么、它问了人什么、我假设了什么。

---

## ① What it decided（它自己决定的）

**EN**
> First, what it decided on its own.
>
> Quantity comes from the most authoritative document — drawing first, then spreadsheet, then email.
> Discount comes from the quantity tier: five percent from five hundred pieces, eight from a thousand.
> If a line cannot be priced, it is held. Not guessed.
> And if the total or the discount crosses policy, it routes itself to approval.

**中文**
> 第一段，它自己决定的。
>
> 数量取最权威的那份文件：图纸优先，其次表格，最后邮件正文。
> 折扣来自数量档位：五百件打 5%，一千件打 8%。
> 某一行的价算不出来，就挂起，绝不猜。
> 总额或折扣越过政策线，它自己就走进审批流程。

**屏幕**：停在格式 B 的报价表，指报价行与总额。

---

## ② What it asked a person（它问了人什么）

**EN**
> Second, what it asked a person.
>
> The spacer: quantity still to follow, so the setup cost cannot be spread. It is held, and the reply
> asks the buyer for the number.
>
> The valve housing: titanium grade five is not on our price list, and the tolerance is tighter than
> any standard rate. Two gaps on one line — that goes to procurement and engineering.
>
> CVR-310: the drawing says eight hundred, the spreadsheets say a thousand. It quotes the weighted
> source and flags the conflict for a human to confirm.
>
> And the fifteen percent discount: that is above our eight percent ceiling, so the sales manager decides.

**中文**
> 第二段，它问了人什么。
>
> 垫片：数量还在等客户确认，工装费没法分摊到每一件。所以这一行挂起，回信里向客户要这个数字。
>
> 阀体：钛合金五级不在我们的价表上，公差又比任何标准费率都紧。一行上两个缺口——这条转给采购和工程。
>
> CVR-310：图纸写八百，两份表格写一千。它按权重取数，同时把冲突标出来，等人确认。
>
> 还有那 15% 的折扣：超过了我们 8% 的上限，交给销售经理决定。

**屏幕**：依次指 SPC-050、HSG-400、CVR-310 三行；最后切 `/approvals` 停在 PENDING MANAGER。

---

## ③ What I assumed（我假设了什么）

**EN**
> Third, what I assumed — because the brief leaves these open.
>
> Thirty days validity. Twenty-five percent is a gross margin, so the selling price is cost divided
> by zero point seven five — not cost plus twenty-five percent.
> The tier applies per line, from that line's own quantity.
> Fifty thousand ringgit is where a manager signs, and eight percent is the discount ceiling.
> And a missing value is held, never filled in.
>
> All of it is in the README, not buried in code.

**中文**
> 第三段，我假设了什么——因为题目把这些留空了。
>
> 报价有效期三十天。25% 指的是毛利率，所以售价是成本除以 0.75，而不是成本加 25%。
> 档位按每一行自己的数量计算。
> 五万马币是经理签字的线，8% 是折扣上限。
> 缺失的值一律挂起，绝不替客户补一个。
>
> 这些都写在 README 里，没有埋在代码里。

**屏幕**：停在报价页，或切到 README 的 known limits 一屏。

---

## 收尾一句（可选，接在第三段后面）

**EN**
> So the split is simple: rules handle what the documents say, a person handles what the documents
> don't, and I wrote down everything in between.

**中文**
> 所以边界很简单：文件里写得清楚的，规则处理；文件里没有的，交给人；中间那些我拿不准的，全部写成假设。

---

## 数字速查（念的时候看这行）

| 项 | 数值 | 归属 |
|---|---|---|
| 三行报价总额 | 74,684.00 MYR | 规则算出 |
| BRK-100 单价 | 26.86（成本 21.20） | 规则算出 |
| 档位 | 500 件 5% · 1000 件 8% | 规则 |
| 审批线 | 50,000 MYR | **假设** |
| 折扣上限 | 8% | **假设** |
| 有效期 | 30 天 | **假设** |
| 毛利率 | 25%（售价 = 成本 ÷ 0.75） | **假设** |
| 挂起 | SPC-050（数量待定）· HSG-400（钛合金无价 + 公差超能力） | 问人 |
| 冲突 | CVR-310：1000 vs 800 | 问人 |
| 折扣请求 | 15%（超 8%） | 问经理 |
