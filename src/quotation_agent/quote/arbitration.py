"""P3 冲突仲裁建议：两个来源打架时，让模型说"更该信哪一份"，但不许它改数。

边界：
- 输出只能是 `values` 里已出现的某一个出处（校验不过就丢弃）；
- 结果只作为**建议**附在冲突记录上，给人参考；
- 报价仍然按来源权重取权威值，不受建议影响。
"""

from __future__ import annotations

from typing import Callable

from .model import Conflict

PROMPT = """A quotation is being built and two sources disagree.

Part: {part}
Field: {field}

{options}

Which source should the estimator trust more, and why?
Only pick one of the exact source strings above.

Reply with JSON only:
{{"preferred": "<one of the exact source strings>", "reason": "<short sentence>"}}
"""


def build_prompt(conflict: Conflict) -> str:
    options = "\n".join(f"- {value}  (from: {source})" for value, source in conflict.values)
    return PROMPT.format(part=conflict.part_no, field=conflict.field_name, options=options)


def suggest(conflict: Conflict, llm: Callable[[str], str] | None) -> dict | None:
    """返回 {"preferred": 出处, "reason": ...}；校验不过返回 None。"""
    if llm is None or not conflict.values:
        return None

    import json

    try:
        raw = llm(build_prompt(conflict))
        start, end = raw.find("{"), raw.rfind("}")
        payload = json.loads(raw[start:end + 1])
    except Exception:  # noqa: BLE001
        return None

    preferred = str(payload.get("preferred") or "").strip()
    sources = [source for _value, source in conflict.values]
    if not any(preferred == source or preferred in source or source in preferred for source in sources):
        return None

    return {"preferred": preferred, "reason": str(payload.get("reason") or "")[:200]}


def annotate(conflicts: list[Conflict], llm: Callable[[str], str] | None) -> list[dict]:
    """给每个冲突附一条建议（失败就留空，不影响主流程）。"""
    notes = []
    for conflict in conflicts:
        notes.append({
            "part_no": conflict.part_no,
            "field": conflict.field_name,
            "values": [{"value": value, "source": source} for value, source in conflict.values],
            "suggestion": suggest(conflict, llm),
        })
    return notes
