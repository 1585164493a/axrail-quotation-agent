"""报价 agent 的共享数据结构。

第一步只需要信封（Envelope，即"来了什么"）；后面的步骤会加上
CanonicalRFQ（归一化后的询价单）、定价结果和复核报告。
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Provenance:
    """一个事实的出处。每个抽取出来的字段都必须带一个。"""

    file: str
    locator: str = ""  # 单元格 / 行号 / 页码 / 幻灯片号
    raw: str = ""  # 原始文本，便于人核对

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class AttachmentRef:
    """一个附件在本地落盘后的引用。"""

    filename: str
    content_type: str
    size_bytes: int
    path: str
    sha256: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Envelope:
    """第一步的产物：一封邮件，归一化之后的样子。

    邮件是流程的唯一入口。附件是跟着邮件走的证据，但**不在这里解析**
    （解析是第二步的事）。
    """

    source: str
    message_id: str
    subject: str
    sender_name: str
    sender_email: str
    recipients: list[str]
    date: datetime | None
    body_text: str
    rfq_ids: list[str] = field(default_factory=list)
    customer_name: str = ""
    customer_email_domain: str = ""
    attachments: list[AttachmentRef] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["date"] = self.date.isoformat() if self.date else None
        return d
