"""客户身份识别：这封询价是哪家公司、哪个人发来的。

为什么要单独一层：邮件里的"客户是谁"没有唯一可靠字段。
- 发件邮箱域名还可能被公共邮箱（gmail / qq）冲淡；
- 签名块有时只写名字，有时干脆没有；
- 但图纸标题栏、报价单抬头这类**受控文件**通常写得很规范。

所以这里把每条线索当作"证据"，累计权重后给一个结论和置信度；
证据互相矛盾时不下结论，交人确认——和定价那边"算不出就挂起"是同一套纪律。

对外只有两个入口：
    resolve_customer(envelope, attachment_texts=None, directory=None)
    python -m quotation_agent.identity <文件.eml>
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass, field
from difflib import SequenceMatcher

from .ingest.email_reader import COMPANY_NAME_RE, read_eml
from .models import Envelope

# 公共邮箱域名：拿它当公司标识会认错人，直接不参与判断
PUBLIC_DOMAINS = {
    "gmail.com", "googlemail.com", "qq.com", "foxmail.com", "163.com", "126.com",
    "outlook.com", "hotmail.com", "live.com", "yahoo.com", "sina.com", "sohu.com",
    "icloud.com", "proton.me", "protonmail.com",
}

# 各类证据的权重。目录（历史客户库）最硬，签名最软。
WEIGHT_DIRECTORY = 0.60
WEIGHT_ATTACHMENT = 0.30
WEIGHT_SIGNATURE = 0.20

# 判定阈值（权重之和的分界，说明见 README）
CONFLICT_MIN_WEIGHT = 0.15  # 任何一条真实证据（最弱是签名 0.2）指向另一家公司，就算打架
HIGH_MIN_SCORE = 0.45  # 目录单独命中(0.6) 或 签名+附件(0.5) 都算高
MEDIUM_MIN_SCORE = 0.20  # 只有签名(0.2) 算中等，可用但要记一笔


@dataclass
class Signal:
    """一条证据：来自哪里、指向哪家公司、值多少分。"""

    kind: str  # directory / attachment_title / signature / domain
    value: str
    source: str
    weight: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class CustomerResolution:
    """识别结果。

    level 的取值：
      high         -> 可以自动往下走
      medium       -> 可以用，但要在 assumptions 里记一笔
      needs_review -> 证据不足或互相矛盾，必须人看
      draft        -> 完全没线索，建"待确认客户"草稿
    """

    company: str
    contact_name: str
    contact_email: str
    domain: str
    level: str
    confidence: float
    signals: list[Signal] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["signals"] = [s.to_dict() for s in self.signals]
        return d


def _norm_company(name: str) -> str:
    """公司名归一化：小写、去标点、压空格、统一常见后缀写法。"""
    s = name.lower().strip()
    s = re.sub(r"[\.,;:()（）\[\]{}'\"&]", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = s.replace("sdn bhd", "sdn bhd").replace("sdn. bhd", "sdn bhd")
    s = s.replace("pte ltd", "pte ltd").replace("pte. ltd", "pte ltd")
    return s.strip()


def _same_company(a: str, b: str) -> bool:
    """两个公司名是否指同一家（容忍缩写与大小写差异）。"""
    na, nb = _norm_company(a), _norm_company(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.9


def _company_from_title_line(text: str) -> str | None:
    """从附件文本（图纸标题栏、表格抬头）里抓公司名。

    只看前几行：标题栏在顶部，正文里出现的公司名可能是供应商或无关引用。
    """
    for line in text.splitlines()[:8]:
        match = COMPANY_NAME_RE.search(line.strip())
        if match:
            return match.group(1).strip()
    return None


def resolve_customer(
    envelope: Envelope,
    attachment_texts: dict[str, str] | None = None,
    directory: dict[str, str] | None = None,
) -> CustomerResolution:
    """综合邮件头、签名、附件标题栏和历史客户库，判定客户身份。

    参数：
        envelope:         第一步产出的邮件信封
        attachment_texts: {文件名: 文本}，由第二步的解析器提供；没有就只靠邮件本身
        directory:        {邮箱或域名: 公司名}，来自历史客户库
    """
    signals: list[Signal] = []
    notes: list[str] = []
    domain = envelope.customer_email_domain.lower()

    # ---- 证据 1：历史客户库（按邮箱精确、再按域名）----
    if directory:
        hit = directory.get(envelope.sender_email.lower()) or directory.get(domain)
        if hit:
            signals.append(Signal("directory", hit, envelope.sender_email or domain, WEIGHT_DIRECTORY))

    # ---- 证据 2：签名块里的公司名（第一步已经抓过）----
    if envelope.customer_name:
        signals.append(Signal("signature", envelope.customer_name, "email body / signature", WEIGHT_SIGNATURE))

    # ---- 证据 3：附件标题栏 ----
    for filename, text in (attachment_texts or {}).items():
        name = _company_from_title_line(text or "")
        if name:
            signals.append(Signal("attachment_title", name, filename, WEIGHT_ATTACHMENT))

    # ---- 证据 4：企业邮箱域名（只作提示，不给权重）----
    if domain and domain not in PUBLIC_DOMAINS:
        notes.append(f"sender domain {domain} (corporate domain, supporting hint only)")
    elif domain:
        notes.append(f"sender domain {domain} is a public mailbox and cannot identify the company")

    # ---- 汇总：按"是不是同一家公司"归组，累加权重 ----
    groups: list[dict] = []
    for sig in signals:
        merged = False
        for group in groups:
            if _same_company(group["name"], sig.value):
                group["score"] += sig.weight
                group["signals"].append(sig)
                merged = True
                break
        if not merged:
            groups.append({"name": sig.value, "score": sig.weight, "signals": [sig]})

    groups.sort(key=lambda g: (g["score"], len(g["signals"])), reverse=True)

    contact_name = envelope.sender_name or envelope.sender_email.split("@")[0]
    contact_email = envelope.sender_email

    if not groups:
        return CustomerResolution(
            company="",
            contact_name=contact_name,
            contact_email=contact_email,
            domain=domain,
            level="draft",
            confidence=0.0,
            signals=signals,
            notes=notes + ["no company evidence at all; a pending-customer draft is created for sales to confirm"],
        )

    best = groups[0]
    rivals = [g for g in groups[1:] if g["score"] >= CONFLICT_MIN_WEIGHT]
    conflicts = [
        f"company mismatch: {best['name']} ({best['score']:.2f}) vs {r['name']} ({r['score']:.2f})"
        for r in rivals
    ]

    score = min(best["score"], 1.0)
    if conflicts:
        level = "needs_review"
        notes.append("evidence contradicts itself; not choosing automatically, needs a human")
    elif score >= HIGH_MIN_SCORE:
        level = "high"
    elif score >= MEDIUM_MIN_SCORE:
        level = "medium"
    else:
        level = "needs_review"
        notes.append("only a single weak signal; confirm the customer name manually")

    return CustomerResolution(
        company=best["name"],
        contact_name=contact_name,
        contact_email=contact_email,
        domain=domain,
        level=level,
        confidence=round(score, 2),
        signals=signals,
        conflicts=conflicts,
        notes=notes,
    )


def main(argv: list[str] | None = None) -> int:
    from .cli_util import utf8_stdout

    utf8_stdout()
    ap = argparse.ArgumentParser(description="客户身份识别：判定询价来自哪家公司/哪个人。")
    ap.add_argument("eml", help=".eml 文件路径")
    ap.add_argument("--staging", default="artifacts", help="附件落盘目录")
    args = ap.parse_args(argv)

    envelope = read_eml(args.eml, args.staging)
    # 第二步的解析器还没接上，先只用邮件本身的证据
    result = resolve_customer(envelope)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
