from __future__ import annotations
import re

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
]
# 抹用户名段，含末尾无斜杠的裸路径（如 /Users/mac）
_USERPATH = re.compile(r"/Users/[^/\s]+")


def redact(text: str) -> str:
    """尽力而为地抹掉常见密钥/邮箱/用户路径。出站与模型输出回程共用。"""
    if not text:
        return text
    out = text
    for p in _PATTERNS:
        out = p.sub("[REDACTED]", out)
    out = _USERPATH.sub("/Users/[USER]", out)
    return out
