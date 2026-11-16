"""P1/P2/P3 的测试：模型只在"规则失效"处介入，且输出必须过校验。

P1 结构映射：错位表头的 xlsx → 规则 0 行 → 映射后 4 行；第二次命中缓存不再调模型。
P2 值解释：英寸/微米/IT 等级/非对称公差/g。
P3 冲突仲裁：建议必须指向真实存在的来源，否则丢弃。
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from quotation_agent.parsers import dispatch  # noqa: E402
from quotation_agent.parsers.mapping_cache import MemoryCache  # noqa: E402
from quotation_agent.parsers.table_mapper import (  # noqa: E402
    fingerprint,
    map_columns,
    validate_mapping,
)
from quotation_agent.quote.arbitration import suggest as arbitrate  # noqa: E402
from quotation_agent.quote.model import Conflict  # noqa: E402
from quotation_agent.quote.normalise import parse_tol  # noqa: E402
from quotation_agent.quote.values import parse_mass, parse_tolerance  # noqa: E402

XLSX = ROOT / "tests" / "fixtures" / "attachments" / "part_list_vendor_template.xlsx"

GOOD_MAPPING = {
    "header_row": 4,
    "columns": {"A": "part_no", "B": "description", "C": "material", "D": "qty",
                "E": "tol", "F": "mass", "G": "cycle", "H": "finish"},
    "units": {"D": "pcs", "E": "mm", "F": "kg", "G": "min"},
    "reason": "Item=C part number column; Matl=material; Req'd=quantity",
    "confidence": 0.86,
}


class SpyLLM:
    def __init__(self, response: dict | str) -> None:
        self.response = response
        self.calls = 0

    def __call__(self, prompt: str) -> str:
        self.calls += 1
        return self.response if isinstance(self.response, str) else json.dumps(self.response)


class TableMapperTests(unittest.TestCase):
    def test_rules_fail_without_a_mapper(self) -> None:
        result = dispatch(XLSX)
        self.assertEqual(sum(1 for b in result.blocks if b.get("row")), 0)
        self.assertTrue(any("no_table_header" in w for w in result.warnings))

    def test_mapping_rescues_the_table(self) -> None:
        spy = SpyLLM(GOOD_MAPPING)
        cache = MemoryCache()
        result = dispatch(XLSX, mapper=lambda rows: map_columns(rows, llm=spy, cache=cache))

        rows = [b["row"] for b in result.blocks if b.get("row")]
        self.assertEqual(len(rows), 4)
        self.assertEqual(str(rows[0]["Part no"]), "1")  # A 列是 Item 序号
        self.assertEqual(rows[0]["Material"], "SUS304")
        self.assertEqual(str(rows[0]["Qty"]), "250")
        self.assertTrue(any("mapping_used" in w for w in result.warnings))
        self.assertEqual(spy.calls, 1)

    def test_second_call_hits_the_cache(self) -> None:
        spy = SpyLLM(GOOD_MAPPING)
        cache = MemoryCache()
        dispatch(XLSX, mapper=lambda rows: map_columns(rows, llm=spy, cache=cache))
        dispatch(XLSX, mapper=lambda rows: map_columns(rows, llm=spy, cache=cache))
        self.assertEqual(spy.calls, 1, "第二次不应该再调模型")

    def test_invalid_mapping_is_rejected(self) -> None:
        bad = {"header_row": 4, "columns": {"A": "part_no"}, "confidence": 0.9}
        rows = [[1], [2]]
        ok, problems = validate_mapping(bad, rows, 9)
        self.assertFalse(ok)
        self.assertTrue(any("fields mapped" in p for p in problems))

        spy = SpyLLM(bad)
        self.assertIsNone(map_columns([["a"] * 9] * 3, llm=spy, cache=MemoryCache()))

    def test_out_of_range_column_is_rejected(self) -> None:
        bad = dict(GOOD_MAPPING, columns={"Z": "part_no", "A": "qty", "B": "material"})
        ok, problems = validate_mapping(bad, [["x"] * 3], 3)
        self.assertFalse(ok)
        self.assertTrue(any("out of range" in p for p in problems))

    def test_model_failure_returns_none(self) -> None:
        def boom(_prompt: str) -> str:
            raise RuntimeError("throttled")

        self.assertIsNone(map_columns([["a"] * 5] * 3, llm=boom, cache=MemoryCache()))

    def test_fingerprint_is_stable(self) -> None:
        rows = [["A", "B"], ["1", "2"]]
        self.assertEqual(fingerprint(rows), fingerprint(rows))
        self.assertNotEqual(fingerprint(rows), fingerprint([["A", "C"], ["1", "2"]]))


class ValueInterpretationTests(unittest.TestCase):
    def test_plain_and_symmetric(self) -> None:
        self.assertEqual(parse_tolerance("+/-0.10 mm")[0], 0.10)
        self.assertEqual(parse_tolerance("±0.02")[0], 0.02)

    def test_micrometre(self) -> None:
        value, note = parse_tolerance("4 µm")
        self.assertAlmostEqual(value, 0.004)
        self.assertIn("micrometre", note)

    def test_inch(self) -> None:
        value, note = parse_tolerance('0.004"')
        self.assertAlmostEqual(value, 0.1016, places=4)
        self.assertIn("inch", note)

    def test_asymmetric_takes_tighter_side(self) -> None:
        value, note = parse_tolerance("+0.10/-0.02")
        self.assertAlmostEqual(value, 0.02)
        self.assertIn("asymmetric", note)

    def test_it_grade(self) -> None:
        value, note = parse_tolerance("IT7")
        self.assertAlmostEqual(value, 0.025)
        self.assertIn("IT7", note)

    def test_unparsed_returns_none(self) -> None:
        self.assertIsNone(parse_tolerance("see drawing")[0])

    def test_mass_units(self) -> None:
        self.assertAlmostEqual(parse_mass("620 g")[0], 0.62)
        self.assertEqual(parse_mass("0.62 kg")[0], 0.62)
        self.assertEqual(parse_mass("0.5")[0], 0.5)

    def test_mass_flows_into_tolerance_helper_chain(self) -> None:
        self.assertEqual(parse_tol("4 µm"), 0.004)
        self.assertEqual(parse_tol("±0.05"), 0.05)


class ArbitrationTests(unittest.TestCase):
    def _conflict(self) -> Conflict:
        return Conflict("CVR-310", "qty", [("1000", "part_list.xlsx @ Part list!A7"),
                                           ("800", "drawing.pdf @ page 1 L13")])

    def test_suggestion_must_reference_a_real_source(self) -> None:
        good = SpyLLM({"preferred": "part_list.xlsx @ Part list!A7", "reason": "structured table"})
        result = arbitrate(self._conflict(), good)
        self.assertEqual(result["preferred"], "part_list.xlsx @ Part list!A7")

    def test_invented_source_is_rejected(self) -> None:
        bad = SpyLLM({"preferred": "the ERP system", "reason": "trust me"})
        self.assertIsNone(arbitrate(self._conflict(), bad))

    def test_no_model_means_no_suggestion(self) -> None:
        self.assertIsNone(arbitrate(self._conflict(), None))


if __name__ == "__main__":
    unittest.main()
