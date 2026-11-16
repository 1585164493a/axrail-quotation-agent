# 必答题 2 · 口语版（照念）

> 目标：45–55 秒，句子短、有停顿、用缩写。不要念表格。

## 英文（念这段）

> Before this, I built a supply-chain assistant on LangGraph. That's the stack I know from
> production.
>
> Six sub-agents, all defined in YAML. Some agents could only read, two could write, and every
> write had to be approved by a person. Twenty-three tools behind an MCP server. A sandbox per
> user. And Mongo to keep the state.
>
> What do I keep from that? Three things.
>
> **One:** the flow is visible. You can see every step, and you can test each one on its own.
> My eight steps here are written the same way.
>
> **Two:** tools are just functions. Nothing magic. And every one has a test.
>
> **Three:** a person has to say yes. Writes there — big quotes here.
>
> What do I replace? Also three.
>
> **Hosting.** Before, I ran containers on a VM, and I had to start four services in the right
> order. Now it's one file — agent dot py — and Runtime runs it.
>
> **The tool boundary.** Before, the tools lived inside the app, and I checked permissions in my
> own code. Now Gateway exposes them, and IAM decides who can call.
>
> **State.** Before, Mongo remembered where the graph was. Now Memory remembers what happened:
> received, priced, rendered. That's more useful to me — I can change the pipeline, and the
> history still makes sense.
>
> One thing I didn't bring over: a framework. This flow is straight-line. No branches, no
> sub-agents. Eight plain functions with tests are easier to explain than a graph. If it ever
> branches, I'll bring the graph back.

## 中文（只用来对意思）

> 之前我做过供应链助手，用的是 LangGraph。六个子 agent，全部 YAML 定义。有的只能读，两个能写，
> 所有写操作都要人批。二十三个工具，挂在一个 MCP server 后面。每个用户一个沙箱。状态存在 Mongo。
>
> 留什么？三样。第一，流程看得见，每一步都能单独测——我这里八步是同样写法。第二，工具就是普通函数，每个都有测试。
> 第三，必须有人点头：那边是写操作，这边是大额报价。
>
> 换什么？也是三样。托管：以前自己在 VM 上跑容器、还要按顺序起四个服务，现在就一个文件，Runtime 跑。
> 工具边界：以前工具在应用里、权限我自己查，现在 Gateway 暴露、IAM 判谁能调。
> 状态：以前 Mongo 记图跑到哪儿，现在 Memory 记发生了什么——收到、算完、出文件。这个更有用，
> 因为我改了流程，历史记录照样看得懂。
>
> 有一件我故意没带过来：框架。这条链路是直的，没有分支、没有子 agent。
> 八个普通函数加测试，比一张图好解释。哪天真有分支，我再把图请回来。

## 念的时候注意

- `LangGraph` 念 **Lang-graph**（两个词分开，重音在前）
- `checkpointer` 不用念，这个口语版里已经去掉了；说 **Mongo kept the state**
- `sub-agents` 念 **sub-AY-gents**
- `IAM` 念 **I-A-M**，三个字母分开
- 数字都拆开念：**twenty-three tools**、**six sub-agents**、**eight steps**
- 破折号处停半秒，尤其 "Writes there — big quotes here" 和 "agent dot py — and Runtime runs it"

## 参考对照表（不念，忘了能看一眼）

| 维度 | LangGraph 生产栈 | 现在 |
|---|---|---|
| 编排 | `StateGraph` + 子图路由 | 八层纯函数顺序调用 |
| 工具 | 进程内 `@tool`，权限代码自查 | Lambda + Gateway(MCP) + IAM |
| 状态 | Mongo checkpointer（图到哪） | Memory 事件（发生了什么） |
| 人工中断 | `interrupt_on` | 审批记录 + 页面操作 |
| 运行 | 容器 + VM + 启动顺序 | Runtime 托管 |
| 代码执行 | per-user 沙箱（真实需要） | 不用（定价是固定公式） |
| 启动校验 | YAML 工具名、写工具登记 | 五道映射校验、范围校验 |
| 可观测 | 自建日志 + Langfuse | CloudWatch + `parse_run` 表 |
