"""Hermes (Nous Research) collector：从 ~/.hermes/state.db 取出每个 session 与 messages。

Hermes 把所有会话存在单个 SQLite 里，与 Claude/Codex 一文件一会话的模型不一样。
为了让 sync.py 的「(source, path) + (mtime, size) 增量」机制可用，discover() 时为
每个 session dump 一份 deterministic JSON 到 export_dir，dump 时把 mtime 对齐到该
session 最新消息时间——内容不变则文件 mtime/size 不变，sync 会 skip。
"""
from __future__ import annotations
import os, re, json, sqlite3, datetime
from typing import Iterable
from agent_archive.models import SessionRef, Message, Conversation
from agent_archive.collectors._util import title_snippet


class HermesCollector:
    source = "hermes"

    def __init__(self, db_path: str | None = None, export_dir: str | None = None):
        self.db_path = db_path or os.path.expanduser("~/.hermes/state.db")
        self.export_dir = export_dir or os.path.expanduser(
            "~/.cache/agent-archive/hermes")

    def _open(self):
        # 只读 URI 打开，避免锁 / 写 wal
        c = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        c.row_factory = sqlite3.Row
        return c

    def discover(self) -> Iterable[SessionRef]:
        if not os.path.exists(self.db_path):
            return
        os.makedirs(self.export_dir, exist_ok=True)
        conn = self._open()
        try:
            sessions = list(conn.execute(
                "SELECT id, source, title, started_at, ended_at, cwd, model "
                "FROM sessions WHERE archived=0 ORDER BY started_at"))
            for s in sessions:
                native_id = s["id"]
                msgs = []
                last_ts = float(s["started_at"] or 0.0)
                for m in conn.execute(
                    "SELECT role, content, tool_calls, tool_name, timestamp, "
                    "reasoning FROM messages WHERE session_id=? AND active=1 "
                    "ORDER BY timestamp, id", (native_id,)):
                    msgs.append({
                        "role": m["role"],
                        "content": m["content"] or "",
                        "tool_calls": m["tool_calls"],
                        "tool_name": m["tool_name"],
                        "timestamp": m["timestamp"],
                    })
                    if m["timestamp"]:
                        last_ts = max(last_ts, float(m["timestamp"]))
                payload = {
                    "id": native_id, "source": s["source"], "title": s["title"],
                    "started_at": s["started_at"], "ended_at": s["ended_at"],
                    "cwd": s["cwd"], "model": s["model"], "messages": msgs,
                }
                path = os.path.join(self.export_dir, _safe(native_id) + ".json")
                _write_if_changed(path, payload, last_ts)
                st = os.stat(path)
                yield SessionRef(self.source, native_id, path, st.st_mtime, st.st_size)
        finally:
            conn.close()

    def parse(self, ref: SessionRef) -> Conversation:
        with open(ref.path, encoding="utf-8") as f:
            data = json.load(f)
        messages: list[Message] = []
        first_user = first_agent = ""
        for m in data["messages"]:
            role = m["role"]
            content = (m.get("content") or "").strip()
            ts = _iso(m.get("timestamp"))
            tc_raw = m.get("tool_calls")
            if role == "tool":
                # 工具结果——保留摘要供以后 distill 判断是否做过 X，但只截 200
                messages.append(Message("tool", content[:200], ts, "tool",
                                        tool=m.get("tool_name")))
                continue
            if tc_raw:
                # assistant 发起工具调用：取第一个工具名 + 截短 args
                tool_name, args = _peek_tool_call(tc_raw)
                messages.append(Message(
                    "assistant",
                    (content or args)[:200] if (content or args) else "",
                    ts, "tool", tool=tool_name))
                # tool_calls 旁边可能也有 content 文本——若已截存就不再重复
                continue
            if role == "system":
                # 系统消息不入 prose（避免被 FTS / distill 当作内容）
                continue
            if content:
                if role == "user" and not first_user:
                    first_user = content
                elif role == "assistant" and not first_agent:
                    first_agent = content
                messages.append(Message(role, content, ts, "prose"))
        title = (data.get("title")
                 or title_snippet(first_user)
                 or title_snippet(first_agent)
                 or "(无标题)")
        return Conversation(
            id=f"{self.source}:{data['id']}", source=self.source,
            title=title, project=data.get("cwd"),
            started_at=_iso(data.get("started_at")),
            updated_at=_iso(data.get("ended_at") or data.get("started_at")),
            messages=messages, raw_ref="",
        )


def _safe(s: str) -> str:
    return re.sub(r"[^\w.-]+", "_", s).strip("_") or "untitled"


def _iso(ts) -> str | None:
    if not ts:
        return None
    try:
        return datetime.datetime.fromtimestamp(
            float(ts), tz=datetime.timezone.utc).isoformat()
    except (ValueError, OSError):
        return None


def _peek_tool_call(raw):
    try:
        calls = json.loads(raw) if isinstance(raw, str) else raw
        if isinstance(calls, list) and calls:
            c0 = calls[0]
            fn = c0.get("function") or {}
            name = fn.get("name") or c0.get("name")
            args = fn.get("arguments") or c0.get("arguments") or ""
            return name, args if isinstance(args, str) else json.dumps(args)
    except (json.JSONDecodeError, AttributeError, TypeError):
        pass
    return None, ""


def _write_if_changed(path: str, payload: dict, mtime: float) -> None:
    new = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as f:
                if f.read() == new:
                    return
        except OSError:
            pass
    with open(path, "w", encoding="utf-8") as f:
        f.write(new)
    if mtime:
        os.utime(path, (mtime, mtime))
