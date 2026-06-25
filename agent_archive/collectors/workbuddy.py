"""WorkBuddy (腾讯 CodeBuddy 内核) collector：从 ~/.workbuddy/projects/**/*.jsonl 解析。

一文件一会话，但行格式是扁平事件流（非 Claude 的嵌套 message）：
  - type=message：role + content[]（input_text/output_text/image_blob_ref）
  - type=reasoning：rawContent[] 思考
  - type=function_call / function_call_result：工具调用与结果
  - type=ai-title：模型生成的标题（优先用它）
  - type=file-history-snapshot 等：忽略
时间戳是 epoch 毫秒。
"""
from __future__ import annotations
import os, json, glob, datetime
from typing import Iterable
from agent_archive.models import SessionRef, Message, Conversation
from agent_archive.collectors._util import title_snippet


class WorkBuddyCollector:
    source = "workbuddy"

    def __init__(self, root: str | None = None):
        self.root = root or os.path.expanduser("~/.workbuddy/projects")

    def discover(self) -> Iterable[SessionRef]:
        for path in glob.glob(os.path.join(self.root, "**", "*.jsonl"), recursive=True):
            st = os.stat(path)
            native_id = os.path.splitext(os.path.basename(path))[0]
            yield SessionRef(self.source, native_id, path, st.st_mtime, st.st_size)

    def parse(self, ref: SessionRef) -> Conversation:
        messages: list[Message] = []
        project = None
        ai_title = ""
        title_user = title_asst = ""
        started_at = updated_at = None
        for o in _iter_jsonl(ref.path):
            t = o.get("type")
            ts = _iso_ms(o.get("timestamp"))
            project = project or o.get("cwd")
            if ts:
                started_at = started_at or ts
                updated_at = ts
            if t == "ai-title":
                ai_title = ai_title or (o.get("aiTitle") or "")
            elif t == "message":
                role = o.get("role", "")
                if role == "system":
                    continue  # 系统消息不入 prose（避免污染 FTS / distill）
                for txt in _texts(o.get("content")):
                    if not txt.strip() or _is_boilerplate(txt):
                        continue
                    if role == "user" and not title_user:
                        title_user = title_snippet(txt)
                    elif role == "assistant" and not title_asst:
                        title_asst = title_snippet(txt)
                    messages.append(Message(role, txt, ts, "prose"))
            elif t == "reasoning":
                for b in (o.get("rawContent") or []):
                    if isinstance(b, dict) and b.get("text"):
                        messages.append(Message("assistant", b["text"], ts, "thinking"))
            elif t == "function_call":
                args = (o.get("arguments") or "")[:200]
                messages.append(Message("assistant", args, ts, "tool", tool=o.get("name")))
            elif t == "function_call_result":
                out = " ".join(_texts(o.get("output")))[:200]
                messages.append(Message("tool", out, ts, "tool", tool=o.get("name")))
            # file-history-snapshot 等其余类型忽略
        return Conversation(
            id=f"{self.source}:{ref.native_id}", source=self.source,
            title=ai_title or title_user or title_asst or "(无标题)",
            project=project, started_at=started_at, updated_at=updated_at,
            messages=messages, raw_ref="",
        )


def _iter_jsonl(path):
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def _texts(content) -> list[str]:
    """从 content/output 的 block 列表抽取文本（input_text/output_text）。"""
    if isinstance(content, str):
        return [content]
    if not isinstance(content, list):
        return []
    return [b["text"] for b in content
            if isinstance(b, dict) and b.get("type") in ("input_text", "output_text")
            and b.get("text")]


def _is_boilerplate(txt: str) -> bool:
    # WorkBuddy 会把 system-reminder/user-context 当 input_text 注入，非真实对话
    return txt.lstrip().startswith("<system-reminder")


def _iso_ms(ts) -> str | None:
    if not ts:
        return None
    try:
        return datetime.datetime.fromtimestamp(
            float(ts) / 1000.0, tz=datetime.timezone.utc).isoformat()
    except (ValueError, OSError):
        return None
