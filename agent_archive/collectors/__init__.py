from __future__ import annotations
from typing import Protocol, Iterable, runtime_checkable
from agent_archive.models import SessionRef, Conversation


@runtime_checkable
class Collector(Protocol):
    source: str
    def discover(self) -> Iterable[SessionRef]: ...
    def parse(self, ref: SessionRef) -> Conversation: ...


def get_collectors(only: str | None = None) -> list[Collector]:
    from agent_archive.collectors.claude import ClaudeCollector
    from agent_archive.collectors.codex import CodexCollector
    from agent_archive.collectors.hermes import HermesCollector
    cols: list[Collector] = [ClaudeCollector(), CodexCollector(), HermesCollector()]
    if only:
        cols = [c for c in cols if c.source == only]
    return cols
