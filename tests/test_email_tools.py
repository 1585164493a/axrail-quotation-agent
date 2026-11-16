"""list_emails / quote_email 两个工具（用假 S3，不连 AWS）。

重点：一封带三个附件（xlsx / pptx / pdf）的邮件，必须解析出与本地入库一致的报价。
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

FIXTURES = ROOT / "tests" / "fixtures"
EML = FIXTURES / "02_rfq_full_attachments.eml"


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def list_objects_v2(self, Bucket: str, Prefix: str = "", MaxKeys: int = 1000):  # noqa: N803
        contents = [
            {"Key": key, "Size": len(data),
             "LastModified": datetime(2026, 11, 15, 9, 30, tzinfo=timezone.utc)}
            for key, data in self.objects.items() if key.startswith(Prefix)
        ]
        return {"Contents": contents}

    def get_object(self, Bucket: str, Key: str):  # noqa: N803
        return {"Body": _Body(self.objects[Key])}


def call(payload: dict) -> dict:
    result = lambda_handler.handler(payload)
    body = result.get("body", result)
    return json.loads(body) if isinstance(body, str) else body


class EmailToolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["LLM_EXTRACTION"] = "0"
        cls.scratch = ROOT / ".testtmp" / "email-tools"
        cls.scratch.mkdir(parents=True, exist_ok=True)
        os.environ["SCRATCH_DIR"] = str(cls.scratch)
        cls.raw = EML.read_bytes()
        cls.fake = FakeS3({"inbox/02_rfq_full_attachments.eml": cls.raw})
        lambda_handler._s3 = lambda: cls.fake  # type: ignore[attr-defined]
        lambda_handler._email_bucket = lambda: "test-bucket"  # type: ignore[attr-defined]

    def test_list_emails_returns_subject_and_sender(self) -> None:
        out = call({"prefix": "inbox/"})
        self.assertEqual(out["count"], 1)
        email = out["emails"][0]
        self.assertEqual(email["name"], "02_rfq_full_attachments.eml")
        self.assertIn("RFQ", email["subject"].upper())
        self.assertIn("@", email["from"])

    def test_quote_email_matches_the_local_pipeline(self) -> None:
        out = call({"key": "inbox/02_rfq_full_attachments.eml"})
        self.assertEqual(len(out["lines"]), 3)
        self.assertEqual(len(out["held"]), 2)
        self.assertEqual(out["total"], 74684.0)
        self.assertTrue(out["approval"]["required"])

        # 冲突来自附件与正文对不上（图纸说 800、清单说 1000）
        self.assertTrue(any("CVR-310" in c for c in out["conflicts"]))

        source = out["source"]
        self.assertEqual(source["email_key"], "inbox/02_rfq_full_attachments.eml")
        self.assertEqual(len(source["attachments"]), 3)

    def test_quote_email_without_key_is_reported(self) -> None:
        out = call({"key": ""})
        # 空 key 识别不出工具：返回工具清单（而不是崩），调用方据此判断参数不对
        self.assertIn("tools", out)


if __name__ == "__main__":
    unittest.main()
