"""第二步：把附件切成"块"。

解析器只做一件事——把文件读成带出处的最小单位，不判断业务含义：

    {"block_type": "table_row", "locator": "Part list!A5", "ordinal": 5,
     "row": {"Line": 1, "Part no": "BRK-100", "Qty": 500}}

职责边界：
- 解析器负责：读文件、找表格、切行、给每个块标 locator
- 解析器不负责：判断数量冲突、映射材料名、算价格（那是第三步）
"""

from .base import ParseResult, dispatch

__all__ = ["ParseResult", "dispatch"]
