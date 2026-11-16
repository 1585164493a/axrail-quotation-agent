"""Build the AgentCore Runtime package (arm64) and roll a new runtime version.

AgentCore runs on Graviton, so the bundle must contain aarch64 wheels — the Lambda
package cannot be reused. The zip is uploaded to S3 and referenced by the runtime.

Usage:
    python tools/deploy_runtime.py                 # package + upload + update runtime
    python tools/deploy_runtime.py --skip-build    # reuse the existing zip

Configuration (env vars):
    RUNTIME_ID       quotation_agent-xxxxxxxx
    RUNTIME_ROLE     arn:aws:iam::<account>:role/service-role/<role>
    GATEWAY_URL      https://<gateway>.gateway.bedrock-agentcore.<region>.amazonaws.com/mcp
    MEMORY_ID        <memory id>
    S3_BUCKET        s3-quotation-agent
    AWS_PROFILE      aws
    AWS_REGION       ap-southeast-2
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGENT_DIR = ROOT / "agent_runtime"
STAGE = AGENT_DIR / "deployment_package"
ZIP = AGENT_DIR / "deployment_package.zip"


def build_package() -> Path:
    """Install aarch64 dependencies and zip them together with agent.py."""
    uv = shutil.which("uv") or r"D:\pythoncode\tools\uv\uv.exe"
    if STAGE.exists():
        shutil.rmtree(STAGE)
    subprocess.run(
        [uv, "pip", "install", "--python-platform", "aarch64-manylinux2014",
         "--python-version", "3.13", "--target", str(STAGE), "--only-binary", ":all:",
         "-r", str(AGENT_DIR / "requirements.txt")],
        check=True,
    )
    if ZIP.exists():
        ZIP.unlink()
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED) as bundle:
        for path in STAGE.rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts:
                bundle.write(path, path.relative_to(STAGE))
        bundle.write(AGENT_DIR / "agent.py", "agent.py")
    return ZIP


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy the agent to AgentCore Runtime")
    parser.add_argument("--skip-build", action="store_true")
    args = parser.parse_args()

    runtime_id = os.environ.get("RUNTIME_ID")
    role_arn = os.environ.get("RUNTIME_ROLE")
    gateway_url = os.environ.get("GATEWAY_URL")
    memory_id = os.environ.get("MEMORY_ID", "")
    bucket = os.environ.get("S3_BUCKET", "s3-quotation-agent")
    region = os.environ.get("AWS_REGION", "ap-southeast-2")
    profile = os.environ.get("AWS_PROFILE", "aws")

    missing = [name for name, value in (("RUNTIME_ID", runtime_id), ("RUNTIME_ROLE", role_arn),
                                        ("GATEWAY_URL", gateway_url)) if not value]
    if missing:
        print("missing environment variables:", ", ".join(missing))
        return 2

    if not args.skip_build:
        build_package()

    import boto3
    from botocore.config import Config

    config = Config(retries={"max_attempts": 8, "mode": "adaptive"}, read_timeout=300)
    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3", config=config)
    control = session.client("bedrock-agentcore-control", config=config)

    key = "code/deployment_package.zip"
    print(f"uploading {ZIP.stat().st_size / 1024 / 1024:.1f} MB to s3://{bucket}/{key}")
    s3.upload_file(str(ZIP), bucket, key)

    control.update_agent_runtime(
        agentRuntimeId=runtime_id,
        agentRuntimeArtifact={
            "codeConfiguration": {
                "code": {"s3": {"bucket": bucket, "prefix": key}},
                "runtime": "PYTHON_3_13",
                "entryPoint": ["agent.py"],
            }
        },
        roleArn=role_arn,
        networkConfiguration={"networkMode": "PUBLIC"},
        protocolConfiguration={"serverProtocol": "HTTP"},
        environmentVariables={"GATEWAY_URL": gateway_url, "MEMORY_ID": memory_id, "AWS_REGION": region},
    )
    print("runtime update requested, waiting for READY ...")

    for _ in range(80):
        status = control.get_agent_runtime(agentRuntimeId=runtime_id)["status"]
        print("  status:", status)
        if status == "READY":
            return 0
        if "FAILED" in status:
            return 1
        time.sleep(15)

    print("timed out")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
