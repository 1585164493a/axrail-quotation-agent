# AWS deployment

Two things in this file:

1. **How to stand this up in your own account** (the part a reviewer needs).
2. **What is live in the demo account** (IDs, so the commands below are concrete).

The agent itself is small; almost all of the work is one-time wiring.

---

## 1. Deploy it yourself

### 1.1 Prerequisites

- AWS CLI v2 with a profile that can create IAM roles, Lambda, S3 and Bedrock AgentCore resources
- Docker is **not** required (Lambda gets a zip, Runtime gets a zip with arm64 wheels)
- A region where Bedrock AgentCore is available — `ap-southeast-1` (Singapore) or
  `ap-southeast-2` (Sydney). Set it once:

```bash
export AWS_REGION=ap-southeast-1
export AWS_PROFILE=your-profile
```

### 1.2 Bucket and key

```bash
BUCKET=quotation-agent-$RANDOM
aws s3 mb "s3://$BUCKET" --region "$AWS_REGION"
```

The API key for the optional model path lives in SSM (skip if you keep `LLM_MAPPING=0` etc.):

```bash
aws ssm put-parameter --name /quotation-agent/deepseek-api-key \
  --type SecureString --value "<your-key>" --region "$AWS_REGION"
```

### 1.3 Lambda: the tools

```bash
python tools/package_lambda.py            # builds build/quotation-agent-tools.zip (x86_64 wheels)
aws s3 cp build/quotation-agent-tools.zip "s3://$BUCKET/code/quotation-agent-tools.zip"

aws iam create-role --role-name quotation-agent-lambda-role \
  --assume-role-policy-document '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"lambda.amazonaws.com"},"Action":"sts:AssumeRole"}]}'
aws iam attach-role-policy --role-name quotation-agent-lambda-role \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# S3 + Rekognition (OCR) + SSM (model key) for that role
aws iam put-role-policy --role-name quotation-agent-lambda-role --policy-name tools-access \
  --policy-document "{\"Version\":\"2012-10-17\",\"Statement\":[
    {\"Effect\":\"Allow\",\"Action\":[\"s3:GetObject\",\"s3:PutObject\",\"s3:ListBucket\"],\"Resource\":[\"arn:aws:s3:::$BUCKET\",\"arn:aws:s3:::$BUCKET/*\"]},
    {\"Effect\":\"Allow\",\"Action\":[\"rekognition:DetectText\"],\"Resource\":\"*\"},
    {\"Effect\":\"Allow\",\"Action\":[\"ssm:GetParameter\"],\"Resource\":\"*\"}]}"

aws lambda create-function --function-name quotation-agent-tools \
  --runtime python3.12 --handler quotation_agent.lambda_handler.handler \
  --memory-size 512 --timeout 60 --architectures x86_64 \
  --role "arn:aws:iam::$(aws sts get-caller-identity --query Account --output text):role/quotation-agent-lambda-role" \
  --code S3Bucket=$BUCKET,S3Key=code/quotation-agent-tools.zip \
  --environment "Variables={PDF_BUCKET=$BUCKET,EMAIL_BUCKET=$BUCKET,EMAIL_PREFIX=inbox/,SCRATCH_DIR=/tmp,MAPPING_CACHE_PREFIX=mapping_cache/}"
```

### 1.4 Gateway: expose the tools over MCP

The authorizer type is **immutable** — create it right the first time. `CUSTOM_JWT` will give
you 401 “Invalid Bearer token” when you call it with IAM credentials.

```bash
aws bedrock-agentcore-control create-gateway \
  --name quotation-agent-gw \
  --protocol-type MCP --authorizer-type AWS_IAM \
  --role-arn "arn:aws:iam::<account>:role/quotation-agent-gateway-role"

# then a target that points at the Lambda function
# the 14-tool schema is checked in as docs/gateway-tools.json — replace lambdaArn, then:
aws bedrock-agentcore-control create-gateway-target \
  --gateway-identifier <gateway-id> --name tools \
  --target-configuration file://docs/gateway-tools.json \
  --credential-provider-configurations '[{"credentialProviderType":"GATEWAY_IAM_ROLE"}]'
```

Notes learned the hard way:

- tool names become `tools___<name>`, and **the Lambda receives only the arguments** (no tool
  name), so the handler infers the tool from the argument shape;
- `toolSchema.inlinePayload` rejects `enum` — put the allowed values in the description;
- the credential configuration must be `GATEWAY_IAM_ROLE`.

### 1.5 Memory and Runtime

```bash
aws bedrock-agentcore-control create-memory --name quotation_agent_memories \
  --event-expiry-duration 7

# runtime: needs arm64 wheels, so build a separate package
python tools/deploy_runtime.py     # builds agent_runtime/deployment_package.zip (aarch64)
```

Runtime configuration: `PYTHON_3_13`, `entryPoint: ["agent.py"]`, protocol **HTTP**,
`networkMode: PUBLIC`, environment `GATEWAY_URL`, `MEMORY_ID`, `AWS_REGION`.
It needs either a role with `bedrock-agentcore:InvokeGateway` + `CreateEvent`/`ListEvents`,
or those permissions as an inline policy.

### 1.6 Redeploying after a change

```bash
python tools/deploy_lambda.py      # package → S3 → update code + env, waits for Successful
python tools/deploy_runtime.py     # package (arm64) → S3 → new runtime version, waits for READY
```

Both read `LAMBDA_FUNCTION`, `S3_BUCKET`, `RUNTIME_ID`, `RUNTIME_ROLE`, `GATEWAY_URL`,
`MEMORY_ID`, `AWS_PROFILE`, `AWS_REGION` from the environment.

### 1.7 Invoke it

```bash
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn "arn:aws:bedrock-agentcore:$AWS_REGION:<account>:runtime/<runtime-id>" \
  --runtime-session-id sess-demo-0001-abcdefghijklmnopqrstuvwxyz \
  --payload fileb://invoke.json --cli-binary-format raw-in-base64-out \
  --region "$AWS_REGION" --profile "$AWS_PROFILE" out.json
```

`invoke.json`:

```json
{"email_key": "inbox/02_rfq_full_attachments.eml", "mode": "both"}
```

or, without S3:

```json
{"rfq_no": "RFQ-2026-118", "customer": "Example Customer Sdn Bhd", "body_text": "1. BRK-100 ..."}
```

The response carries `quote` (lines with traces, held lines, conflicts, total), `reply_email`,
`quote_text`, `pdf_url`, `review_url` and `tool_calls`. Expected for the sample RFQ: 3 priced
lines, 2 held, total **74,684.00 MYR**.

### 1.8 The web UI

`tools/ui.py` is a local shell that signs requests with your credentials:

```bash
export RUNTIME_ARN="arn:aws:bedrock-agentcore:$AWS_REGION:<account>:runtime/<runtime-id>"
export AWS_PROFILE=your-profile
python tools/ui.py          # http://127.0.0.1:8765
```

It talks to **your** runtime — the ARN above is required, there is no default that works
outside the demo account.

---

## 2. What is live in the demo account

Account `187133147869`, region `ap-southeast-2` (Sydney). Everything below is in that project.

| Resource | Identifier |
|---|---|
| S3 bucket | `s3-quotation-agent` (prefixes `code/`, `inbox/`, `quotes/`, `attachments/`, `approvals/`, `mapping_cache/`) |
| Lambda | `quotation-agent-tools` — python3.12, x86_64, 512 MB, 13.3 MB zip |
| Gateway | `quotation-agent-gw-boa2n2neqb` — MCP, `AWS_IAM` |
| Gateway target | `tools` (`5BBXPA2UWC`) — Lambda target, `GATEWAY_IAM_ROLE` |
| Memory | `quotation_agent_memories-AxYJFmB7v6` — 7-day event expiry |
| Runtime | `quotation_agent-oPugo6Dgui` — `PYTHON_3_13`, HTTP, `default` endpoint |
| Lambda role | `PowerUserRole` + `AWSLambdaBasicExecutionRole` |
| Runtime role | `BedrockAgentCoreRuntimeServiceRole` + inline `gateway-and-memory` policy |

Health check from a workstation with credentials:

```bash
aws bedrock-agentcore-control list-agent-runtimes --region ap-southeast-2 --profile aws \
  --query "agentRuntimes[].{id:agentRuntimeId,status:status}" --output table
```

---

## 3. Teardown

```bash
aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id quotation_agent-oPugo6Dgui
aws bedrock-agentcore-control delete-gateway --gateway-identifier quotation-agent-gw-boa2n2neqb
aws bedrock-agentcore-control delete-memory --memory-id quotation_agent_memories-AxYJFmB7v6
aws lambda delete-function --function-name quotation-agent-tools
aws s3 rb s3://s3-quotation-agent --force
```

A named `default` endpoint must be deleted before its runtime, if you created one explicitly.

## 4. Cost note

The demo runs on the free/promo credits. Per quote the billable items are a Lambda invocation,
a few seconds of Runtime and a handful of S3 requests; the model call only happens on a
fallback. Numbers: [`cost.md`](cost.md).
