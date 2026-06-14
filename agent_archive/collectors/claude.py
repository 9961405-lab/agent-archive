from __future__ import annotations
from typing import Iterable
from agent_archive.models import SessionRef, Conversation


class ClaudeCollector:
    source = "claude"

    def __init__(self, root: str | None = None):
        import os
        self.root = root or os.path.expanduser("~/.claude/projects")

    def discover(self) -> Iterable[SessionRef]:
        return []

    def parse(self, ref: SessionRef) -> Conversation:
        raise NotImplementedError
