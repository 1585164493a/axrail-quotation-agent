# 提交邮件（发给 Kelvin Kok）

## 收件人 / 主题

**To:** kelvinkok@axrail.com
**Subject:** AI Quotation Agent — take-home submission (Wu Pengxu)

---

## 正文（直接复制）

Hi Kelvin,

Thanks for the exercise — it was a good one to build against. Here is my submission:

**Repo:** https://github.com/1585164493a/axrail-quotation-agent
**Video (9m09s):** <粘贴视频链接>

In one line: an agent on AgentCore Runtime that takes a mixed-format RFQ — email body, Excel, PowerPoint, PDF, plus scans — normalises it into one structure, prices it with deterministic tools, and produces a quotation PDF, a reply draft and a review list. The model only reads text; prices, discounts, approval and confidence are code.

Three things worth pointing at:

- **The sample RFQ reproduces the brief's figures** — three priced lines, two held, 74,684 MYR. Body-only, attachments-only or both give the same total; there is a test that asserts it.
- **AgentCore usage:** Runtime for hosting, Gateway for the 14 tools over MCP with IAM auth, Memory for state. Identity, Code Interpreter, Browser and deep observability are deliberately not used — the reasoning is in the video and in `docs/answer-q1.md`.
- **Every number traces to a source row and a rule.** Anything that cannot be priced is held with the missing field named, never guessed — two of the five sample lines are held for exactly that reason.

Reproducing it locally takes three commands (README → *Run locally*) and the 178 tests run offline in about five seconds.

One thing to flag rather than hide: the AWS account I have access to is pinned to **ap-southeast-2 (Sydney)**, so that is where the demo runs. For a Malaysian customer in production I would use **ap-southeast-1 (Singapore)** — covered in the video and the README's Region section.

Happy to walk through any part of it, or to run it live.

Best regards,
Wu Pengxu (武鹏旭)
1585164493@qq.com

---

## 短版（如果你想更简短）

Hi Kelvin,

Submission for the AI quotation agent:

- Repo: https://github.com/1585164493a/axrail-quotation-agent
- Video: <链接>

It runs on AgentCore Runtime + Gateway + Memory, normalises email/Excel/PowerPoint/PDF into one structure, and prices with deterministic tools — the model only reads text. The sample RFQ reproduces 74,684 MYR with two held lines, and body-only vs attachments gives the same total (asserted by a test). 178 tests, offline, ~5 s.

Note: the account is pinned to ap-southeast-2, so the demo is deployed there; production for a Malaysian customer would be ap-southeast-1.

Happy to walk through it.

Wu Pengxu (武鹏旭)

---

## 发送前检查

- [ ] 视频链接**不需要申请访问**（YouTube 设成「不公开 / Unlisted」，不是「私人」）
- [ ] 仓库链接在**无痕窗口**打开正常（README 图片能显示）
- [ ] 视频时长在 5–10 分钟之间
- [ ] 旁白是英文
- [ ] 把正文里的 `<粘贴视频链接>` 和 `8:xx` 换成真实值
