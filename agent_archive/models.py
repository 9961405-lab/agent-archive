from __future__ import annotations
from dataclasses import dataclass
from functools import cached_property
import hashlib


@dataclass
class SessionRef:
    source: str
    native_id: str
    path: str          # 原始文件绝对路径
    mtime: float
    size: int


@dataclass
class Message:
    role: str                  # user | assistant | tool | system
    text: str
    ts: str | None = None      # ISO8601 UTC
    kind: str = "prose"        # prose | thinking | tool | sidechain
    tool: str | None = None


@dataclass
class Conversation:
    id: str                    # f"{source}:{native_id}"
    source: str
    title: str
    project: str | None
    started_at: str | None
    updated_at: str | None
    messages: list[Message]
    raw_ref: str

    @property
    def message_count(self) -> int:
        return len(self.messages)

    @cached_property
    def content_hash(self) -> str:
        # parse 后 messages 不再变，缓存避免 sync 里重复 O(n) 重算 SHA256
        h = hashlib.sha256()
        for m in self.messages:
            if m.kind == "prose":
                h.update(m.role.encode("utf-8"))
                h.update(b"\n")
                h.update(m.text.encode("utf-8"))
                h.update(b"\x00")
        return h.hexdigest()
