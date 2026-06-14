from __future__ import annotations
from agent_archive.models import Conversation, Message

MD_TRUNCATE_BYTES = 2048


def _truncate(text: str) -> str:
    b = text.encode("utf-8")
    if len(b) <= MD_TRUNCATE_BYTES:
        return text
    return b[:MD_TRUNCATE_BYTES].decode("utf-8", "ignore") + "\n…[截断，完整见 raw]"


def _render_msg(m: Message) -> str:
    if m.kind == "thinking":
        return f"<details><summary>💭 thinking</summary>\n\n{_truncate(m.text)}\n\n</details>"
    if m.kind == "tool":
        return f"> 🔧 {m.tool or 'tool'} `{_truncate(m.text)}`"
    prefix = "🧑 **User**" if m.role == "user" else (
        "🤖 **Assistant**" if m.role == "assistant" else f"**{m.role}**")
    if m.kind == "sidechain":
        prefix = "↳ " + prefix
    return f"{prefix}\n\n{_truncate(m.text)}"


def render_markdown(conv: Conversation) -> str:
    fm = [
        "---",
        f"id: {conv.id}",
        f"source: {conv.source}",
        f"title: {conv.title}",
        f"project: {conv.project or ''}",
        f"started_at: {conv.started_at or ''}",
        f"updated_at: {conv.updated_at or ''}",
        f"message_count: {conv.message_count}",
        f"raw_ref: {conv.raw_ref}",
        "---",
        "",
        f"# {conv.title}",
        "",
    ]
    body = "\n\n".join(_render_msg(m) for m in conv.messages)
    return "\n".join(fm) + body + "\n"
