# AXRAIL_QUOTATION_AGENT

**CNC 加工厂的报价助手** —— 客户发来一封询价邮件（正文 + Excel / PPT / PDF / 扫描件），
系统把零件抽出来、用确定性代码算价、标出要人看的东西，产出**报价单 PDF、复核清单 PDF、回信草稿**。

运行在 **Amazon Bedrock AgentCore**：Runtime 跑编排、Gateway 用 MCP 暴露工具、Memory 存状态。

> 样例询价（题目 sample）：3 行报价 + 2 行挂起 + 1 个冲突，总额 **74,684.00 MYR**。
> 只用正文 / 只用附件 / 两者都用，**金额完全一致**（`tests/test_same_quote.py`）。

---

## 1. 核心设计

### 1.1 模型只读文字，价格只出代码

分工是硬边界：

| 谁 | 做什么 | 证据 |
|---|---|---|
| **模型** | 把文字变成字段（正文兜底、表头映射、单值解释、冲突仲裁） | 四处置信标记 `llm line N` |
| **代码** | 定价、折扣、毛利、审批、可信度、PDF | 每行带 `Trace`：规则 id + 输入 + 金额 + 出处 |

为什么这么切：报价是要签字的商业文件。模型会算错、会说得像对的，同一封邮件问两次可能给两个价；
代码不会。样例里 BRK-100 的成本 **21.20** 是题目给的算例，我们算出来也是 21.20，且能在 PDF 里
逐行展开成八步：材料 7.20 + 机时 12.00 + 表面处理 1.50 + 工装分摊 0.50。

### 1.2 算不出就挂起，但挂起也要给"可行动"的信息

报不出价不等于什么都算不出。挂起时同时给出**已经能算的部分**和**还缺什么**：

```
SPC-050  数量 TBC     material 1.10 · machining 4.00 · finish 0.00   小计 5.10
                     还缺：order quantity
HSG-400  Ti Gr5 无价   finish 0.00 · setup 5.00                      小计 5.00
                     还缺：material price for Ti Gr5
                           machine rate for tolerance +/-0.005 mm
```

采购拿到这张表只需补一个数，不用回头找客户重问。HSG-400 其实踩了两个坑（钛合金没价、
公差 ±0.005 超能力），所以两条都列出来。

> 原则：**宁可挂起，不许猜。** 挂起看着不"智能"，但错价的代价远大于一句"这个要确认"。

### 1.3 冲突只报告，不替客户决定

来源权重：**结构化附件 0.90 > PDF 图纸 0.70 > 邮件正文 0.60 > 模型抽取 0.45**。
取值按权重，但冲突永远保留双方值与出处：

```
CVR-310.qty: 1000 (part_list.xlsx @ Part list!A7); 800 (drawing_CVR-310_RevB.pdf @ page 1 L13)
```

报价单、复核清单、回信三处都写明。题目原话是"**the files are the source of truth**"，
所以摘要/正文不能压过附件——但也不能悄悄选一个了事。

### 1.4 可信度是显式的，不是感觉

每个字段按来源与一致性打分，整行取**数量 / 材料 / 公差**三者的最低分：

| 情况 | 分数 |
|---|---|
| 多来源一致（**按文件算**，同一封正文被正则和模型各读一遍只算一份） | 最高权重 + 0.05×(不同文件数-1)，上限 0.99 |
| 多来源矛盾 | 0.30（同时记一条冲突） |
| 只有一个来源 | 该来源权重 |
| 缺失（含 TBC） | 0.40 |

阈值：≥0.85 high、0.55–0.85 medium、<0.55 **low → 标红 + 进审批理由**。
权重是经验判断、不是训练出来的——这点会直说。

### 1.5 结构读不出时的三级兜底（顺序不能乱）

```
规则解析失败
  → ① 结构映射（模型，P1）：说"哪一列是什么"，五道校验，按模板指纹缓存
  → ② 文本收割 / OCR（规则）：整行拼文字按特征抓；扫描页用 Rekognition
  → ③ 挂起 + 说明缺什么
```

**OCR 不属于模型那三条规则**，它是确定性兜底：按页判断（没文字层、或有图但无结构无件号），
逐页调 Amazon Rekognition `DetectText`，低于 80% 置信度的行丢弃。
OCR 会丢标点（`Bracket, AL6061` → `Bracket AL6061`），所以字段是**按内容特征抓**的，不靠逗号。

### 1.6 审批：判定在代码里，状态可流转，通知还没接

触发条件（任一）：总额 ≥ **50,000** / 折扣 > **8%** / 有挂起 / 有冲突 / 有低可信度行。

状态：`pending_manager → approved / rejected`，记录落 `s3://…/approvals/`，
页面 `/approvals` 可批准/驳回，记录里带理由、低可信度行、挂起行、冲突。

**没做的**：没有真的发邮件通知经理（发信要 SES 权限）。

---

## 2. 进程与端口拓扑

```
浏览器 :8765                  本地薄壳（tools/ui.py，只用标准库）
  └─ AgentCore Runtime        agent.py：编排，调用工具，写 Memory
       └─ AgentCore Gateway   MCP + AWS_IAM，14 个工具
            └─ Lambda         quotation-agent-tools（py3.12，13.3 MB）
                 ├─ S3        inbox/ · quotes/ · approvals/ · mapping_cache/
                 └─ 外部服务   Bedrock(可选) · Rekognition(OCR) · SSM(密钥)
```

四个页面：`/` 报价工作台 · `/inbox` 只读浏览 · `/approvals` 审批队列 · `/prices` 价格表。
界面只是壳，所有业务在 Runtime + Gateway + Lambda 里。

---

## 3. 数据层

**S3（对象）**

| 前缀 | 内容 |
|---|---|
| `inbox/` | 原始 `.eml`（含附件），原样保存 |
| `attachments/` | 从邮件里拆出来的附件，按内容哈希命名，给预签名链接 |
| `quotes/` | 报价单 PDF、复核清单 PDF |
| `approvals/` | 审批记录 JSON |
| `mapping_cache/` | 模板指纹 → 列映射（命中即不再调模型） |

**SQLite（本地管线）**：`blob_store`（内容寻址原始字节）→ `raw_email` / `raw_attachment`（信封）
→ `parse_run` / `stage_email` / `stage_block`（解析结果）→ `mart_rfq`（归一化报价）。
分层的目的：解析器改了可以对原始字节**重放**，不用请客户重发。

---

## 4. 技术栈

| 层 | 用什么 |
|---|---|
| 编排 | Python 3.13 + `bedrock-agentcore`（`BedrockAgentCoreApp`，底层 Starlette/uvicorn） |
| 工具 | Python 3.12 Lambda：openpyxl · python-pptx · python-docx · pypdf |
| 模型 | DeepSeek（OpenAI 兼容），密钥存 SSM；Bedrock 需 allowlist，本账号未开 |
| OCR | Amazon Rekognition `DetectText`（Textract 被本账号 SCP 拒绝） |
| 存储 | S3 + AgentCore Memory + 本地 SQLite |
| 界面 | 标准库 `http.server`，零前端依赖 |

**为什么两边 Python 版本不同**：Runtime 和 Lambda 是两个互不相干的运行环境，之间只传 JSON，
不共享解释器、不 pickle 对象。版本由各自平台的可用性决定：AgentCore V2 给的是 3.13，
Lambda 侧用 3.12（依赖里 lxml / Pillow 是编译扩展，包内是 **cp312 + manylinux x86_64** 的轮子；
Runtime 包内是 **cp313 + aarch64**）。唯一的风险是两边共享的 `quotation_agent` 源码要兼容两个版本——
实测同一套 174 个测试在 3.12 与 3.13 下都通过。

---

## 5. 目录

```
src/quotation_agent/
  ingest/email_reader.py   MIME → 信封 + 附件
  parsers/                 xlsx · pptx · docx · pdf · body · image
                           + ocr.py  ocr_rows.py  table_mapper.py  mapping_cache.py
  quote/                   normalise · confidence · pricing · values · arbitration · render · pdf
  store/db.py              SQLite 分层
  pipeline.py              入库 + 解析一封邮件
  lambda_handler.py        14 个 Gateway 工具
agent_runtime/agent.py     Runtime 入口（只编排）
tools/                     CLI · 网页界面 · 打包 · 部署 · 造 fixture
tests/                     174 个测试
docs/                      架构图 · AWS 部署 · 成本 · 演示脚本 · 面试稿 · 数据字典
```

---

## 6. 环境与运行

```bash
# 1) 依赖
uv sync

# 2) 本地跑通（不碰 AWS，不联网）
python tools/init_db.py --rebuild --store tests/fixtures/02_rfq_full_attachments.eml
python tools/build_quote.py --email 1        # → Total 74,684.00 MYR，2 行挂起
python tools/deliver.py --email 1            # → deliverables/<rfq>/ 下四个文件

# 3) 网页界面（需要 aws login，因为要调部署好的 Runtime）
python tools/ui.py                            # → http://127.0.0.1:8765

# 4) 测试
python -m unittest discover -s tests          # 174 个，约 4 秒

# 5) 部署（改完代码）
python tools/deploy_lambda.py                 # 打包 x86_64 → S3 → 更新代码+环境变量
python tools/deploy_runtime.py                # 打包 arm64  → S3 → 打新版本
```

模型开关（默认全开，`:0` 关闭）：`LLM_MAPPING` · `LLM_VALUES` · `LLM_ARBITRATION` · `LLM_EXTRACTION`。

---

## 7. 题目埋的六个坑，我们怎么接

| 坑 | 题目原话 | 处理 |
|---|---|---|
| 摘要不是事实来源 | "summary typed up by our sales assistant" + "the files are the source of truth" | 附件权重高于正文；冲突保留并三处披露 |
| 跨文件重复 | "same parts repeated across files" | 按件号合并，逐字段比对 |
| 数量 TBC | "Qty for the spacer to follow" | 挂起，不假设；但给出已算出的成本 |
| 材料没价 | "Other materials: no standard price" | 挂起，列出还缺什么 |
| 公差超能力 | "Tighter than ±0.02 mm: no standard rate" | 挂起，与材料缺失并列 |
| 越权折扣 | "Can you also give us 15% off" | 折扣 >8% → 审批 |

> 坦白：题目 Drive 里的四份原件我们没拿到，fixture 是按摘要复现的（数字一致）；
> 演示用的"图纸说 800"是我们额外造的冲突，用来验证冲突处理。

---

## 8. 已知限制

- 邮箱集成只有一个 IMAP 拉取脚本（QQ 实测），没做 SES 收信。
- 审批**不发邮件通知经理**，只有队列和页面。
- 图表语义读不了：OCR 只能读到图上的文字标签，读不出柱状图的数值趋势。
- 可信度权重是经验值，没有历史数据校准。
- Runtime 无状态，持久状态只在 Memory 和 S3；SQLite 仅本地。
- 样例文件是自造的，不是题目 Drive 原件。

---

## 9. 文档

| 文件 | 内容 |
|---|---|
| `README.md` | English（交付用） |
| `docs/architecture.png` / `.md` | 架构图与逐节点说明 |
| `docs/interview-script.md` | 面试稿（中英对照，含两个必答题） |
| `docs/aws-deployment.md` | AWS 资源、调用命令、拆除 |
| `docs/cost.md` | 每份报价成本、省钱杠杆 |
| `docs/demo-script.md` | 录屏分镜 |
| `docs/db-schema.xlsx` | 数据字典（10 表 / 93 字段，含来源） |
