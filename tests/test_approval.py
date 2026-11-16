"""审批流：提交 → 列出 → 批复。

题目要求 "route big quotes for approval" 和 "the approval status"。
这里用内存版 S3 验证状态流转，并确认记录里带上了标记清单与理由。
"""

from __future__ import annotations

import json
import os
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("LLM_VALUES", "0")
os.environ.setdefault("LLM_ARBITRATION", "0")
os.environ.setdefault("LLM_MAPPING", "0")
os.environ.setdefault("LLM_EXTRACTION", "0")

from quotation_agent import lambda_handler  # noqa: E402

EML = ROOT / "tests" / "fixtures" / "02_rfq_full_attachments.eml"
EMAIL_KEY = "inbox/02_rfq_full_attachments.eml"


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class MemoryS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {EMAIL_KEY: EML.read_bytes()}

    def put_object(self, Bucket, Key, Body, ContentType=None):  # noqa: N803
        self.objects[Key] = Body

    def list_objects_v2(self, Bucket, Prefix="", MaxKeys=1000):  # noqa: N803
        return {"Contents": [
            {"Key": k, "Size": len(v), "LastModified": datetime.now(timezone.utc)}
            for k, v in self.objects.items() if k.startswith(Prefix)
        ]}

    def get_object(self, Bucket, Key):  # noqa: N803
        return {"Body": _Body(self.objects[Key])}


def call(payload: dict) -> dict:
    result = lambda_handler.handler(payload)
    body = result.get("body", result)
    return json.loads(body) if isinstance(body, str) else body


class ApprovalFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["LLM_EXTRACTION"] = "0"
        scratch = ROOT / ".testtmp" / "approval"
        scratch.mkdir(parents=True, exist_ok=True)
        os.environ["SCRATCH_DIR"] = str(scratch)
        cls.s3 = MemoryS3()
        lambda_handler._s3 = lambda: cls.s3  # type: ignore[attr-defined]
        lambda_handler._email_bucket = lambda: "test-bucket"  # type: ignore[attr-defined]

    def _quote(self) -> dict:
        return call({"key": EMAIL_KEY})

    def test_large_quote_is_routed_and_recorded(self) -> None:
        quote = self._quote()
        self.assertTrue(quote["approval"]["required"])

        submitted = call({"quote": quote, "submit": True, "requested_by": "pengxu"})
        self.assertEqual(submitted["status"], "pending_manager")
        self.assertTrue(submitted["s3_key"].startswith("approvals/"))

        record = json.loads(self.s3.objects[submitted["s3_key"]].decode("utf-8"))
        self.assertEqual(record["status"], "pending_manager")
        self.assertEqual(record["total"], 74684.0)
        self.assertTrue(record["reasons"])
        self.assertTrue(record["flags"])       # 低可信度的行被记下来
        self.assertTrue(record["held"])        # 挂起的行也带上
        self.assertTrue(record["conflicts"])   # 冲突也带上

    def test_list_returns_submitted_records(self) -> None:
        quote = self._quote()
        call({"quote": quote, "submit": True})
        listing = call({"list_approvals": True})
        self.assertGreaterEqual(listing["count"], 1)
        self.assertIn("status", listing["items"][0])

    def test_manager_can_approve_and_reject(self) -> None:
        quote = self._quote()
        submitted = call({"quote": quote, "submit": True})

        approved = call({"s3_key": submitted["s3_key"], "decision": "approved", "decided_by": "Kelvin"})
        self.assertEqual(approved["status"], "approved")
        self.assertEqual(approved["decided_by"], "Kelvin")

        record = json.loads(self.s3.objects[submitted["s3_key"]].decode("utf-8"))
        self.assertEqual(record["status"], "approved")
        self.assertTrue(record["decided_at"])

        rejected = call({"s3_key": submitted["s3_key"], "decision": "rejected"})
        self.assertEqual(rejected["status"], "rejected")

    def test_bad_decision_is_rejected(self) -> None:
        quote = self._quote()
        submitted = call({"quote": quote, "submit": True})
        bad = call({"s3_key": submitted["s3_key"], "decision": "maybe"})
        self.assertIn("error", bad)


if __name__ == "__main__":
    unittest.main()
