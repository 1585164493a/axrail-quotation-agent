# 必答题 1 · 口语版（照念）

> 目标：55–65 秒。短句、有停顿、带缩写。不要念表格。

## 英文（念这段）

> There are seven capabilities here. I use three.
>
> **Runtime** runs the agent. I don't manage a server, I don't manage containers — I just ship
> one file, and it gets an address, logs and scaling.
>
> **Gateway** puts my fourteen tools behind MCP, and IAM decides who can call them. So the tool
> list and the permissions live outside my business code. Adding a tool is a schema change.
>
> **Memory** keeps three things: received, priced, rendered. Runtime forgets everything between
> calls, so that's how a quote can come back tomorrow and pick up where it stopped.
>
> Now the four I don't use.
>
> **Identity** — I have one caller, me. One IAM role is enough. Just to be clear: my Gateway auth
> is IAM signatures, not the Identity service.
>
> **Observability** — I use the default CloudWatch logs, plus a small table of my own that records
> which parser version produced which row. That's enough to trace a bad quote to a cell. I didn't
> turn on tracing, because nothing here is slow enough to need it.
>
> **Code Interpreter** — no. Prices have to come from my own functions over a fixed price table.
> If I let the model run code, I lose the one promise I care about: same email, same price, every
> time.
>
> **Browser** — nothing to browse.
>
> So, short version: three for hosting, tools and state. Four left out, because they'd add surface
> without adding anything I need.

## 中文（只用来对意思）

> 七项能力，我用三项。Runtime 跑 agent：不用管服务器、不用管容器，交一个文件就有地址、日志和扩缩容。
> Gateway 把十四个工具挂在 MCP 后面，IAM 决定谁能调；工具清单和权限都在业务代码之外，加工具只改 schema。
> Memory 记三件事：收到、算完、出文件；Runtime 调用之间什么都不记，所以明天回来的报价能接着走。
>
> 另外四项不用。Identity：我只有一个调用方，一个 IAM 角色够；说清楚一点，我 Gateway 的鉴权是 IAM 签名，
> 不是 Identity 服务。Observability：只用默认的 CloudWatch 日志，加一张我自己的小表，记哪个解析器版本
> 产出了哪一行，足够追到单元格；没开追踪，因为这里没有任何一步慢到需要它。
> Code Interpreter：不行，价格必须来自我自己的函数和固定价表；让模型跑代码，我就丢了最在意的那个保证——
> 同一封邮件，永远同一个价。Browser：没有网页要抓。
>
> 一句话：托管、工具、状态用三样；另外四样不用，因为它们只会增加面积，不增加我需要的东西。

## 念的时候注意

- `IAM` 念 **I-A-M**（三个字母）
- `MCP` 念 **M-C-P**
- `fourteen tools` 别念成 "fourteen-th"；`three` / `four` 说清楚
- "Now the four I don't use." 后面停半秒，再一条条数
- 每个 ❌ 后面加一句理由就够，不要展开

## 参考对照表（不念）

| 能力 | 用没用 | 一句话理由 |
|---|---|---|
| Runtime | ✅ | 托管与扩缩容，我只交一个文件 |
| Gateway | ✅ | 工具与鉴权在业务代码之外 |
| Memory | ✅ | 记 received/priced/rendered，跨调用续上 |
| Identity | ❌ | 单调用方，IAM 角色够（鉴权走 IAM 签名） |
| Observability | ⚠️ 默认 | CloudWatch + 自建解析记录，够追到单元格 |
| Code Interpreter | ❌ | 定价必须纯函数，否则失去同价保证 |
| Browser | ❌ | 没有网页要抓 |
