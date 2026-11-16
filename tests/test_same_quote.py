"""同一份 RFQ 的三条路径必须给同一份报价。

题目原文：
  "the same RFQ must give the same quote whatever the format"
  "live run on the sample RFQ in at least two formats
   (e.g. the email body alone, then the Excel + PowerPoint), showing the same quote"

三条路径：
  body         只有正文
  attachments  只有附件（xlsx + pptx + pdf）
  both         正文 + 附件

唯一允许的差异：只有"两边都有值"时才可能出现冲突，
所以 body 路径的冲突数可以为 0，而 attachments/both 会报出 CVR-310 数量冲突。
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
KEY = "inbox/02_rfq_full_attachments.eml"


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def list_objects_v2(self, Bucket: str, Prefix: str = "", MaxKeys: int = 1000):  # noqa: N803
        return {"Contents": [
            {"Key": k, "Size": len(v), "LastModified": datetime(2026, 11, 15, tzinfo=timezone.utc)}
            for k, v in self.objects.items() if k.startswith(Prefix)
        ]}

    def get_object(self, Bucket: str, Key: str):  # noqa: N803
        return {"Body": _Body(self.objects[Key])}


def call(payload: dict) -> dict:
    result = lambda_handler.handler(payload)
    body = result.get("body", result)
    return json.loads(body) if isinstance(body, str) else body


class SameQuoteEveryFormatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["LLM_EXTRACTION"] = "0"
        scratch = ROOT / ".testtmp" / "same-quote"
        scratch.mkdir(parents=True, exist_ok=True)
        os.environ["SCRATCH_DIR"] = str(scratch)
        lambda_handler._s3 = lambda: FakeS3({KEY: EML.read_bytes()})  # type: ignore[attr-defined]
        lambda_handler._email_bucket = lambda: "test-bucket"  # type: ignore[attr-defined]

    def _quote(self, mode: str) -> dict:
        return call({"key": KEY, "mode": mode})

    def test_all_three_paths_give_the_same_total(self) -> None:
        totals = {mode: self._quote(mode)["total"] for mode in ("body", "attachments", "both")}
        self.assertEqual(totals, {"body": 74684.0, "attachments": 74684.0, "both": 74684.0})

    def test_all_three_paths_give_the_same_lines(self) -> None:
        shapes = {}
        for mode in ("body", "attachments", "both"):
            quote = self._quote(mode)
            shapes[mode] = [(line["part_no"], line["qty"], line["unit_price"]) for line in quote["lines"]]
        self.assertEqual(shapes["body"], shapes["attachments"])
        self.assertEqual(shapes["body"], shapes["both"])

    def test_held_lines_agree_across_paths(self) -> None:
        held = {mode: sorted((h["part_no"], h["reason"]) for h in self._quote(mode)["held"])
                for mode in ("body", "attachments", "both")}
        expected = [("HSG-400", "hold_no_material"), ("SPC-050", "hold_no_qty")]
        self.assertEqual(held["body"], expected)
        self.assertEqual(held["attachments"], expected)
        self.assertEqual(held["both"], expected)

    def test_conflict_only_appears_when_two_sources_are_used(self) -> None:
        """正文单独没有冲突；附件里图纸和清单不一致，所以会报 1 个冲突。"""
        self.assertEqual(self._quote("body")["conflicts"], [])
        self.assertEqual(len(self._quote("attachments")["conflicts"]), 1)
        self.assertEqual(len(self._quote("both")["conflicts"]), 1)

    def test_attachments_only_has_no_body_lines(self) -> None:
        """附件路径下每行的 refs 不应出现 email body。"""
        for line in self._quote("attachments")["lines"]:
            self.assertFalse(any("email body" in ref for ref in line["refs"]),
                             f"{line['part_no']} 混进了正文来源: {line['refs']}")

    def test_body_only_has_no_attachment_lines(self) -> None:
        for line in self._quote("body")["lines"]:
            self.assertFalse(any(".xlsx" in ref or ".pptx" in ref or ".pdf" in ref for ref in line["refs"]),
                             f"{line['part_no']} 混进了附件来源: {line['refs']}")

    def test_mode_is_echoed_and_invalid_falls_back_to_both(self) -> None:
        self.assertEqual(self._quote("body")["mode"], "body")
        self.assertEqual(self._quote("nonsense")["mode"], "both")


if __name__ == "__main__":
    unittest.main()
