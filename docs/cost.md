# Cost plan — keeping the cost per quote low

The brief asks two cost questions: which region for a Malaysian customer's data, and how
to keep cost per quote low. This is the answer, with the arithmetic.

## Where the money actually goes

| Component | Billed on | Published rate | Share of a quote |
|---|---|---|---|
| AgentCore Runtime | active vCPU-hours + GB-hours only (model wait time is not billed) | $0.0895/vCPU-hr, $0.00945/GB-hr | ~25% |
| AgentCore Memory | $0.25 per 1,000 new events | per event | ~60% |
| Bedrock model | input + output tokens | model dependent | 15%–95% |
| S3 / ECR / CloudWatch | storage and ingest | pennies at this volume | ~10% |

Per quote, at demo volume (20 quotes a day):

```
Runtime   20 s active x 1 vCPU        = 0.0056 vCPU-hr  -> $0.00050
Memory    5 events per quote          = 0.005 k events  -> $0.00125
Model     Nova Micro, ~9k in / 1k out = 0.0004          -> $0.00040
Logs/S3   amortised                   =                  -> $0.00010
                                                          ----------
                                                          ~$0.0023 / quote
```

Two conclusions:

1. **Model choice dominates.** The same quote with a mid-tier model costs ~$0.06 — thirty
   times more. The whole optimisation effort belongs here.
2. **The pipeline itself is nearly free.** Parsing, normalising, pricing, PDF rendering are
   deterministic Python: zero tokens.

## Measured, not modelled (2026-11-16)

CloudWatch on this account, last 24 hours, function `quotation-agent-tools`:

| Metric | Value |
|---|---|
| Invocations | 461 |
| Average duration | 557 ms |
| Max duration (3 attachments + model fallback) | 8.09 s |
| Memory | 512 MB configured, 170 MB used |

AgentCore Runtime logs, same window: invocations of 2.6 s / 2.8 s / 8.7 s — a quote with
attachments and one model fallback lands around 8 seconds.

One quote, itemised (published rates, measured durations):

```
Memory    3 events (received/priced/rendered)   $0.25 / 1k events   -> $0.00075
Model     1 fallback call, ~900 in / ~250 out   DeepSeek rates      -> $0.00040
Runtime   8.7 s active, 1 vCPU / 2 GB           $0.0895/vCPU-hr     -> $0.00021
Lambda    4.8 GB-s (8 s + 3 renders x 0.5 GB)   $0.0000167/GB-s     -> $0.00008
S3        3 puts + 2 gets                       pennies             -> $0.00002
                                                                      ---------
                                                                      ~$0.0015 / quote
```

That is roughly **one Chinese cent per quote** (about 0.1-0.2 US cents). Without a model call
the deterministic path drops to about $0.0010, and Memory events are then the largest item —
which is why the levers below start with "do not call a model".

## Three levers, in order of impact

### 1. Do not call a model for work code can do

Extraction, pricing, discounting and PDF layout are deterministic and already tested.
A model call is only needed for (a) the reply email wording and (b) deciding which tool to
call next, if the orchestrator is model-driven.

Cheapest workable split:

- parsing / pricing / rendering: **no model**
- reply email: **Nova Micro** (or a template with no model at all)
- routing ("is this an RFQ?"): a few hundred tokens, or a deterministic check

That alone takes a quote from $0.06 to $0.002.

### 2. Keep the session short and the memory events few

- Runtime bills **active CPU only**; waiting for a human does not bill. Keep the idle
  timeout short so a forgotten session does not hold memory.
- Memory bills **per event**. Store one event per state transition (received, parsed,
  priced, approved), not one per block. Five events per quote, not fifty.
- Do not enable long-term memory strategies for this workload — nothing needs to be
  remembered across quotes except the customer directory.

### 3. Do not buy the fixed-cost components

The services that quietly cost $30–50 a month are the ones to avoid:

| Trap | Fixed cost | Use instead |
|---|---|---|
| NAT Gateway | ~$32/mo | no VPC egress needed; tools run in Lambda/Runtime |
| ALB / API Gateway REST | $16–20/mo | Lambda function URL or Gateway |
| Aurora Serverless v2 | ~$43/mo minimum | DynamoDB on-demand (~$0.10 at this volume) |
| Provisioned DynamoDB | capacity charge | on-demand |
| VPC endpoints per service | ~$7/mo each | only if a private network is mandated |
| Log groups without retention | grows forever | 1-day retention for the demo, 14–30 days in production |

## Monthly estimate

| | Demo (20/day) | Production (500/day) |
|---|---|---|
| Runtime | $0.30 | $7.50 |
| Memory | $0.75 | $18.75 |
| Model (Nova Micro) | $0.24 | $6.00 |
| S3 + ECR + logs | $0.40 | $12.00 |
| DynamoDB on-demand | $0.10 | $8.00 |
| **Total** | **≈ $1.80** | **≈ $52** |

The same production volume with a mid-tier model for every step is ~$1,000/month — again,
the model is the variable that matters.

## Build-phase budget: staying under $1 for the whole demo

The target is not steady-state spend but "from first deploy to finished recording, the
bill stays under one dollar". The arithmetic for that phase:

| Action | Count | Unit cost | Total |
|---|---|---|---|
| Runtime invocations (test runs + 2–3 takes of the demo) | 30 × 60 s @ 1 vCPU | $0.000025/vCPU-s | **$0.045** |
| Runtime memory | 30 × 60 s @ 0.5 GB | $0.00945/GB-hr | $0.002 |
| Memory service events | 100 events | $0.25 / 1,000 | **$0.025** |
| Model calls (Nova Micro, ~10k in / 1k out each) | 50 | $0.035 / $0.14 per M tokens | **$0.025** |
| Container image in ECR (~700 MB, prorated) | 1 | $0.10/GB-month | $0.05 |
| CloudWatch logs (~100 MB, 1-day retention) | — | $0.50/GB | $0.05 |
| Lambda (tool targets) | < 10k requests | free tier | $0.00 |
| S3 (attachments + PDFs, < 1 GB) | — | $0.023/GB-month | $0.01 |
| **Expected total** | | | **≈ $0.20** |

Three to four times of headroom under the $1 ceiling — as long as the model stays cheap.

### What would blow the budget

| Mistake | Cost |
|---|---|
| Using a mid-tier model in the loop | one quote ≈ $0.06, twenty test runs ≈ $1.20 → over budget on the model alone |
| A container image with PyTorch/transformers | 3–5 GB image, slower cold starts, more billed CPU |
| Putting the tools in a VPC with a NAT Gateway | $1.05 **per day**, before anything runs |
| Aurora or provisioned DynamoDB "for later" | $40+/month even with zero traffic |
| Redeploying the full stack ten times | each rebuild is fresh CPU seconds + image push, and multiply by re-tests |

### The order that keeps it cheap

1. **Test locally first.** All 93 tests and every demo command run without AWS — that is
   most of the iteration, at $0.
2. **Deploy once** after the local flow is stable. Slim image: `python:3.12-slim` plus
   four parser libraries, no ML stack.
3. **Model calls only where a model is needed** (reply wording, routing). Parsing and
   pricing stay deterministic — the demo path itself can run with zero tokens.
4. **Invoke sparingly**: one smoke test, then record. Runtime bills active CPU, so a
   forgotten idle session costs nothing, but a retry loop does.
5. **Delete the stack** after recording: `aws` delete of the runtime, gateway, memory and
   log groups. The deliverables live in the repo.



1. **Spend limit / budget alarm** in AWS Settings, set to a few dollars for the build phase.
2. **Log retention 1 day** on every log group created during the build.
3. **S3 lifecycle rule** expiring artefacts after 7 days.
4. **Delete the stack after recording** the demo — the deliverables stay in the repo.
5. One region only (`ap-southeast-2`): the new AWS experience pins it anyway, and any
   cross-region resource is both blocked and a cost multiplier.

## Honest caveats

- These are list-price estimates from the published rate cards, not a bill. The account's
  $100 credit covers this workload comfortably.
- Gateway and Identity pricing are not modelled here because their share at this volume is
  below the noise floor; check the pricing page before a production commitment.
- The SQLite store must become DynamoDB for a real deployment (Runtime is stateless);
  that is the one structural change this estimate assumes.
