# Agent 对话沉淀层 P1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一个本地 CLI，把 Claude Code 与 Codex 的对话增量沉淀成「原始镜像(hardlink) + 精炼 Markdown + SQLite(FTS5) 全文索引」三层档案。

**Architecture:** 插件化 collector（每个源实现 `discover`/`parse`）→ 归一为 `Conversation` → 三层落盘（mirror / render / store）。`sync` 用 SQLite `manifest` 表做基于 mtime+size 的增量；`search`/`stats` 读 SQLite。纯本地、零网络、零三方依赖（仅 Python 标准库 + sqlite3 FTS5）。

**Tech Stack:** Python 3.11+，标准库（`dataclasses`/`json`/`sqlite3`/`pathlib`/`hashlib`/`argparse`/`os`），pytest。

设计依据：[沉淀层设计 v1.1](../specs/2026-06-14-agent-conversation-sediment-design.md)。

---

## File Structure

```
agent-archive/
  pyproject.toml                     # 包定义 + pytest 配置 + entry point
  agent_archive/
    __init__.py
    models.py                        # SessionRef / Message / Conversation + content_hash
    collectors/
      __init__.py                    # Collector 协议 + 源注册表
      claude.py                      # ClaudeCollector
      codex.py                       # CodexCollector
    mirror.py                        # 原始镜像：hardlink 优先，回退 copy
    render.py                        # Conversation → Markdown
    store.py                         # SQLite schema / upsert / FTS 搜索 / manifest / stats
    sync.py                          # 编排 + 增量
    cli.py                           # argparse: sync / search / stats
  tests/
    fixtures/
      claude_sample.jsonl
      codex_sample.jsonl
      codex_session_index.jsonl
    test_models.py
    test_claude_collector.py
    test_codex_collector.py
    test_mirror.py
    test_render.py
    test_store.py
    test_sync.py
```

每个文件单一职责：`collectors/*` 只懂各源格式；`store.py` 只懂 SQLite；`sync.py` 只做编排，不懂任何源细节。

约定：`ARCHIVE_ROOT` 默认 `~/agent-archive`，可被 `--root` 或环境变量 `AGENT_ARCHIVE_ROOT` 覆盖。常量 `MD_TRUNCATE_BYTES=2048`、`MAX_INDEX_BYTES=65536`。

---

## Task 0: 项目脚手架

**Files:**
- Create: `pyproject.toml`
- Create: `agent_archive/__init__.py`
- Create: `tests/__init__.py`

- [ ] **Step 1: 写 pyproject.toml**

```toml
[project]
name = "agent-archive"
version = "0.1.0"
requires-python = ">=3.11"

[project.scripts]
agent-archive = "agent_archive.cli:main"

[tool.pytest.ini_options]
testpaths = ["tests"]

[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"
```

- [ ] **Step 2: 建空包文件**

`agent_archive/__init__.py`:
```python
__version__ = "0.1.0"
```
`tests/__init__.py`: 空文件。

- [ ] **Step 3: 安装并确认 pytest 可跑**

Run: `cd ~/agent-archive && python3 -m pip install -e . pytest && python3 -m pytest -q`
Expected: `no tests ran`（无报错即可）。

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml agent_archive/__init__.py tests/__init__.py
git commit -m "chore: 项目脚手架与 pytest 配置"
```

---

## Task 1: 数据模型与 content_hash

**Files:**
- Create: `agent_archive/models.py`
- Test: `tests/test_models.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_models.py
from agent_archive.models import Message, Conversation, SessionRef

def _conv(msgs):
    return Conversation(
        id="claude:abc", source="claude", title="t", project="p",
        started_at="2026-06-14T00:00:00Z", updated_at="2026-06-14T00:01:00Z",
        messages=msgs, raw_ref="raw/claude/abc.jsonl",
    )

def test_content_hash_only_covers_prose_and_is_stable():
    prose = [Message(role="user", text="hello"), Message(role="assistant", text="hi")]
    h1 = _conv(prose).content_hash
    # 追加一条 tool 消息不应改变 hash（hash 只覆盖 prose 正文）
    h2 = _conv(prose + [Message(role="tool", text="ls -la", kind="tool")]).content_hash
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex

def test_content_hash_changes_when_prose_changes():
    a = _conv([Message(role="user", text="hello")]).content_hash
    b = _conv([Message(role="user", text="HELLO")]).content_hash
    assert a != b

def test_message_count():
    assert _conv([Message(role="user", text="x")]).message_count == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_models.py -q`
Expected: FAIL（`ModuleNotFoundError: agent_archive.models`）。

- [ ] **Step 3: 实现 models.py**

```python
# agent_archive/models.py
from __future__ import annotations
from dataclasses import dataclass
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

    @property
    def content_hash(self) -> str:
        h = hashlib.sha256()
        for m in self.messages:
            if m.kind == "prose":
                h.update(m.role.encode("utf-8"))
                h.update(b"\n")
                h.update(m.text.encode("utf-8"))
                h.update(b"\x00")
        return h.hexdigest()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_models.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/models.py tests/test_models.py
git commit -m "feat: Conversation/Message/SessionRef 模型与 content_hash"
```

---

## Task 2: Collector 协议与注册表

**Files:**
- Create: `agent_archive/collectors/__init__.py`
- Test: `tests/test_collectors_registry.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_collectors_registry.py
from agent_archive.collectors import get_collectors, Collector

def test_registry_has_claude_and_codex():
    cols = {c.source: c for c in get_collectors()}
    assert set(cols) == {"claude", "codex"}
    for c in cols.values():
        assert isinstance(c, Collector)

def test_filter_by_source():
    cols = get_collectors(only="codex")
    assert [c.source for c in cols] == ["codex"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_collectors_registry.py -q`
Expected: FAIL（import 失败；此时 claude/codex 尚未实现，注册表先留空会让第一个断言失败——预期）。

- [ ] **Step 3: 实现协议与注册表**

```python
# agent_archive/collectors/__init__.py
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
    cols: list[Collector] = [ClaudeCollector(), CodexCollector()]
    if only:
        cols = [c for c in cols if c.source == only]
    return cols
```

- [ ] **Step 4: 占位 collector 让注册表可导入**

先建最小占位（Task 3/4 会填实现）：

`agent_archive/collectors/claude.py`:
```python
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
```

`agent_archive/collectors/codex.py`:
```python
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
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m pytest tests/test_collectors_registry.py -q`
Expected: PASS（2 passed）。

- [ ] **Step 6: Commit**

```bash
git add agent_archive/collectors/
git add tests/test_collectors_registry.py
git commit -m "feat: Collector 协议与源注册表（claude/codex 占位）"
```

---

## Task 3: ClaudeCollector 解析

**Files:**
- Create: `tests/fixtures/claude_sample.jsonl`
- Modify: `agent_archive/collectors/claude.py`
- Test: `tests/test_claude_collector.py`

- [ ] **Step 1: 建 fixture（贴近真实结构）**

`tests/fixtures/claude_sample.jsonl`（每行一个 JSON；含噪声行、user 字符串 content、assistant 多 block、sidechain）：
```jsonl
{"type":"queue-operation","operation":"enqueue","sessionId":"sess1"}
{"type":"user","message":{"role":"user","content":"帮我写个脚本"},"timestamp":"2026-06-14T07:12:19.891Z","cwd":"/home/dev/demo-project","sessionId":"sess1"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"thinking","thinking":"先看下目录"},{"type":"text","text":"好的，我来写"},{"type":"tool_use","name":"Bash","input":{"command":"ls -la"}}]},"timestamp":"2026-06-14T07:12:25.000Z","cwd":"/home/dev/demo-project","sessionId":"sess1"}
{"type":"user","message":{"role":"user","content":[{"type":"tool_result","content":"total 0"}]},"timestamp":"2026-06-14T07:12:26.000Z","sessionId":"sess1"}
{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"写好了"}]},"timestamp":"2026-06-14T07:12:30.000Z","isSidechain":true,"sessionId":"sess1"}
```

- [ ] **Step 2: 写失败测试**

```python
# tests/test_claude_collector.py
import os
from agent_archive.collectors.claude import ClaudeCollector

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _ref(tmp_path):
    src = os.path.join(FIX, "claude_sample.jsonl")
    dst = tmp_path / "sess1.jsonl"
    dst.write_text(open(src, encoding="utf-8").read(), encoding="utf-8")
    c = ClaudeCollector(root=str(tmp_path))
    refs = list(c.discover())
    return c, refs

def test_discover_finds_session(tmp_path):
    c, refs = _ref(tmp_path)
    assert len(refs) == 1
    assert refs[0].source == "claude"
    assert refs[0].native_id == "sess1"

def test_parse_builds_conversation(tmp_path):
    c, refs = _ref(tmp_path)
    conv = c.parse(refs[0])
    assert conv.id == "claude:sess1"
    assert conv.project == "/home/dev/demo-project"
    assert conv.title == "帮我写个脚本"          # 首条 user 正文
    assert conv.started_at == "2026-06-14T07:12:19.891Z"
    assert conv.updated_at == "2026-06-14T07:12:30.000Z"
    kinds = [(m.role, m.kind) for m in conv.messages]
    # user prose, assistant thinking+text+tool, tool_result(prose? no→tool), sidechain assistant
    assert ("user", "prose") in kinds
    assert ("assistant", "thinking") in kinds
    assert ("assistant", "tool") in kinds          # tool_use
    assert any(m.kind == "sidechain" for m in conv.messages)

def test_queue_operation_is_ignored(tmp_path):
    c, refs = _ref(tmp_path)
    conv = c.parse(refs[0])
    assert all(m.role != "queue-operation" for m in conv.messages)
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python3 -m pytest tests/test_claude_collector.py -q`
Expected: FAIL（discover 返回空 / parse 抛 NotImplementedError）。

- [ ] **Step 4: 实现 ClaudeCollector**

```python
# agent_archive/collectors/claude.py
from __future__ import annotations
import os, json, glob
from typing import Iterable
from agent_archive.models import SessionRef, Message, Conversation


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
        title = ""
        started_at = updated_at = None
        for line in open(ref.path, encoding="utf-8"):
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
                if msg.kind == "prose" and msg.role == "user" and not title:
                    title = msg.text.strip().splitlines()[0][:80]
                messages.append(msg)
        return Conversation(
            id=f"{self.source}:{ref.native_id}", source=self.source,
            title=title or "(无标题)", project=project,
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
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m pytest tests/test_claude_collector.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 6: 对真实数据冒烟（只读，不写盘）**

Run:
```bash
python3 -c "
from agent_archive.collectors.claude import ClaudeCollector
c=ClaudeCollector(); refs=list(c.discover())
print('claude sessions:', len(refs))
conv=c.parse(max(refs, key=lambda r:r.size if r.size<200000 else 0))
print('title:', conv.title[:40], '| msgs:', conv.message_count, '| project:', conv.project)
"
```
Expected: 打印出真实会话数、一个标题与消息数（无异常）。

- [ ] **Step 7: Commit**

```bash
git add agent_archive/collectors/claude.py tests/test_claude_collector.py tests/fixtures/claude_sample.jsonl
git commit -m "feat: ClaudeCollector discover/parse（block 归一、sidechain/thinking 标注）"
```

---

## Task 4: CodexCollector 解析（含 compacted 去重坑）

**Files:**
- Create: `tests/fixtures/codex_sample.jsonl`, `tests/fixtures/codex_session_index.jsonl`
- Modify: `agent_archive/collectors/codex.py`
- Test: `tests/test_codex_collector.py`

- [ ] **Step 1: 建 fixture**

`tests/fixtures/codex_session_index.jsonl`:
```jsonl
{"id":"019e060b-1e4c-79a3-b534-9e4cc5dc2450","thread_name":"快团团订单核对","updated_at":"2026-05-08T05:30:00Z"}
```

`tests/fixtures/codex_sample.jsonl`（含 session_meta、用户/助手正文、噪声 developer message、加密 reasoning、function_call、以及会重复历史的 compacted）：
```jsonl
{"type":"session_meta","payload":{"id":"019e060b-1e4c-79a3-b534-9e4cc5dc2450","timestamp":"2026-05-08T05:24:12.492Z","cwd":"/home/dev/demo-project"}}
{"type":"response_item","payload":{"type":"message","role":"developer","content":[{"type":"input_text","text":"<permissions instructions> ..."}]}}
{"type":"event_msg","payload":{"type":"user_message","message":"帮我核对快团团订单"}}
{"type":"response_item","payload":{"type":"reasoning","summary":[],"content":null,"encrypted_content":"gAAAA..."}}
{"type":"event_msg","payload":{"type":"agent_message","message":"我先看下项目结构"}}
{"type":"response_item","payload":{"type":"function_call","name":"exec_command","arguments":"{\"cmd\":\"pwd\"}"}}
{"type":"event_msg","payload":{"type":"task_complete","turn_id":"t1","last_agent_message":"我先看下项目结构"}}
{"type":"compacted","payload":{"message":"","replacement_history":[{"type":"message","role":"user","content":[{"type":"input_text","text":"帮我核对快团团订单"}]}]}}
```

- [ ] **Step 2: 写失败测试**

```python
# tests/test_codex_collector.py
import os
from agent_archive.collectors.codex import CodexCollector

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _setup(tmp_path):
    sub = tmp_path / "2026" / "05" / "08"
    sub.mkdir(parents=True)
    name = "rollout-2026-05-08T05-24-12-019e060b-1e4c-79a3-b534-9e4cc5dc2450.jsonl"
    (sub / name).write_text(
        open(os.path.join(FIX, "codex_sample.jsonl"), encoding="utf-8").read(), encoding="utf-8")
    idx = tmp_path / "session_index.jsonl"
    idx.write_text(open(os.path.join(FIX, "codex_session_index.jsonl"), encoding="utf-8").read(),
                   encoding="utf-8")
    c = CodexCollector(root=str(tmp_path), index_path=str(idx))
    return c, list(c.discover())

def test_discover(tmp_path):
    c, refs = _setup(tmp_path)
    assert len(refs) == 1
    assert refs[0].native_id == "019e060b-1e4c-79a3-b534-9e4cc5dc2450"

def test_title_from_index(tmp_path):
    c, refs = _setup(tmp_path)
    assert c.parse(refs[0]).title == "快团团订单核对"

def test_prose_authoritative_and_no_compacted_dup(tmp_path):
    c, refs = _setup(tmp_path)
    conv = c.parse(refs[0])
    prose = [m for m in conv.messages if m.kind == "prose"]
    # 仅 1 条 user + 1 条 assistant；compacted 的重复历史不得计入
    assert [(m.role, m.text) for m in prose] == [
        ("user", "帮我核对快团团订单"), ("assistant", "我先看下项目结构")]

def test_developer_noise_and_encrypted_reasoning_excluded(tmp_path):
    c, refs = _setup(tmp_path)
    conv = c.parse(refs[0])
    assert all("permissions instructions" not in m.text for m in conv.messages)
    assert all(m.kind != "thinking" for m in conv.messages)  # reasoning 加密，丢弃

def test_function_call_becomes_tool(tmp_path):
    c, refs = _setup(tmp_path)
    conv = c.parse(refs[0])
    assert any(m.kind == "tool" and m.tool == "exec_command" for m in conv.messages)

def test_project_from_meta(tmp_path):
    c, refs = _setup(tmp_path)
    assert c.parse(refs[0]).project == "/home/dev/demo-project"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `python3 -m pytest tests/test_codex_collector.py -q`
Expected: FAIL（discover 空 / NotImplementedError）。

- [ ] **Step 4: 实现 CodexCollector**

```python
# agent_archive/collectors/codex.py
from __future__ import annotations
import os, json, glob
from typing import Iterable
from agent_archive.models import SessionRef, Message, Conversation


class CodexCollector:
    source = "codex"

    def __init__(self, root: str | None = None, index_path: str | None = None):
        self.root = root or os.path.expanduser("~/.codex/sessions")
        self.index_path = index_path or os.path.expanduser("~/.codex/session_index.jsonl")

    def _titles(self) -> dict:
        titles = {}
        if os.path.exists(self.index_path):
            for line in open(self.index_path, encoding="utf-8"):
                try:
                    o = json.loads(line)
                    if o.get("id") and o.get("thread_name"):
                        titles[o["id"]] = o["thread_name"]
                except json.JSONDecodeError:
                    continue
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
        last_agent = ""
        for line in open(ref.path, encoding="utf-8"):
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
                continue  # 🔴 compacted.replacement_history 会重复历史，必须跳过
            if t != "event_msg":
                # response_item 仅用于补 tool，不作正文（避免 developer 噪声 + 双轨重复）
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
                last_agent = txt
                messages.append(Message("assistant", txt, None, "prose"))
            elif pt == "task_complete":
                # 仅当与末条 agent_message 不同时兜底（通常重复，跳过）
                lam = p.get("last_agent_message", "")
                if lam and lam != last_agent:
                    messages.append(Message("assistant", lam, None, "prose"))
        title = titles.get(ref.native_id)
        if not title:
            title = first_user.strip().splitlines()[0][:80] if first_user else "(无标题)"
        return Conversation(
            id=f"{self.source}:{ref.native_id}", source=self.source,
            title=title, project=project,
            started_at=started_at, updated_at=updated_at,
            messages=messages, raw_ref="",
        )
```

- [ ] **Step 5: 跑测试确认通过**

Run: `python3 -m pytest tests/test_codex_collector.py -q`
Expected: PASS（6 passed）。

- [ ] **Step 6: 对真实数据冒烟（验证 title join 真成立）**

Run:
```bash
python3 -c "
from agent_archive.collectors.codex import CodexCollector
c=CodexCollector(); refs=list(c.discover())
print('codex sessions:', len(refs))
joined=sum(1 for r in refs[:50] if c.parse(r).title != '(无标题)')
print('first-50 标题命中:', joined)
"
```
Expected: 标题命中数 > 0（确认 `session_index` join 真的对得上；若为 0 需排查 id 格式）。

- [ ] **Step 7: Commit**

```bash
git add agent_archive/collectors/codex.py tests/test_codex_collector.py tests/fixtures/codex_sample.jsonl tests/fixtures/codex_session_index.jsonl
git commit -m "feat: CodexCollector（event_msg 权威源、跳过 compacted、丢弃加密 reasoning、标题 join）"
```

---

## Task 5: 原始镜像（hardlink 优先）

**Files:**
- Create: `agent_archive/mirror.py`
- Test: `tests/test_mirror.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_mirror.py
import os
from agent_archive.models import SessionRef
from agent_archive.mirror import mirror

def test_hardlink_same_fs(tmp_path):
    src = tmp_path / "src.jsonl"; src.write_text("hello", encoding="utf-8")
    st = src.stat()
    ref = SessionRef("claude", "sess1", str(src), st.st_mtime, st.st_size)
    root = tmp_path / "archive"
    raw_ref = mirror(ref, str(root), prefer_hardlink=True)
    dest = root / raw_ref
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "hello"
    # 硬链接：同 inode；源被删后仍存活
    assert os.stat(src).st_ino == os.stat(dest).st_ino
    os.remove(src)
    assert dest.read_text(encoding="utf-8") == "hello"

def test_copy_fallback(tmp_path):
    src = tmp_path / "src.db"; src.write_text("data", encoding="utf-8")
    st = src.stat()
    ref = SessionRef("cursor", "x", str(src), st.st_mtime, st.st_size)
    root = tmp_path / "archive"
    raw_ref = mirror(ref, str(root), prefer_hardlink=False)
    dest = root / raw_ref
    assert dest.exists()
    assert os.stat(src).st_ino != os.stat(dest).st_ino  # 拷贝，不同 inode
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_mirror.py -q`
Expected: FAIL（`ModuleNotFoundError: agent_archive.mirror`）。

- [ ] **Step 3: 实现 mirror.py**

```python
# agent_archive/mirror.py
from __future__ import annotations
import os, shutil
from agent_archive.models import SessionRef


def mirror(ref: SessionRef, archive_root: str, prefer_hardlink: bool = True) -> str:
    """把源文件镜像进 raw/<source>/<basename>，返回相对 raw_ref。
    优先硬链接（同盘、append-only）；失败或不偏好则拷贝。重复调用幂等。"""
    rel = os.path.join("raw", ref.source, os.path.basename(ref.path))
    dest = os.path.join(archive_root, rel)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if os.path.exists(dest):
        os.remove(dest)
    if prefer_hardlink:
        try:
            os.link(ref.path, dest)
            return rel
        except OSError:
            pass  # 跨盘/不支持 → 回退拷贝
    shutil.copy2(ref.path, dest)
    return rel
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_mirror.py -q`
Expected: PASS（2 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/mirror.py tests/test_mirror.py
git commit -m "feat: 原始镜像 hardlink 优先、copy 回退"
```

---

## Task 6: Markdown 渲染

**Files:**
- Create: `agent_archive/render.py`
- Test: `tests/test_render.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_render.py
from agent_archive.models import Message, Conversation
from agent_archive.render import render_markdown, MD_TRUNCATE_BYTES

def _conv(msgs):
    return Conversation("claude:s1","claude","写脚本","/p",
        "2026-06-14T07:12:19Z","2026-06-14T07:12:30Z", msgs, "raw/claude/s1.jsonl")

def test_frontmatter_and_body():
    md = render_markdown(_conv([Message("user","你好","2026-06-14T07:12:19Z")]))
    assert md.startswith("---\n")
    assert "id: claude:s1" in md
    assert "title: 写脚本" in md
    assert "raw_ref: raw/claude/s1.jsonl" in md
    assert "你好" in md

def test_thinking_collapsed_and_tool_oneline():
    md = render_markdown(_conv([
        Message("assistant","深思","t",kind="thinking"),
        Message("assistant",'{"command":"ls"}',"t",kind="tool",tool="Bash"),
    ]))
    assert "<details>" in md            # thinking 折叠
    assert "🔧 Bash" in md              # tool 一行

def test_large_tool_output_truncated():
    big = "x" * (MD_TRUNCATE_BYTES + 100)
    md = render_markdown(_conv([Message("tool",big,"t",kind="tool",tool="tool_result")]))
    assert "[截断" in md
    assert len(md) < MD_TRUNCATE_BYTES + 2000
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_render.py -q`
Expected: FAIL（`ModuleNotFoundError: agent_archive.render`）。

- [ ] **Step 3: 实现 render.py**

```python
# agent_archive/render.py
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
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_render.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/render.py tests/test_render.py
git commit -m "feat: Markdown 渲染（front matter、thinking 折叠、tool 一行、截断）"
```

---

## Task 7: SQLite 存储（schema / upsert / FTS 搜索 / manifest / stats）

**Files:**
- Create: `agent_archive/store.py`
- Test: `tests/test_store.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_store.py
from agent_archive.models import Message, Conversation
from agent_archive import store

def _conv(cid="claude:s1", prose="你好世界"):
    return Conversation(cid, "claude", "标题", "/p",
        "2026-06-14T07:12:19Z", "2026-06-14T07:12:30Z",
        [Message("user", prose, "t"),
         Message("assistant", "ok", "t"),
         Message("tool", "x"*100, "t", kind="tool", tool="Bash")],
        "raw/claude/s1.jsonl")

def test_init_and_upsert_then_search(tmp_path):
    db = tmp_path / "a.sqlite"
    conn = store.connect(str(db)); store.init_db(conn)
    store.upsert_conversation(conn, _conv(), md_ref="md/2026-06-14/x.md")
    hits = store.search(conn, "你好世界")
    assert len(hits) == 1
    assert hits[0]["conv_id"] == "claude:s1"

def test_tool_text_not_indexed(tmp_path):
    db = tmp_path / "a.sqlite"
    conn = store.connect(str(db)); store.init_db(conn)
    store.upsert_conversation(conn, _conv(prose="可搜索正文"), md_ref="m")
    assert store.search(conn, "可搜索正文")          # prose 命中
    assert store.search(conn, "xxxxxxxxxx") == []    # tool 文本不进 FTS

def test_upsert_is_idempotent(tmp_path):
    db = tmp_path / "a.sqlite"
    conn = store.connect(str(db)); store.init_db(conn)
    for _ in range(3):
        store.upsert_conversation(conn, _conv(), md_ref="m")
    assert len(store.search(conn, "你好世界")) == 1   # 不重复

def test_manifest_roundtrip(tmp_path):
    db = tmp_path / "a.sqlite"
    conn = store.connect(str(db)); store.init_db(conn)
    assert store.manifest_get(conn, "codex", "/x.jsonl") is None
    store.manifest_set(conn, "codex", "/x.jsonl", mtime=1.0, size=10, content_hash="h")
    row = store.manifest_get(conn, "codex", "/x.jsonl")
    assert row["size"] == 10 and row["content_hash"] == "h"

def test_search_filter_by_source(tmp_path):
    db = tmp_path / "a.sqlite"
    conn = store.connect(str(db)); store.init_db(conn)
    store.upsert_conversation(conn, _conv("claude:s1","唯一词"), md_ref="m")
    store.upsert_conversation(conn, _conv("codex:s2","唯一词"), md_ref="m")
    assert len(store.search(conn, "唯一词")) == 2
    assert len(store.search(conn, "唯一词", source="codex")) == 1

def test_stats(tmp_path):
    db = tmp_path / "a.sqlite"
    conn = store.connect(str(db)); store.init_db(conn)
    store.upsert_conversation(conn, _conv(), md_ref="m")
    s = store.stats(conn)
    assert s["claude"]["conversations"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_store.py -q`
Expected: FAIL（`ModuleNotFoundError: agent_archive.store`）。

- [ ] **Step 3: 实现 store.py**

```python
# agent_archive/store.py
from __future__ import annotations
import sqlite3
from agent_archive.models import Conversation

MAX_INDEX_BYTES = 65536

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, project TEXT,
  started_at TEXT, updated_at TEXT, message_count INTEGER,
  content_hash TEXT NOT NULL, raw_ref TEXT NOT NULL, md_ref TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  conv_id TEXT NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL,
  ts TEXT, kind TEXT, text TEXT, PRIMARY KEY (conv_id, seq)
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  text, conv_id UNINDEXED, role UNINDEXED
);
CREATE TABLE IF NOT EXISTS manifest (
  source TEXT NOT NULL, src_path TEXT NOT NULL, src_mtime REAL,
  src_size INTEGER, content_hash TEXT, last_synced_at TEXT,
  PRIMARY KEY (source, src_path)
);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_conversation(conn, conv: Conversation, md_ref: str) -> None:
    conn.execute("DELETE FROM messages WHERE conv_id=?", (conv.id,))
    conn.execute("DELETE FROM messages_fts WHERE conv_id=?", (conv.id,))
    conn.execute(
        "INSERT OR REPLACE INTO conversations "
        "(id,source,title,project,started_at,updated_at,message_count,content_hash,raw_ref,md_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (conv.id, conv.source, conv.title, conv.project, conv.started_at,
         conv.updated_at, conv.message_count, conv.content_hash, conv.raw_ref, md_ref))
    for seq, m in enumerate(conv.messages):
        conn.execute(
            "INSERT INTO messages (conv_id,seq,role,ts,kind,text) VALUES (?,?,?,?,?,?)",
            (conv.id, seq, m.role, m.ts, m.kind, m.text))
        if m.kind == "prose" and m.text:
            text = m.text.encode("utf-8")[:MAX_INDEX_BYTES].decode("utf-8", "ignore")
            conn.execute("INSERT INTO messages_fts (text,conv_id,role) VALUES (?,?,?)",
                         (text, conv.id, m.role))
    conn.commit()


def search(conn, query: str, source: str | None = None, project: str | None = None) -> list[dict]:
    sql = ("SELECT DISTINCT c.id AS conv_id, c.source, c.title, c.project, c.md_ref "
           "FROM messages_fts f JOIN conversations c ON c.id=f.conv_id "
           "WHERE messages_fts MATCH ?")
    args = [query]
    if source:
        sql += " AND c.source=?"; args.append(source)
    if project:
        sql += " AND c.project LIKE ?"; args.append(f"%{project}%")
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def manifest_get(conn, source: str, src_path: str) -> dict | None:
    r = conn.execute("SELECT src_mtime AS mtime, src_size AS size, content_hash "
                     "FROM manifest WHERE source=? AND src_path=?",
                     (source, src_path)).fetchone()
    return dict(r) if r else None


def manifest_set(conn, source, src_path, mtime, size, content_hash, last_synced_at="") -> None:
    conn.execute("INSERT OR REPLACE INTO manifest "
                 "(source,src_path,src_mtime,src_size,content_hash,last_synced_at) "
                 "VALUES (?,?,?,?,?,?)",
                 (source, src_path, mtime, size, content_hash, last_synced_at))
    conn.commit()


def stats(conn) -> dict:
    out = {}
    for r in conn.execute("SELECT source, COUNT(*) c, SUM(message_count) m "
                          "FROM conversations GROUP BY source"):
        out[r["source"]] = {"conversations": r["c"], "messages": r["m"] or 0}
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_store.py -q`
Expected: PASS（6 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/store.py tests/test_store.py
git commit -m "feat: SQLite 存储（schema/upsert/FTS 搜索/manifest/stats）"
```

---

## Task 8: sync 编排与增量

**Files:**
- Create: `agent_archive/sync.py`
- Test: `tests/test_sync.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_sync.py
import os, datetime
from agent_archive.collectors.claude import ClaudeCollector
from agent_archive import sync, store

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _make_claude(tmp_path):
    proj = tmp_path / "src"; proj.mkdir()
    (proj / "sess1.jsonl").write_text(
        open(os.path.join(FIX, "claude_sample.jsonl"), encoding="utf-8").read(), encoding="utf-8")
    return ClaudeCollector(root=str(proj))

def test_sync_writes_three_layers(tmp_path):
    root = tmp_path / "archive"
    col = _make_claude(tmp_path)
    res = sync.sync(str(root), collectors=[col])
    assert res["synced"] == 1
    # ① raw 镜像
    assert (root / "raw" / "claude" / "sess1.jsonl").exists()
    # ② markdown（按起始日期 2026-06-14 分目录）
    mds = list((root / "md").rglob("*.md"))
    assert len(mds) == 1 and "2026-06-14" in str(mds[0])
    # ③ sqlite 可搜
    conn = store.connect(str(root / "index.sqlite"))
    assert store.search(conn, "脚本")

def test_sync_incremental_skips_unchanged(tmp_path):
    root = tmp_path / "archive"
    col = _make_claude(tmp_path)
    assert sync.sync(str(root), collectors=[col])["synced"] == 1
    r2 = sync.sync(str(root), collectors=[col])      # 文件未变
    assert r2["synced"] == 0 and r2["skipped"] == 1

def test_sync_full_reprocesses(tmp_path):
    root = tmp_path / "archive"
    col = _make_claude(tmp_path)
    sync.sync(str(root), collectors=[col])
    assert sync.sync(str(root), collectors=[col], full=True)["synced"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_sync.py -q`
Expected: FAIL（`ModuleNotFoundError: agent_archive.sync`）。

- [ ] **Step 3: 实现 sync.py**

```python
# agent_archive/sync.py
from __future__ import annotations
import os, re, datetime
from agent_archive import store, mirror as mirror_mod, render as render_mod


def _slug(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\n\r\t]+", "_", s).strip("_ ")
    return (s or "untitled")[:40]


def _md_path(root: str, conv) -> str:
    day = (conv.started_at or "")[:10] or "0000-00-00"
    short = conv.id.split(":")[-1][:8]
    name = f"{conv.source}__{_slug(conv.title)}__{short}.md"
    return os.path.join(root, "md", day, name)


def sync(archive_root: str, collectors, full: bool = False) -> dict:
    os.makedirs(archive_root, exist_ok=True)
    conn = store.connect(os.path.join(archive_root, "index.sqlite"))
    store.init_db(conn)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    synced = skipped = 0
    for col in collectors:
        prefer_hl = col.source in ("claude", "codex")
        for ref in col.discover():
            prev = store.manifest_get(conn, ref.source, ref.path)
            if not full and prev and prev["mtime"] == ref.mtime and prev["size"] == ref.size:
                skipped += 1
                continue
            conv = col.parse(ref)
            conv.raw_ref = mirror_mod.mirror(ref, archive_root, prefer_hardlink=prefer_hl)
            md_path = _md_path(archive_root, conv)
            os.makedirs(os.path.dirname(md_path), exist_ok=True)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(render_mod.render_markdown(conv))
            md_ref = os.path.relpath(md_path, archive_root)
            store.upsert_conversation(conn, conv, md_ref=md_ref)
            store.manifest_set(conn, ref.source, ref.path, ref.mtime, ref.size,
                               conv.content_hash, now)
            synced += 1
    return {"synced": synced, "skipped": skipped}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_sync.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/sync.py tests/test_sync.py
git commit -m "feat: sync 编排三层落盘 + manifest 增量"
```

---

## Task 9: CLI

**Files:**
- Create: `agent_archive/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli.py
import os
from agent_archive import cli
from agent_archive.collectors.claude import ClaudeCollector

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _root_with_data(tmp_path, monkeypatch):
    proj = tmp_path / "src"; proj.mkdir()
    (proj / "sess1.jsonl").write_text(
        open(os.path.join(FIX, "claude_sample.jsonl"), encoding="utf-8").read(), encoding="utf-8")
    # 让 cli 只用 claude collector，且指向 fixture 根
    monkeypatch.setattr(cli, "get_collectors",
                        lambda only=None: [ClaudeCollector(root=str(proj))])
    return str(tmp_path / "archive")

def test_cli_sync_then_search(tmp_path, monkeypatch, capsys):
    root = _root_with_data(tmp_path, monkeypatch)
    assert cli.main(["--root", root, "sync"]) == 0
    assert cli.main(["--root", root, "search", "脚本"]) == 0
    out = capsys.readouterr().out
    assert "claude:sess1" in out

def test_cli_stats(tmp_path, monkeypatch, capsys):
    root = _root_with_data(tmp_path, monkeypatch)
    cli.main(["--root", root, "sync"])
    assert cli.main(["--root", root, "stats"]) == 0
    assert "claude" in capsys.readouterr().out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `python3 -m pytest tests/test_cli.py -q`
Expected: FAIL（`ModuleNotFoundError: agent_archive.cli` 或缺 `get_collectors`）。

- [ ] **Step 3: 实现 cli.py**

```python
# agent_archive/cli.py
from __future__ import annotations
import os, argparse
from agent_archive import sync as sync_mod, store
from agent_archive.collectors import get_collectors


def _root(args) -> str:
    return os.path.expanduser(
        args.root or os.environ.get("AGENT_ARCHIVE_ROOT", "~/agent-archive"))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="agent-archive")
    p.add_argument("--root", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sync")
    ps.add_argument("--source", default=None)
    ps.add_argument("--full", action="store_true")

    pq = sub.add_parser("search")
    pq.add_argument("query")
    pq.add_argument("--source", default=None)
    pq.add_argument("--project", default=None)

    sub.add_parser("stats")

    args = p.parse_args(argv)
    root = _root(args)

    if args.cmd == "sync":
        cols = get_collectors(only=args.source)
        res = sync_mod.sync(root, collectors=cols, full=args.full)
        print(f"synced={res['synced']} skipped={res['skipped']}")
        return 0

    conn = store.connect(os.path.join(root, "index.sqlite"))
    store.init_db(conn)
    if args.cmd == "search":
        for h in store.search(conn, args.query, source=args.source, project=args.project):
            print(f"{h['conv_id']}  [{h['source']}]  {h['title']}\n    {h['md_ref']}")
        return 0
    if args.cmd == "stats":
        for src, s in store.stats(conn).items():
            print(f"{src}: {s['conversations']} 会话 / {s['messages']} 消息")
        return 0
    return 1
```

- [ ] **Step 4: 跑测试确认通过**

Run: `python3 -m pytest tests/test_cli.py -q`
Expected: PASS（2 passed）。

- [ ] **Step 5: 全量测试 + 真实数据端到端**

Run:
```bash
python3 -m pytest -q
AGENT_ARCHIVE_ROOT=/tmp/aa-real python3 -m agent_archive.cli sync
AGENT_ARCHIVE_ROOT=/tmp/aa-real python3 -m agent_archive.cli stats
AGENT_ARCHIVE_ROOT=/tmp/aa-real python3 -m agent_archive.cli search "订单"
```
Expected: 全部测试 PASS；`sync` 打印真实 synced 数（≈120 claude + ≈194 codex）；`stats` 显示两源会话数；`search` 返回命中。

- [ ] **Step 6: Commit**

```bash
git add agent_archive/cli.py tests/test_cli.py
git commit -m "feat: CLI sync/search/stats"
```

---

## Task 10: 每日定时（launchd）与 README

**Files:**
- Create: `scripts/com.agentarchive.sync.plist`
- Create: `README.md`

- [ ] **Step 1: 写 launchd plist**

`scripts/com.agentarchive.sync.plist`（占位 `__USER__`，安装时替换为真实用户名）：
```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.agentarchive.sync</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>agent_archive.cli</string>
    <string>sync</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>23</integer><key>Minute</key><integer>30</integer></dict>
  <key>StandardOutPath</key><string>/Users/__USER__/agent-archive/sync.log</string>
  <key>StandardErrorPath</key><string>/Users/__USER__/agent-archive/sync.err</string>
  <key>WorkingDirectory</key><string>/Users/__USER__/agent-archive</string>
</dict>
</plist>
```

- [ ] **Step 2: 写 README**

`README.md`：
```markdown
# agent-archive

把本地 Agent 对话（Claude Code / Codex）沉淀成 原始镜像 + Markdown + SQLite(FTS5) 三层档案。

## 安装
    python3 -m pip install -e .

## 用法
    agent-archive sync                  # 增量同步
    agent-archive sync --source codex   # 只同步某源
    agent-archive sync --full           # 全量重建
    agent-archive search "关键词"
    agent-archive search "x" --source claude --project 房间渲染
    agent-archive stats

档案默认在 `~/agent-archive/`（可用 `--root` 或 `AGENT_ARCHIVE_ROOT` 覆盖）。

## 每日自动
    sed "s/__USER__/$(whoami)/g" scripts/com.agentarchive.sync.plist \
      > ~/Library/LaunchAgents/com.agentarchive.sync.plist
    launchctl load ~/Library/LaunchAgents/com.agentarchive.sync.plist

## 隐私
档案含密钥/隐私，纯本地、不上云。`raw/ md/ *.sqlite` 已在 .gitignore 中排除。
```

- [ ] **Step 3: Commit**

```bash
git add scripts/com.agentarchive.sync.plist README.md
git commit -m "docs: launchd 每日定时与 README"
```

---

## 后续（不在本计划内）

P2：CursorCollector（SQLite 解析）、DevinCollector（`api.devin.ai`，需 token）。
P3：WorkBuddy 调研、飞书；以及设计文档[附录 A](../specs/2026-06-14-agent-conversation-sediment-design.md) 的 LLM/检索/同步层。均直接复用本计划的三层档案，不返工。
