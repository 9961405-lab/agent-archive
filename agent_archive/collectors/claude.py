from __future__ import annotations
import os, json, glob
from typing import Iterable
from agent_archive.models import SessionRef, Message, Conversation
from agent_archive.collectors._util import title_snippet


class ClaudeCollector:
    source = "claude"

    def __init__(self, root: str | None = None):
        self.root = root or os.path.expanduser("~/.claude/projects")

    def discover(self) -> Iterable[SessionRef]:
        for path in glob.glob(os.path.join(self.root, "**", "*.jsonl"), recursive=True):
            st = os.stat(path)
            native_id = os.path.splitext(os.path.basename(path))[0]
            yield SessionRef(self.source, native_id, path, st.st_mtime, st.st_size)

    def parse(self, ref: SessionRef) -> Conversation:
        messages: list[Message] = []
        project = None
        title_user = ""
        title_asst = ""
        started_at = updated_at = None
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
                if t not in ("user", "assistant"):
                    continue  # 跳过 queue-operation/attachment/mode/last-prompt 等噪声
                ts = o.get("timestamp")
                if ts:
                    started_at = started_at or ts
                    updated_at = ts
                project = project or o.get("cwd")
                sidechain = bool(o.get("isSidechain"))
                role = o.get("message", {}).get("role", t)
                content = o.get("message", {}).get("content")
                for msg in self._blocks(role, content, ts, sidechain):
                    if msg.kind == "prose":
                        if msg.role == "user" and not title_user:
                            title_user = title_snippet(msg.text)
                        elif msg.role == "assistant" and not title_asst:
                            title_asst = title_snippet(msg.text)
                    messages.append(msg)
        return Conversation(
            id=f"{self.source}:{ref.native_id}", source=self.source,
            title=title_user or title_asst or "(无标题)", project=project,
            started_at=started_at, updated_at=updated_at,
            messages=messages, raw_ref="",
        )

    def _blocks(self, role, content, ts, sidechain):
        if isinstance(content, str):
            yield Message(role, content, ts, "sidechain" if sidechain else "prose")
            return
        if not isinstance(content, list):
            return
        for b in content:
            if not isinstance(b, dict):
                continue
            bt = b.get("type")
            if bt == "text":
                yield Message(role, b.get("text", ""), ts,
                              "sidechain" if sidechain else "prose")
            elif bt == "thinking":
                yield Message(role, b.get("thinking", ""), ts, "thinking")
            elif bt == "tool_use":
                args = json.dumps(b.get("input", {}), ensure_ascii=False)[:200]
                yield Message(role, args, ts, "tool", tool=b.get("name"))
            elif bt == "tool_result":
                c = b.get("content", "")
                if isinstance(c, list):
                    c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
                yield Message("tool", str(c), ts, "tool", tool="tool_result")
