from __future__ import annotations
import os, json, glob
from typing import Iterable
from agent_archive.models import SessionRef, Message, Conversation
from agent_archive.collectors._util import title_snippet


class CodexCollector:
    source = "codex"

    def __init__(self, root: str | None = None, index_path: str | None = None):
        self.root = root or os.path.expanduser("~/.codex/sessions")
        self.index_path = index_path or os.path.expanduser("~/.codex/session_index.jsonl")
        self._title_cache: dict | None = None

    def _titles(self) -> dict:
        # 只读一次 session_index.jsonl 并缓存，避免每个 session 都重读（O(N²) I/O）
        if self._title_cache is not None:
            return self._title_cache
        titles: dict = {}
        if os.path.exists(self.index_path):
            with open(self.index_path, encoding="utf-8") as f:
                for line in f:
                    try:
                        o = json.loads(line)
                        if o.get("id") and o.get("thread_name"):
                            titles[o["id"]] = o["thread_name"]
                    except json.JSONDecodeError:
                        continue
        self._title_cache = titles
        return titles

    def discover(self) -> Iterable[SessionRef]:
        for path in glob.glob(os.path.join(self.root, "**", "rollout-*.jsonl"), recursive=True):
            st = os.stat(path)
            native_id = None
            with open(path, encoding="utf-8") as f:
                for line in f:
                    try:
                        o = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if o.get("type") == "session_meta":
                        native_id = (o.get("payload") or {}).get("id")
                        break
            if native_id:
                yield SessionRef(self.source, native_id, path, st.st_mtime, st.st_size)

    def parse(self, ref: SessionRef) -> Conversation:
        titles = self._titles()
        messages: list[Message] = []
        project = None
        started_at = updated_at = None
        first_user = ""
        first_agent = ""
        last_agent = ""
        with open(ref.path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    o = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = o.get("type")
                p = o.get("payload") or {}
                if t == "session_meta":
                    project = p.get("cwd")
                    started_at = started_at or p.get("timestamp")
                    updated_at = p.get("timestamp") or updated_at
                    continue
                if t in ("compacted", "turn_context"):
                    continue  # compacted.replacement_history 会重复历史，必须跳过
                if t != "event_msg":
                    if t == "response_item" and p.get("type") == "function_call":
                        args = (p.get("arguments") or "")[:200]
                        messages.append(Message("assistant", args, None, "tool", tool=p.get("name")))
                    continue
                pt = p.get("type")
                if pt == "user_message":
                    txt = p.get("message", "")
                    first_user = first_user or txt
                    messages.append(Message("user", txt, None, "prose"))
                elif pt == "agent_message":
                    txt = p.get("message", "")
                    first_agent = first_agent or txt
                    last_agent = txt
                    messages.append(Message("assistant", txt, None, "prose"))
                elif pt == "task_complete":
                    lam = p.get("last_agent_message", "")
                    if lam and lam != last_agent:
                        messages.append(Message("assistant", lam, None, "prose"))
        title = (titles.get(ref.native_id)
                 or title_snippet(first_user)
                 or title_snippet(first_agent)
                 or "(无标题)")
        return Conversation(
            id=f"{self.source}:{ref.native_id}", source=self.source,
            title=title, project=project,
            started_at=started_at, updated_at=updated_at,
            messages=messages, raw_ref="",
        )
