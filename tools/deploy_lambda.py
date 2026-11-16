"""Build the Lambda package and deploy it (code + environment variables).

Usage:
    python tools/deploy_lambda.py                 # package + upload + update code
    python tools/deploy_lambda.py --env-only      # only refresh environment variables

Configuration (env vars, with defaults for this project):
    LAMBDA_FUNCTION   quotation-agent-tools
    S3_BUCKET         s3-quotation-agent
    S3_KEY            code/quotation-agent-tools.zip
    AWS_PROFILE       aws
    AWS_REGION        ap-southeast-2
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

BASE_ENV = {
    "PDF_BUCKET": "{bucket}",
    "EMAIL_BUCKET": "{bucket}",
    "EMAIL_PREFIX": "inbox/",
    "LLM_PROVIDER": "openai",
    "LLM_BASE_URL": "https://api.deepseek.com/v1",
    "LLM_MODEL": "deepseek-chat",
    "LLM_KEY_PARAM": "/quotation-agent/deepseek-api-key",
    "LLM_MAPPING": "1",
    "LLM_VALUES": "1",
    "LLM_ARBITRATION": "1",
    "MAPPING_CACHE_PREFIX": "mapping_cache/",
    "SCRATCH_DIR": "/tmp",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Deploy the quotation tools to AWS Lambda")
    parser.add_argument("--env-only", action="store_true", help="skip code upload")
    args = parser.parse_args()

    function = os.environ.get("LAMBDA_FUNCTION", "quotation-agent-tools")
    bucket = os.environ.get("S3_BUCKET", "s3-quotation-agent")
    key = os.environ.get("S3_KEY", "code/quotation-agent-tools.zip")
    region = os.environ.get("AWS_REGION", "ap-southeast-2")
    profile = os.environ.get("AWS_PROFILE", "aws")

    import boto3
    from botocore.config import Config

    config = Config(retries={"max_attempts": 8, "mode": "adaptive"}, read_timeout=300)
    session = boto3.Session(profile_name=profile, region_name=region)
    s3 = session.client("s3", config=config)
    lam = session.client("lambda", config=config)

    if not args.env_only:
        subprocess.run([sys.executable, str(ROOT / "tools" / "package_lambda.py")], check=True)
        zip_path = ROOT / "build" / "quotation-agent-tools.zip"
        print(f"uploading {zip_path.stat().st_size / 1024 / 1024:.1f} MB to s3://{bucket}/{key}")
        s3.upload_file(str(zip_path), bucket, key)
        lam.update_function_code(FunctionName=function, S3Bucket=bucket, S3Key=key)
        print("code update requested")

    variables = {name: value.format(bucket=bucket) for name, value in BASE_ENV.items()}
    lam.get_function_configuration(FunctionName=function)  # fail fast if it does not exist
    lam.update_function_configuration(FunctionName=function, Environment={"Variables": variables})
    print("environment update requested")

    for _ in range(60):
        status = lam.get_function_configuration(FunctionName=function).get("LastUpdateStatus")
        if status == "Successful":
            print("lambda ready")
            return 0
        if status == "Failed":
            print("update failed; check CloudWatch logs")
            return 1
        time.sleep(3)

    print("timed out waiting for the update")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
