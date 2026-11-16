"""命令行小工具。

Windows 控制台默认是 GBK，直接 print 中文会抛 UnicodeEncodeError。
所有 CLI 入口第一件事都调用 utf8_stdout()，让输出不因终端编码而崩。
"""

from __future__ import annotations

import sys


def utf8_stdout() -> None:
    """把标准输出切到 UTF-8，编不出来的字符替换掉而不是抛异常。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # 老版本或已被重定向
        pass
