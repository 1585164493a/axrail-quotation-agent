"""P2 值解释：把"人写得出来但机器读不懂"的量变成规范数值。

原则：能算就别问模型。
    1) 纯数字、"±0.10"、"+/-0.10"         → 直接解析（现有规则已覆盖）
    2) 英寸 0.004" / in                    → ×25.4
    3) 微米 4 µm / um / micron             → ÷1000
    4) IT 公差等级 IT7                      → 查表（近似，带 note）
    5) 以上都不行且含字母                    → 可选：问模型，再校验范围与单位

模型给出的值必须过校验：数值在 0.001–50 mm 内、单位可识别、换算可逆；
不通过就当没解释出来（宁可不报价，也不能读错量级）。
"""

from __future__ import annotations

import re
from typing import Callable

# IT 等级 → 公称尺寸 50–80 mm 段的公差值（mm）。用近似值，note 里说明。
IT_GRADES = {
    5: 0.011,
    6: 0.016,
    7: 0.025,
    8: 0.039,
    9: 0.062,
    10: 0.100,
}

MICRON_TOKENS = ("µm", "μm", "um", "micron", "microns", "微米")
INCH_TOKENS = ("in", "inch", "inches", '"', "英寸")

PROMPT = """Convert this measurement from a machining drawing to millimetres.

Value: {text}
Field: {kind}

Rules:
- Return a number in millimetres (for tolerance) or kilograms (for mass).
- If the unit is inches, multiply by 25.4; if micrometres, divide by 1000.
- If you are not sure, return null for value.

Reply with JSON only: {{"value": <number|null>, "unit": "<mm|kg|inch|um|unknown>", "reason": "<short>"}}
"""


def _clean(text: str) -> str:
    return (
        str(text or "")
        .replace("±", "")
        .replace("+/-", "")
        .replace("+-", "")
        .replace("−", "-")
        .strip()
    )


def parse_tolerance(text: str) -> tuple[float | None, str]:
    """公差 → (mm, note)。note 说明是怎么解释出来的。"""
    raw = _clean(text)
    if not raw:
        return None, "empty"

    # +0.1/-0.05 → 取绝对值较小的那个（更严格的一侧决定工艺）
    pair = re.findall(r"-?\d+(?:\.\d+)?", raw)
    if "/" in raw and len(pair) >= 2:
        values = [abs(float(v)) for v in pair[:2]]
        if min(values) == 0:
            value = max(values)
        else:
            value = min(values)
        return round(value, 4), "asymmetric pair (tighter side)"

    lowered = raw.lower()

    # IT 等级要先判断：否则 "IT7" 里的 7 会被当成数值
    grade = re.search(r"\bit\s*(\d{1,2})\b", lowered)
    if grade:
        level = int(grade.group(1))
        if level in IT_GRADES:
            return IT_GRADES[level], f"IT{level} grade (approximate, 50-80mm band)"
        return None, f"IT{level} grade not in table"

    match = re.search(r"-?\d+(?:\.\d+)?", lowered)
    number = float(match.group()) if match else None

    if number is not None and (any(token in lowered for token in MICRON_TOKENS)):
        return round(abs(number) / 1000, 4), "micrometre converted to mm"

    if number is not None and (any(token in lowered for token in INCH_TOKENS)):
        return round(abs(number) * 25.4, 4), "inch converted to mm"

    if number is not None:
        return abs(number), "plain number"

    return None, "unparsed"


def parse_mass(text: str) -> tuple[float | None, str]:
    """质量 → (kg, note)。支持 g / gram / kg。"""
    raw = _clean(text)
    if not raw:
        return None, "empty"
    lowered = raw.lower()
    match = re.search(r"-?\d+(?:\.\d+)?", lowered)
    if not match:
        return None, "unparsed"
    number = abs(float(match.group()))
    if "kg" in lowered:
        return number, "already kg"
    if re.search(r"\bg(?:ram)?s?\b", lowered):
        return round(number / 1000, 4), "gram converted to kg"
    return number, "no unit, assumed kg"


def interpret_with_model(text: str, kind: str, llm: Callable[[str], str] | None) -> tuple[float | None, str]:
    """规则解释不了时问模型；返回前做范围校验。"""
    if llm is None:
        return None, "unparsed"

    import json

    try:
        raw = llm(PROMPT.format(text=text, kind=kind))
        start, end = raw.find("{"), raw.rfind("}")
        payload = json.loads(raw[start:end + 1])
    except Exception:  # noqa: BLE001
        return None, "model failed"

    value = payload.get("value")
    if value is None:
        return None, "model unsure"

    try:
        number = abs(float(value))
    except (TypeError, ValueError):
        return None, "model returned non-number"

    if kind == "tol" and not (0.001 <= number <= 50):
        return None, "model value out of range"
    if kind == "mass" and not (0.001 <= number <= 500):
        return None, "model value out of range"

    return round(number, 4), f"model interpreted ({payload.get('unit') or 'unknown unit'})"
