from __future__ import annotations
from typing import Iterable
from agent_archive.models import SessionRef, Conversation


class CodexCollector:
    source = "codex"

    def __init__(self, root: str | None = None, index_path: str | None = None):
        import os
        self.root = root or os.path.expanduser("~/.codex/sessions")
        self.index_path = index_path or os.path.expanduser("~/.codex/session_index.jsonl")

    def discover(self) -> Iterable[SessionRef]:
        return []

    def parse(self, ref: SessionRef) -> Conversation:
        raise NotImplementedError
