# AWS deployment — what is live

Account `187133147869`, region `ap-southeast-2` (Sydney). All resources are in the demo
project; nothing is provisioned outside it.

## Resources

| Resource | ID / ARN | Notes |
|---|---|---|
| S3 bucket | `quotation-agent-187133147869-sea` | holds the agent zip and the tool package |
| Lambda | `arn:aws:lambda:ap-southeast-2:187133147869:function:quotation-agent-tools` | `price_line` / `build_quote` / `render_reply`, 13.3 MB zip, python3.12 |
| Gateway | `quotation-agent-gw-yy8w6mx3q8` | MCP, AWS_IAM auth, URL `.../mcp` |
| Gateway target | `tools` (id `OUEIXEWG7I`) | Lambda target, tools exposed as `tools___price_line` etc. |
| Memory | `quotation_agent_memory-Iz1TsXEzPI` | 7-day event expiry |
| Runtime | `quotation_agent-0h8NRaEcLj` (v5) | direct code deploy from S3, `PYTHON_3_13`, HTTP protocol |
| Runtime endpoint | `default` | invocable |
| IAM roles | `quotation-agent-lambda-role`, `quotation-agent-runtime-role` | inline policies, no admin |

## Invoke it

```bash
aws bedrock-agentcore invoke-agent-runtime \
  --agent-runtime-arn arn:aws:bedrock-agentcore:ap-southeast-2:187133147869:runtime/quotation_agent-0h8NRaEcLj \
  --runtime-session-id sess-demo-0001-abcdefghijklmnopqrstuvwxyz \
  --payload fileb://invoke.json \
  --cli-binary-format raw-in-base64-out \
  --region ap-southeast-2 --profile aws out.json
```

`invoke.json`:

```json
{"rfq_no": "RFQ-2026-118", "customer": "Example Customer Sdn Bhd", "body_text": "1. BRK-100 ..."}
```

The response carries `quote` (lines with traces, held lines, conflicts, total),
`reply_email` and `quote_text`. Expected for the sample RFQ: 3 priced lines,
2 held, total **74,684.00 MYR**.

## How it is wired

```
invoke-agent-runtime
      │  HTTP /invocations
      ▼
AgentCore Runtime (agent.py: orchestration only, no arithmetic)
      │  SigV4 signed JSON-RPC over MCP
      ▼
AgentCore Gateway (AWS_IAM)
      │  Lambda target
      ▼
Lambda quotation-agent-tools  →  price_line / build_quote / render_reply
      │
      └─ AgentCore Memory  (state transitions: received → priced → rendered)
```

## What is not done yet

- **Memory writes are not landing.** The agent calls `create_event`, the invocation
  succeeds, but `list-events` returns nothing; the call appears to be skipped or rejected
  inside the runtime. Reading/writing the same memory from the CLI works, so the resource
  and the API contract are fine — it is the in-runtime call that needs debugging.
- No model call anywhere in this path: parsing, pricing and PDF rendering are deterministic,
  so the demo costs only runtime seconds and Lambda invocations.
- The PDF is still produced locally (`tools/deliver.py`); putting it behind the Gateway is
  the next tool to add.

## Cleanup

```bash
aws bedrock-agentcore-control delete-agent-runtime --agent-runtime-id quotation_agent-0h8NRaEcLj
aws bedrock-agentcore-control delete-gateway --gateway-identifier quotation-agent-gw-yy8w6mx3q8
aws bedrock-agentcore-control delete-memory --memory-id quotation_agent_memory-Iz1TsXEzPI
aws lambda delete-function --function-name quotation-agent-tools
aws s3 rb s3://quotation-agent-187133147869-sea --force
aws iam delete-role-policy --role-name quotation-agent-runtime-role --policy-name runtime-policy
aws iam delete-role --role-name quotation-agent-runtime-role
aws iam delete-role-policy --role-name quotation-agent-lambda-role --policy-name invoke-tools
aws iam detach-role-policy --role-name quotation-agent-lambda-role --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole
aws iam delete-role --role-name quotation-agent-lambda-role
```

## Deploy scripts in the repo

`tools/package_lambda.py` builds the Lambda zip from Linux wheels;
`agent_runtime/agent.py` is the runtime entry point;
`agent_runtime/deploy_notes.md` records the exact CLI calls used.
