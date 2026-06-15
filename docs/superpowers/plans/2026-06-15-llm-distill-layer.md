# LLM 精炼层（distill）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在已完成的沉淀层之上加一层 LLM 精炼：把会话用第三方 OpenAI 兼容 API 提炼成结构化「精华卡」（总结/要点/决策/待办/主题/价值），按封闭受控词表分主题，写进 Obsidian；隐私优先、增量、可断点续。

**Architecture:** 只读 P1 的 `messages`（`kind='prose'`）；`llm.py` 是唯一出网点（可注入便于测试）；`distill.py` 编排候选筛选→脱敏构 prompt→调模型→容错解析→输出再脱敏→写 `distillations` 表（每会话最新一条，含 ok/dropped/error 三态）；`render_distill.py` 对账重建精华卡与主题页（仅删带 `generated_by` 标记的文件）。

**Tech Stack:** Python 3.14（venv 在 `.venv`）、标准库 + `urllib`（零三方依赖）、sqlite3、pytest。所有 LLM 测试用注入的 fake client，绝不联网。

设计依据：[distill 设计 v1.3](../specs/2026-06-15-llm-distill-layer-design.md)。

---

## 环境约定（每个任务都适用）

- Work from `/Users/mac/agent-archive`，分支 `feat/p1-sediment`，git 身份已配，直接 `git commit`。
- **所有 python/pytest 命令用 `.venv/bin/python`**（3.14；勿用系统 python3）。
- TDD：写失败测试→验失败→最小实现→验通过→提交。
- 配置环境变量（实现中读取，测试不需要）：`AGENT_ARCHIVE_LLM_BASE_URL`、`AGENT_ARCHIVE_LLM_API_KEY`、`AGENT_ARCHIVE_LLM_MODEL`。
- 常量默认值：`PROMPT_VERSION="distill-v1"`、`PROSE_MIN_CHARS=200`、`MAX_PROMPT_CHARS=12000`、`VALUE_MIN=2`、`MAX_ATTEMPTS=3`。
- 受控主题词表：`电商运营 3D打印 Agent/AI开发 部署运维 网页爬虫 创意设计 知识管理 产品规划 学习研究 工具脚本 其他`。

## File Structure

```
agent_archive/
  redact.py            # 脱敏纯函数（出站 + 回程共用）
  llm.py               # OpenAI 兼容 client（urllib，唯一出网点，可注入）+ JSON 容错解析
  topics.py            # 受控词表常量 + 规范化（词表外→其他）
  distill.py           # 候选筛选 / 构 prompt / distill_one / run 编排
  render_distill.py    # 精华卡 + 主题页渲染 + 对账清理（仅自有文件）
  store.py             # 【改】加 distillations 表 + 相关函数
  cli.py               # 【改】加 distill / topics / distill-stats 子命令
tests/
  test_redact.py
  test_llm_parse.py        # JSON 容错解析（不联网）
  test_llm_client.py       # client：可注入、400 降级（用 fake transport）
  test_topics.py
  test_store_distill.py
  test_distill.py          # 候选筛选 / 构 prompt / distill_one / run（fake complete）
  test_render_distill.py   # 渲染 + 对账（仅删自有文件）
  test_cli_distill.py
```

设计取舍：`llm.py` 把"网络传输"和"JSON 解析"分成两个可单测的纯函数（`_extract_json`、`complete`），网络部分用可注入的 transport 以便测 400 降级而不联网。

---

## Task 1: 脱敏 redact.py

**Files:** Create `agent_archive/redact.py`, Test `tests/test_redact.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_redact.py
from agent_archive.redact import redact

def test_redacts_common_secrets():
    s = redact("key=sk-abcdefghijklmnopqrstuvwx token gho_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345")
    assert "sk-abcdefghijklmnopqrstuvwx" not in s
    assert "gho_ABCDEFGHIJKLMNOPQRSTUVWXYZ012345" not in s
    assert "[REDACTED]" in s

def test_redacts_aws_bearer_email_userpath():
    s = redact("AKIAIOSFODNN7EXAMPLE Bearer abc.def.ghi a@b.com /Users/mac/secret")
    assert "AKIAIOSFODNN7EXAMPLE" not in s
    assert "a@b.com" not in s
    assert "Bearer abc.def.ghi" not in s
    assert "/Users/mac/" not in s   # 用户名段被替换
    assert "/Users/[USER]/" in s

def test_keeps_normal_text():
    assert redact("帮我核对快团团订单，金额对不上") == "帮我核对快团团订单，金额对不上"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_redact.py -q`
Expected: FAIL（`ModuleNotFoundError: agent_archive.redact`）。

- [ ] **Step 3: 实现 redact.py**

```python
# agent_archive/redact.py
from __future__ import annotations
import re

_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"Bearer\s+[A-Za-z0-9._\-]+"),
    re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}"),
]
_USERPATH = re.compile(r"/Users/[^/\s]+/")


def redact(text: str) -> str:
    """尽力而为地抹掉常见密钥/邮箱/用户路径。出站与模型输出回程共用。"""
    if not text:
        return text
    out = text
    for p in _PATTERNS:
        out = p.sub("[REDACTED]", out)
    out = _USERPATH.sub("/Users/[USER]/", out)
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_redact.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/redact.py tests/test_redact.py
git commit -m "feat(distill): redact 脱敏（出站+回程共用）"
```

---

## Task 2: 受控主题词表 topics.py

**Files:** Create `agent_archive/topics.py`, Test `tests/test_topics.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_topics.py
from agent_archive.topics import TOPICS, normalize_topics

def test_topics_is_closed_set_with_other():
    assert "其他" in TOPICS
    assert "电商运营" in TOPICS

def test_normalize_keeps_known_drops_unknown():
    assert normalize_topics(["电商运营", "瞎编的标签", "3D打印"]) == ["电商运营", "3D打印"]

def test_normalize_unknown_only_becomes_other():
    assert normalize_topics(["瞎编", "也瞎编"]) == ["其他"]

def test_normalize_dedups_and_limits_to_3():
    out = normalize_topics(["电商运营","电商运营","3D打印","部署运维","学习研究"])
    assert out == ["电商运营","3D打印","部署运维"]   # 去重 + 最多3个、保序

def test_normalize_handles_empty():
    assert normalize_topics([]) == ["其他"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_topics.py -q`
Expected: FAIL（`ModuleNotFoundError`）。

- [ ] **Step 3: 实现 topics.py**

```python
# agent_archive/topics.py
from __future__ import annotations

TOPICS = [
    "电商运营", "3D打印", "Agent/AI开发", "部署运维", "网页爬虫",
    "创意设计", "知识管理", "产品规划", "学习研究", "工具脚本", "其他",
]
_KNOWN = set(TOPICS)


def normalize_topics(raw: list) -> list:
    """把模型给的标签收敛到受控词表：丢弃词表外的、去重保序、最多 3 个；全空→['其他']。"""
    out: list = []
    for t in raw or []:
        if t in _KNOWN and t not in out:
            out.append(t)
        if len(out) == 3:
            break
    return out or ["其他"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_topics.py -q`
Expected: PASS（5 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/topics.py tests/test_topics.py
git commit -m "feat(distill): 受控主题词表 + normalize"
```

---

## Task 3: LLM JSON 容错解析

**Files:** Create `agent_archive/llm.py`（先只放解析函数）, Test `tests/test_llm_parse.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llm_parse.py
import pytest
from agent_archive.llm import extract_json

def test_plain_json():
    assert extract_json('{"a": 1}') == {"a": 1}

def test_strips_code_fence():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}

def test_ignores_prose_around_json():
    assert extract_json('好的，结果如下：\n{"a": 1}\n以上。') == {"a": 1}

def test_brace_inside_string_not_treated_as_end():
    # 正文字符串里的 } 不能误判结束
    assert extract_json('{"text": "a } b", "n": 2}') == {"text": "a } b", "n": 2}

def test_escaped_quote_inside_string():
    assert extract_json(r'{"t": "he said \"hi\" }", "n": 3}') == {"t": 'he said "hi" }', "n": 3}

def test_raises_on_no_json():
    with pytest.raises(ValueError):
        extract_json("完全没有 JSON")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_llm_parse.py -q`
Expected: FAIL（`ImportError: cannot import name 'extract_json'`）。

- [ ] **Step 3: 实现 llm.py 的 extract_json**

```python
# agent_archive/llm.py
from __future__ import annotations
import json


def extract_json(text: str) -> dict:
    """从模型输出里抠出第一个完整 JSON 对象：剥代码围栏 + 字符串感知的括号扫描。"""
    s = (text or "").strip()
    if s.startswith("```"):
        # 去掉 ```json ... ``` 围栏
        s = s.split("```", 2)[1] if s.count("```") >= 2 else s.strip("`")
        if s.startswith("json"):
            s = s[4:]
    start = s.find("{")
    if start == -1:
        raise ValueError("no JSON object found")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        ch = s[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(s[start:i + 1])
    raise ValueError("unbalanced JSON object")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_llm_parse.py -q`
Expected: PASS（6 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/llm.py tests/test_llm_parse.py
git commit -m "feat(distill): LLM JSON 容错解析（剥围栏+字符串感知括号扫描）"
```

---

## Task 4: LLM client（可注入 + 400 降级）

**Files:** Modify `agent_archive/llm.py`, Test `tests/test_llm_client.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llm_client.py
import pytest
from agent_archive.llm import complete, LLMError

class FakeTransport:
    """记录每次请求体，按预设依次返回 (status, body)。"""
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def __call__(self, url, headers, body):
        self.calls.append(body)
        status, payload = self.responses.pop(0)
        return status, payload

def _ok(content):
    return {"choices": [{"message": {"content": content}}]}

def test_complete_returns_content():
    t = FakeTransport([(200, _ok('{"x":1}'))])
    out = complete("sys", "user", base_url="http://x/v1", api_key="k", model="m", transport=t)
    assert out == '{"x":1}'
    assert '"response_format"' in t.calls[0]   # 首次带 response_format

def test_complete_downgrades_on_400_response_format():
    t = FakeTransport([(400, {"error": "response_format unsupported"}), (200, _ok('{"x":2}'))])
    out = complete("sys", "user", base_url="http://x/v1", api_key="k", model="m", transport=t)
    assert out == '{"x":2}'
    assert '"response_format"' in t.calls[0]
    assert '"response_format"' not in t.calls[1]   # 第二次去掉了

def test_complete_raises_on_persistent_error():
    t = FakeTransport([(500, {}), (500, {}), (500, {}), (500, {}), (500, {})])
    with pytest.raises(LLMError):
        complete("s", "u", base_url="http://x/v1", api_key="k", model="m",
                 transport=t, max_retries=2, backoff=0)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_llm_client.py -q`
Expected: FAIL（`ImportError: cannot import name 'complete'`）。

- [ ] **Step 3: 在 llm.py 追加 client**

```python
# agent_archive/llm.py 末尾追加
import json as _json
import time
import urllib.request


class LLMError(Exception):
    pass


def _http_transport(url: str, headers: dict, body: str):
    req = urllib.request.Request(url, data=body.encode("utf-8"), headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, _json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            payload = _json.loads(e.read().decode("utf-8"))
        except Exception:
            payload = {}
        return e.code, payload


def complete(system: str, user: str, *, base_url: str, api_key: str, model: str,
             transport=_http_transport, max_retries: int = 3, backoff: float = 1.0) -> str:
    """OpenAI 兼容 chat completions。json_mode 默认开；端点 400 则去 response_format 重试一次。
    transport(url, headers, body)->(status, dict) 可注入，便于测试不联网。"""
    url = base_url.rstrip("/") + "/chat/completions"
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"}
    base_payload = {"model": model,
                    "messages": [{"role": "system", "content": system},
                                 {"role": "user", "content": user}]}

    def _once(with_fmt: bool):
        payload = dict(base_payload)
        if with_fmt:
            payload["response_format"] = {"type": "json_object"}
        return transport(url, headers, _json.dumps(payload, ensure_ascii=False))

    with_fmt = True
    last = None
    for attempt in range(max_retries + 1):
        status, data = _once(with_fmt)
        if status == 200:
            return data["choices"][0]["message"]["content"]
        last = (status, data)
        if status == 400 and with_fmt:
            with_fmt = False           # 降级：去掉 response_format 再试
            continue
        if status in (429, 500, 502, 503) and attempt < max_retries:
            time.sleep(backoff * (2 ** attempt))
            continue
        break
    raise LLMError(f"LLM request failed: {last}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_llm_client.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/llm.py tests/test_llm_client.py
git commit -m "feat(distill): LLM client（可注入 transport、429/5xx 退避、400 去 response_format 降级）"
```

---

## Task 5: distillations 表 + store 函数

**Files:** Modify `agent_archive/store.py`, Test `tests/test_store_distill.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_store_distill.py
from agent_archive import store

def _conn(tmp_path):
    c = store.connect(str(tmp_path / "a.sqlite")); store.init_db(c); return c

def _rec(conv_id="claude:s1", status="ok", topics='["电商运营"]', ch="h1"):
    return dict(conv_id=conv_id, content_hash=ch, model="m", prompt_version="distill-v1",
                status=status, summary="总结", bullets='["a"]', decisions="[]", todos="[]",
                topics=topics, value=4, redacted=1, last_error=None)

def test_upsert_and_get(tmp_path):
    c = _conn(tmp_path)
    store.upsert_distillation(c, _rec())
    r = store.get_distillation(c, "claude:s1")
    assert r["status"] == "ok" and r["model"] == "m" and r["content_hash"] == "h1"

def test_upsert_is_latest_only(tmp_path):
    c = _conn(tmp_path)
    store.upsert_distillation(c, _rec(status="error"))
    store.upsert_distillation(c, _rec(status="ok"))      # 同 conv_id 覆盖
    r = store.get_distillation(c, "claude:s1")
    assert r["status"] == "ok"
    assert c.execute("SELECT COUNT(*) FROM distillations").fetchone()[0] == 1

def test_record_error_increments_attempt(tmp_path):
    c = _conn(tmp_path)
    store.record_distill_error(c, "claude:s2", "h2", "m", "distill-v1", "boom")
    store.record_distill_error(c, "claude:s2", "h2", "m", "distill-v1", "boom2")
    r = store.get_distillation(c, "claude:s2")
    assert r["status"] == "error" and r["attempt_count"] == 2 and r["last_error"] == "boom2"

def test_by_topic_only_ok(tmp_path):
    c = _conn(tmp_path)
    store.upsert_distillation(c, _rec("claude:s1", status="ok", topics='["电商运营"]'))
    store.upsert_distillation(c, _rec("claude:s2", status="dropped", topics='["电商运营"]'))
    rows = store.distillations_by_topic(c, "电商运营")
    assert [r["conv_id"] for r in rows] == ["claude:s1"]

def test_distill_stats(tmp_path):
    c = _conn(tmp_path)
    store.upsert_distillation(c, _rec("claude:s1", status="ok"))
    store.upsert_distillation(c, _rec("claude:s2", status="dropped"))
    s = store.distill_stats(c)
    assert s["ok"] == 1 and s["dropped"] == 1
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_store_distill.py -q`
Expected: FAIL（`AttributeError: module 'agent_archive.store' has no attribute 'upsert_distillation'`）。

- [ ] **Step 3: 在 store.py 实现**

在 `SCHEMA` 字符串末尾（最后一个 `);` 之后、`"""` 之前）追加 distillations 表：

```sql
CREATE TABLE IF NOT EXISTS distillations (
  conv_id TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  status TEXT NOT NULL,
  summary TEXT, bullets TEXT, decisions TEXT, todos TEXT,
  topics TEXT, value INTEGER,
  redacted INTEGER NOT NULL DEFAULT 0,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT, last_error_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
```

在 store.py 末尾追加函数：

```python
import datetime as _dt


def _now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def upsert_distillation(conn, rec: dict) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO distillations "
        "(conv_id,content_hash,model,prompt_version,status,summary,bullets,decisions,todos,"
        " topics,value,redacted,attempt_count,last_error,last_error_at,created_at,updated_at) "
        "VALUES (:conv_id,:content_hash,:model,:prompt_version,:status,:summary,:bullets,"
        ":decisions,:todos,:topics,:value,:redacted,0,:last_error,NULL,:now,:now) "
        "ON CONFLICT(conv_id) DO UPDATE SET "
        "content_hash=excluded.content_hash, model=excluded.model, "
        "prompt_version=excluded.prompt_version, status=excluded.status, summary=excluded.summary, "
        "bullets=excluded.bullets, decisions=excluded.decisions, todos=excluded.todos, "
        "topics=excluded.topics, value=excluded.value, redacted=excluded.redacted, "
        "last_error=excluded.last_error, updated_at=excluded.updated_at",
        {**rec, "now": now})
    conn.commit()


def record_distill_error(conn, conv_id, content_hash, model, prompt_version, err) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO distillations "
        "(conv_id,content_hash,model,prompt_version,status,attempt_count,last_error,last_error_at,"
        " created_at,updated_at) "
        "VALUES (?,?,?,?, 'error', 1, ?, ?, ?, ?) "
        "ON CONFLICT(conv_id) DO UPDATE SET status='error', "
        "attempt_count=distillations.attempt_count+1, last_error=excluded.last_error, "
        "last_error_at=excluded.last_error_at, content_hash=excluded.content_hash, "
        "model=excluded.model, prompt_version=excluded.prompt_version, updated_at=excluded.updated_at",
        (conv_id, content_hash, model, prompt_version, err, now, now, now))
    conn.commit()


def get_distillation(conn, conv_id) -> dict | None:
    r = conn.execute("SELECT * FROM distillations WHERE conv_id=?", (conv_id,)).fetchone()
    return dict(r) if r else None


def distillations_by_topic(conn, topic) -> list[dict]:
    rows = conn.execute(
        "SELECT d.*, c.title, c.started_at, c.md_ref FROM distillations d "
        "JOIN conversations c ON c.id=d.conv_id "
        "WHERE d.status='ok' AND d.topics LIKE ? ORDER BY c.started_at DESC",
        (f'%"{topic}"%',)).fetchall()
    return [dict(r) for r in rows]


def distill_stats(conn) -> dict:
    out = {"ok": 0, "dropped": 0, "error": 0}
    for status, n in conn.execute("SELECT status, COUNT(*) FROM distillations GROUP BY status"):
        out[status] = n
    return out
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_store_distill.py -q`
Expected: PASS（5 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/store.py tests/test_store_distill.py
git commit -m "feat(distill): distillations 表（每会话最新+三态）与 store 函数"
```

---

## Task 6: distill 候选筛选 + 构 prompt

**Files:** Create `agent_archive/distill.py`, Test `tests/test_distill.py`（本任务先测两个纯函数）

- [ ] **Step 1: 写失败测试**

```python
# tests/test_distill.py
from agent_archive import store
from agent_archive.distill import select_candidates, build_prompt, PROSE_MIN_CHARS

def _conn(tmp_path):
    c = store.connect(str(tmp_path / "a.sqlite")); store.init_db(c); return c

def _add(conn, cid, msgs, started="2026-06-14T00:00:00Z"):
    # msgs: list of (role, kind, text)
    conn.execute("INSERT INTO conversations "
        "(id,source,title,project,started_at,updated_at,message_count,content_hash,raw_ref,md_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cid, cid.split(":")[0], "标题", "/p", started, started, len(msgs), "h_"+cid, "r", "m"))
    for i,(role,kind,text) in enumerate(msgs):
        conn.execute("INSERT INTO messages (conv_id,seq,role,ts,kind,text) VALUES (?,?,?,?,?,?)",
                     (cid, i, role, started, kind, text))
    conn.commit()

def test_select_requires_prose_both_sides_and_chars(tmp_path):
    c = _conn(tmp_path)
    long = "x"*PROSE_MIN_CHARS
    _add(c, "claude:good", [("user","prose",long),("assistant","prose","ok")])
    _add(c, "claude:onlyuser", [("user","prose",long)])                 # 缺 assistant prose
    _add(c, "claude:short", [("user","prose","hi"),("assistant","prose","yo")])  # prose 太短
    _add(c, "claude:tooly", [("user","tool","x"*9999),("assistant","tool","y"*9999)])  # 全 tool
    ids = [cv["id"] for cv in select_candidates(c)]
    assert ids == ["claude:good"]

def test_select_excludes_subagent_and_excluded_project(tmp_path):
    c = _conn(tmp_path)
    long = "x"*PROSE_MIN_CHARS
    _add(c, "claude:agent-abc", [("user","prose",long),("assistant","prose","ok")])  # 子代理
    ids = [cv["id"] for cv in select_candidates(c)]
    assert "claude:agent-abc" not in ids

def test_select_skips_cached_ok_but_retries_error(tmp_path):
    c = _conn(tmp_path)
    long = "x"*PROSE_MIN_CHARS
    _add(c, "claude:done", [("user","prose",long),("assistant","prose","ok")])
    _add(c, "claude:err", [("user","prose",long),("assistant","prose","ok")])
    store.upsert_distillation(c, dict(conv_id="claude:done", content_hash="h_claude:done",
        model="m", prompt_version="distill-v1", status="ok", summary="", bullets="[]",
        decisions="[]", todos="[]", topics='["其他"]', value=3, redacted=1, last_error=None))
    store.record_distill_error(c, "claude:err", "h_claude:err", "m", "distill-v1", "boom")
    ids = [cv["id"] for cv in select_candidates(c, model="m", prompt_version="distill-v1")]
    assert "claude:done" not in ids and "claude:err" in ids

def test_build_prompt_only_prose_redacted_truncated(tmp_path):
    c = _conn(tmp_path)
    _add(c, "claude:x", [("user","prose","我的 key 是 sk-abcdefghijklmnopqrstuvwx"),
                          ("assistant","tool","绝密工具输出"),
                          ("assistant","prose","好的")])
    system, user = build_prompt(c, "claude:x")
    assert "绝密工具输出" not in user          # tool 不进
    assert "sk-abcdefghijklmnopqrstuvwx" not in user   # 已脱敏
    assert "好的" in user
    assert "电商运营" in system               # 受控词表在 system 里给出

def test_build_prompt_truncates_overlong(tmp_path):
    from agent_archive.distill import MAX_PROMPT_CHARS
    c = _conn(tmp_path)
    big = "甲" * (MAX_PROMPT_CHARS * 2)        # 远超上限的单条 prose
    _add(c, "claude:big", [("user","prose",big),("assistant","prose","乙乙乙")])
    _, user = build_prompt(c, "claude:big")
    assert "…[中间省略]…" in user              # 走了首尾各半的截断分支
    assert len(user) < MAX_PROMPT_CHARS + 200  # 截断后受控（含省略标记的余量）
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_distill.py -q`
Expected: FAIL（`ModuleNotFoundError: agent_archive.distill`）。

- [ ] **Step 3: 实现 distill.py（候选 + prompt 部分）**

```python
# agent_archive/distill.py
from __future__ import annotations
from agent_archive.redact import redact
from agent_archive.topics import TOPICS

PROMPT_VERSION = "distill-v1"
PROSE_MIN_CHARS = 200
MAX_PROMPT_CHARS = 12000
VALUE_MIN = 2
MAX_ATTEMPTS = 3

# 已知的系统注入开场前缀，构 prompt 时丢掉首句省 token
_SYS_OPENERS = ("You are running as", "The following is the Codex", "<local-command-caveat")


def _native_id(conv_id: str) -> str:
    return conv_id.split(":", 1)[-1]


def select_candidates(conn, model: str = "", prompt_version: str = PROMPT_VERSION,
                      exclude_projects: tuple = ()) -> list[dict]:
    rows = conn.execute("""
        SELECT c.*,
          SUM(CASE WHEN m.kind='prose' AND m.role='user' THEN 1 ELSE 0 END) up,
          SUM(CASE WHEN m.kind='prose' AND m.role='assistant' THEN 1 ELSE 0 END) ap,
          SUM(CASE WHEN m.kind='prose' THEN LENGTH(m.text) ELSE 0 END) pc
        FROM conversations c JOIN messages m ON m.conv_id=c.id
        GROUP BY c.id
    """).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if not (d["up"] >= 1 and d["ap"] >= 1 and (d["pc"] or 0) >= PROSE_MIN_CHARS):
            continue
        if _native_id(d["id"]).startswith("agent-"):
            continue
        if d.get("project") in exclude_projects:
            continue
        prev = conn.execute("SELECT status,content_hash,model,prompt_version,attempt_count "
                            "FROM distillations WHERE conv_id=?", (d["id"],)).fetchone()
        if prev:
            same = (prev["content_hash"] == d["content_hash"]
                    and prev["model"] == model and prev["prompt_version"] == prompt_version)
            if prev["status"] in ("ok", "dropped") and same:
                continue
            if prev["status"] == "error" and prev["attempt_count"] >= MAX_ATTEMPTS:
                continue
        out.append(d)
    return out


def build_prompt(conn, conv_id: str):
    rows = conn.execute("SELECT role, text FROM messages "
                        "WHERE conv_id=? AND kind='prose' ORDER BY seq", (conv_id,)).fetchall()
    parts = []
    for i, r in enumerate(rows):
        txt = r["text"] or ""
        if i == 0 and any(txt.lstrip().startswith(p) for p in _SYS_OPENERS):
            continue  # 丢掉系统注入开场首句
        parts.append(f'{r["role"]}: {txt}')
    body = "\n\n".join(parts)
    if len(body) > MAX_PROMPT_CHARS:                 # 超长取首尾各半
        half = MAX_PROMPT_CHARS // 2
        body = body[:half] + "\n…[中间省略]…\n" + body[-half:]
    body = redact(body)
    system = (
        "你是知识整理助手。阅读一段我与 AI 的对话，提炼成结构化 JSON。"
        "只输出 JSON，不要任何其他文字。字段：summary(一句话中文总结)、"
        "bullets(3-5 条要点)、decisions(关键决策，可空数组)、todos(待办，可空数组)、"
        "topics(从下列固定标签中选 1-3 个，不得自造)、value(0-5 价值分)、drop(是否无价值 true/false)。"
        f"可选 topics：{TOPICS}。所有文本用中文。"
    )
    return system, body
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_distill.py -q`
Expected: PASS（5 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/distill.py tests/test_distill.py
git commit -m "feat(distill): 候选筛选(prose信号/排除子代理/跳过缓存可重试error) + 构 prompt(仅prose/脱敏/截断)"
```

---

## Task 7: distill_one + run 编排

**Files:** Modify `agent_archive/distill.py`, Modify `tests/test_distill.py`

- [ ] **Step 1: 追加失败测试**

```python
# tests/test_distill.py 末尾追加
import json
from agent_archive.distill import distill_one, run

def _fake_complete(content):
    def _c(system, user, **kw):
        return content
    return _c

def test_distill_one_ok_redacts_output(tmp_path):
    c = _conn(tmp_path)
    _add(c, "claude:x", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    payload = json.dumps({"summary":"用户的邮箱是 a@b.com","bullets":["b1"],"decisions":[],
                          "todos":[],"topics":["电商运营","瞎编"],"value":4,"drop":False})
    rec = distill_one(c, "claude:x", _fake_complete(payload))
    assert rec["status"] == "ok"
    assert "a@b.com" not in rec["summary"]        # 输出回程脱敏
    assert json.loads(rec["topics"]) == ["电商运营"]  # 词表收敛
    assert rec["redacted"] == 1

def test_distill_one_retries_bad_json_then_succeeds(tmp_path):
    c = _conn(tmp_path)
    _add(c, "claude:r", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    good = json.dumps({"summary":"s","bullets":["b"],"decisions":[],"todos":[],
                       "topics":["其他"],"value":3,"drop":False})
    seq = ["这不是JSON", good]                  # 第一次坏、第二次好
    def complete(system, user, **kw):
        return seq.pop(0)
    rec = distill_one(c, "claude:r", complete)
    assert rec["status"] == "ok" and seq == []   # 重试一次后成功

def test_distill_one_drop_or_lowvalue(tmp_path):
    c = _conn(tmp_path)
    _add(c, "claude:y", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    payload = json.dumps({"summary":"s","bullets":[],"decisions":[],"todos":[],
                          "topics":["其他"],"value":0,"drop":True})
    rec = distill_one(c, "claude:y", _fake_complete(payload))
    assert rec["status"] == "dropped"

def test_run_isolates_failures(tmp_path):
    c = _conn(tmp_path)
    _add(c, "claude:a", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    _add(c, "claude:b", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    good = json.dumps({"summary":"s","bullets":["b"],"decisions":[],"todos":[],
                       "topics":["其他"],"value":3,"drop":False})
    calls = {"n": 0}
    def complete(system, user, **kw):       # 第一个会话失败，第二个成功
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return good
    res = run(c, complete, model="m")
    assert res["failed"] == 1 and res["ok"] == 1
    errs = c.execute("SELECT COUNT(*) FROM distillations WHERE status='error'").fetchone()[0]
    assert errs == 1                         # 失败入库为 error，下次可重试
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_distill.py -k "distill_one or run" -q`
Expected: FAIL（`ImportError: cannot import name 'distill_one'`）。

- [ ] **Step 3: 在 distill.py 追加 distill_one + run**

```python
# agent_archive/distill.py 末尾追加
import json
from agent_archive.llm import extract_json
from agent_archive.topics import normalize_topics
from agent_archive import store


def distill_one(conn, conv_id: str, complete, model: str = "") -> dict:
    """对单会话调模型并解析，输出回程脱敏，返回已 upsert 的记录 dict。"""
    system, user = build_prompt(conn, conv_id)
    ch = conn.execute("SELECT content_hash FROM conversations WHERE id=?", (conv_id,)).fetchone()[0]
    raw = complete(system, user, model=model)
    try:
        data = extract_json(raw)
    except ValueError:                            # 坏 JSON：用更强约束重试一次（设计要求）
        raw2 = complete(system + "\n严格只输出 JSON，不要任何其他文字、不要代码围栏。",
                        user, model=model)
        data = extract_json(raw2)                  # 再失败则抛 ValueError，由 run 记 error
    def _red_list(xs):
        return [redact(str(x)) for x in (xs or [])]
    topics = normalize_topics(data.get("topics") or [])
    dropped = bool(data.get("drop")) or int(data.get("value") or 0) < VALUE_MIN
    rec = dict(
        conv_id=conv_id, content_hash=ch, model=model, prompt_version=PROMPT_VERSION,
        status="dropped" if dropped else "ok",
        summary=redact(str(data.get("summary") or "")),
        bullets=json.dumps(_red_list(data.get("bullets")), ensure_ascii=False),
        decisions=json.dumps(_red_list(data.get("decisions")), ensure_ascii=False),
        todos=json.dumps(_red_list(data.get("todos")), ensure_ascii=False),
        topics=json.dumps(topics, ensure_ascii=False),
        value=int(data.get("value") or 0), redacted=1, last_error=None)
    store.upsert_distillation(conn, rec)
    return rec


def run(conn, complete, *, model: str = "", limit=None, exclude_projects: tuple = ()) -> dict:
    cands = select_candidates(conn, model=model, exclude_projects=exclude_projects)
    if limit:
        cands = cands[:limit]
    res = {"ok": 0, "dropped": 0, "failed": 0, "skipped": 0}
    for cv in cands:
        try:
            rec = distill_one(conn, cv["id"], complete, model=model)
            res["ok" if rec["status"] == "ok" else "dropped"] += 1
        except Exception as e:                    # 每会话隔离：入库 error，可重试
            ch = cv["content_hash"]
            store.record_distill_error(conn, cv["id"], ch, model, PROMPT_VERSION, str(e)[:500])
            res["failed"] += 1
    return res
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_distill.py -q`
Expected: PASS（全部 distill 测试通过）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/distill.py tests/test_distill.py
git commit -m "feat(distill): distill_one(输出脱敏+词表收敛+drop/低分) + run(每会话错误隔离入库)"
```

---

## Task 8: 渲染精华卡 + 主题页 + 对账清理

**Files:** Create `agent_archive/render_distill.py`, Test `tests/test_render_distill.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_render_distill.py
import os, json
from agent_archive import store
from agent_archive.render_distill import render_all, GENERATED_MARK

def _conn(tmp_path):
    c = store.connect(str(tmp_path / "a.sqlite")); store.init_db(c); return c

def _conv(conn, cid, started="2026-06-14T00:00:00Z"):
    conn.execute("INSERT INTO conversations "
        "(id,source,title,project,started_at,updated_at,message_count,content_hash,raw_ref,md_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cid, cid.split(':')[0], "标题", "/p", started, started, 3, "h", "r", "m")); conn.commit()

def _dist(conn, cid, status="ok", topics='["电商运营"]'):
    store.upsert_distillation(conn, dict(conv_id=cid, content_hash="h", model="m",
        prompt_version="distill-v1", status=status, summary="一句话", bullets='["要点"]',
        decisions="[]", todos="[]", topics=topics, value=4, redacted=1, last_error=None))

def test_render_writes_card_and_topic(tmp_path):
    c = _conn(tmp_path); _conv(c, "claude:s1"); _dist(c, "claude:s1")
    root = str(tmp_path / "arc")
    render_all(c, root)
    cards = list((tmp_path / "arc" / "distilled").rglob("*.md"))
    assert len(cards) == 1
    assert GENERATED_MARK in cards[0].read_text(encoding="utf-8")   # 自有标记
    topic = tmp_path / "arc" / "topics" / "电商运营.md"
    assert topic.exists() and "一句话" in topic.read_text(encoding="utf-8")

def test_dropped_card_removed_on_rerun(tmp_path):
    c = _conn(tmp_path); _conv(c, "claude:s1"); _dist(c, "claude:s1")
    root = str(tmp_path / "arc"); render_all(c, root)
    assert list((tmp_path / "arc" / "distilled").rglob("*.md"))
    _dist(c, "claude:s1", status="dropped")     # 翻成 dropped
    render_all(c, root)
    assert not list((tmp_path / "arc" / "distilled").rglob("*.md"))   # 旧卡被删

def test_does_not_delete_user_files(tmp_path):
    c = _conn(tmp_path); _conv(c, "claude:s1"); _dist(c, "claude:s1")
    root = tmp_path / "arc"; (root / "distilled" / "2026-06-14").mkdir(parents=True)
    user_md = root / "distilled" / "2026-06-14" / "我的手写.md"
    user_md.write_text("# 用户手写，无标记", encoding="utf-8")
    render_all(c, str(root))
    assert user_md.exists()     # 无 generated_by 标记的文件不被删
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_render_distill.py -q`
Expected: FAIL（`ModuleNotFoundError: agent_archive.render_distill`）。

- [ ] **Step 3: 实现 render_distill.py**

```python
# agent_archive/render_distill.py
from __future__ import annotations
import os, re, json, glob
from agent_archive import store
from agent_archive.topics import TOPICS

GENERATED_MARK = "generated_by: agent-archive-distill"


def _slug(s: str) -> str:
    return (re.sub(r"[\\/:*?\"<>|\n\r\t ]+", "_", s).strip("_") or "untitled")[:40]


def _is_ours(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            return GENERATED_MARK in f.read(400)
    except OSError:
        return False


def _clear_owned(dir_path: str):
    for p in glob.glob(os.path.join(dir_path, "**", "*.md"), recursive=True):
        if _is_ours(p):
            os.remove(p)


def _card_md(d: dict) -> str:
    bullets = "\n".join(f"- {b}" for b in json.loads(d["bullets"] or "[]"))
    decisions = "\n".join(f"- {x}" for x in json.loads(d["decisions"] or "[]"))
    todos = "\n".join(f"- [ ] {x}" for x in json.loads(d["todos"] or "[]"))
    topics = json.loads(d["topics"] or "[]")
    fm = ["---", GENERATED_MARK, f"conv_id: {d['conv_id']}", f"source: {d['source']}",
          f"topics: {topics}", f"value: {d['value']}", f"redacted: {bool(d['redacted'])}",
          f"raw_ref: {d['raw_ref']}", f"md_ref: {d['md_ref']}", "---", ""]
    body = [f"# {d['title']}", "", f"> {d['summary']}", ""]
    if bullets: body += ["## 要点", bullets, ""]
    if decisions: body += ["## 决策", decisions, ""]
    if todos: body += ["## 待办", todos, ""]
    return "\n".join(fm + body)


def render_all(conn, archive_root: str) -> dict:
    distilled = os.path.join(archive_root, "distilled")
    topics_dir = os.path.join(archive_root, "topics")
    os.makedirs(distilled, exist_ok=True); os.makedirs(topics_dir, exist_ok=True)
    # 对账：先删自有旧文件，再按 DB 重写（绝不裸清目录）
    _clear_owned(distilled); _clear_owned(topics_dir)

    rows = conn.execute(
        "SELECT d.*, c.title, c.source, c.started_at, c.raw_ref, c.md_ref "
        "FROM distillations d JOIN conversations c ON c.id=d.conv_id "
        "WHERE d.status='ok'").fetchall()
    n = 0
    for r in rows:
        d = dict(r)
        day = (d["started_at"] or "")[:10] or "0000-00-00"
        sub = os.path.join(distilled, day); os.makedirs(sub, exist_ok=True)
        name = f"{d['source']}__{_slug(d['title'])}__{d['conv_id'].split(':',1)[-1]}.md"
        with open(os.path.join(sub, name), "w", encoding="utf-8") as f:
            f.write(_card_md(d))
        n += 1

    for topic in TOPICS:
        items = store.distillations_by_topic(conn, topic)
        if not items:
            continue
        lines = ["---", GENERATED_MARK, f"topic: {topic}", "---", "", f"# 主题：{topic}", ""]
        for it in items:
            day = (it["started_at"] or "")[:10]
            lines.append(f"- [{day}] {it['summary']}  （{it['title']}）")
        with open(os.path.join(topics_dir, f"{_slug(topic)}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return {"cards": n}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_render_distill.py -q`
Expected: PASS（3 passed）。

- [ ] **Step 5: Commit**

```bash
git add agent_archive/render_distill.py tests/test_render_distill.py
git commit -m "feat(distill): 渲染精华卡+主题页，对账只删带 generated_by 标记的文件"
```

---

## Task 9: CLI distill / topics / distill-stats（含 --dry-run 免 key）

**Files:** Modify `agent_archive/cli.py`, Test `tests/test_cli_distill.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_cli_distill.py
import os, json
from agent_archive import cli, store

def _seed(tmp_path):
    root = str(tmp_path / "arc")
    os.makedirs(root, exist_ok=True)
    conn = store.connect(os.path.join(root, "index.sqlite")); store.init_db(conn)
    conn.execute("INSERT INTO conversations "
        "(id,source,title,project,started_at,updated_at,message_count,content_hash,raw_ref,md_ref) "
        "VALUES ('claude:s1','claude','标题','/p','2026-06-14T00:00:00Z','2026-06-14T00:00:00Z',2,'h','r','m')")
    for i,(role,kind,text) in enumerate([("user","prose","x"*300),("assistant","prose","好的")]):
        conn.execute("INSERT INTO messages (conv_id,seq,role,ts,kind,text) VALUES (?,?,?,?,?,?)",
                     ("claude:s1", i, role, "t", kind, text))
    conn.commit(); conn.close()
    return root

def test_dry_run_needs_no_api_key(tmp_path, monkeypatch, capsys):
    root = _seed(tmp_path)
    monkeypatch.delenv("AGENT_ARCHIVE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_ARCHIVE_LLM_BASE_URL", raising=False)
    assert cli.main(["--root", root, "distill", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "claude:s1" in out and "1" in out      # 列出将外发的会话

def test_distill_stats(tmp_path, capsys):
    root = _seed(tmp_path)
    conn = store.connect(os.path.join(root, "index.sqlite"))
    store.upsert_distillation(conn, dict(conv_id="claude:s1", content_hash="h", model="m",
        prompt_version="distill-v1", status="ok", summary="s", bullets="[]", decisions="[]",
        todos="[]", topics='["其他"]', value=3, redacted=1, last_error=None)); conn.close()
    assert cli.main(["--root", root, "distill-stats"]) == 0
    assert "ok" in capsys.readouterr().out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `.venv/bin/python -m pytest tests/test_cli_distill.py -q`
Expected: FAIL（argparse 无 `distill` 子命令 → SystemExit）。

- [ ] **Step 3: 在 cli.py 加子命令**

在 `cli.py` 顶部已有 `import os, argparse, datetime, collections`；追加导入：
```python
from agent_archive import distill as distill_mod, render_distill, llm as llm_mod
```

在 `sub.add_parser("stats")` 之后追加：
```python
    pds = sub.add_parser("distill")
    pds.add_argument("--limit", type=int, default=None)
    pds.add_argument("--exclude-project", action="append", default=[])
    pds.add_argument("--dry-run", action="store_true")
    pds.add_argument("--yes", action="store_true")

    sub.add_parser("topics")
    sub.add_parser("distill-stats")
```

在 `if args.cmd == "stats":` 分支之后、`return 1` 之前追加：
```python
    if args.cmd == "distill":
        cands = distill_mod.select_candidates(
            conn, model=os.environ.get("AGENT_ARCHIVE_LLM_MODEL", ""),
            exclude_projects=tuple(args.exclude_project))
        if args.limit:
            cands = cands[:args.limit]
        if args.dry_run:                      # 免 key：只列将外发的会话 + 一个脱敏样例
            print(f"[dry-run] 将外发 {len(cands)} 个会话至 "
                  f"{os.environ.get('AGENT_ARCHIVE_LLM_BASE_URL','(未配置)')}")
            for cv in cands:
                print(f"  {cv['id']}  {cv['title'][:40]}")
            if cands:
                _, sample = distill_mod.build_prompt(conn, cands[0]["id"])
                print("\n--- 脱敏后 prompt 样例（首个会话，截断）---\n" + sample[:600])
            return 0
        base = os.environ.get("AGENT_ARCHIVE_LLM_BASE_URL")
        key = os.environ.get("AGENT_ARCHIVE_LLM_API_KEY")
        model = os.environ.get("AGENT_ARCHIVE_LLM_MODEL")
        if not (base and key and model):
            print("缺配置：请设 AGENT_ARCHIVE_LLM_BASE_URL / _API_KEY / _MODEL")
            return 2
        if not args.yes:
            print(f"将把 {len(cands)} 个会话外发至 {base}（model={model}）。加 --yes 确认执行。")
            return 0
        def complete(system, user, **kw):
            return llm_mod.complete(system, user, base_url=base, api_key=key, model=model)
        res = distill_mod.run(conn, complete, model=model, limit=args.limit,
                              exclude_projects=tuple(args.exclude_project))
        render_distill.render_all(conn, root)
        print(f"ok={res['ok']} dropped={res['dropped']} failed={res['failed']}")
        return 0
    if args.cmd == "topics":
        render_distill.render_all(conn, root)
        print("主题页已重建")
        return 0
    if args.cmd == "distill-stats":
        for status, n in store.distill_stats(conn).items():
            print(f"{status}: {n}")
        return 0
```

- [ ] **Step 4: 跑测试确认通过**

Run: `.venv/bin/python -m pytest tests/test_cli_distill.py -q`
Expected: PASS（2 passed）。

- [ ] **Step 5: 全量测试**

Run: `.venv/bin/python -m pytest -q`
Expected: 全绿（P1 既有 + distill 新增）。

- [ ] **Step 6: Commit**

```bash
git add agent_archive/cli.py tests/test_cli_distill.py
git commit -m "feat(distill): CLI distill/topics/distill-stats（--dry-run 免 key、--yes 确认外发）"
```

---

## Task 10: README 配置说明 + Obsidian 软链 + dry-run 真实数据冒烟

**Files:** Modify `README.md`

- [ ] **Step 1: 在 README 追加 distill 段**

```markdown
## 精炼（distill，可选，需第三方 LLM）

把会话提炼成结构化精华卡 + 主题页（写进 distilled/ 与 topics/）。**会把 prose 正文外发第三方 API**——见下方隐私说明。

配置（OpenAI 兼容，任选 DeepSeek / OpenAI / 自建代理）：

    export AGENT_ARCHIVE_LLM_BASE_URL=https://api.deepseek.com/v1
    export AGENT_ARCHIVE_LLM_API_KEY=sk-xxxx
    export AGENT_ARCHIVE_LLM_MODEL=deepseek-chat

用法：

    agent-archive distill --dry-run         # 免 key，先看会外发哪些会话 + 脱敏样例
    agent-archive distill --limit 10 --yes  # 试跑 10 个
    agent-archive distill --yes             # 全量（顺序，约 15-35 分钟）
    agent-archive distill --exclude-project /Users/mac/secret --yes   # 排除敏感项目
    agent-archive topics                    # 重建主题页
    agent-archive distill-stats             # ok/dropped/error 计数

### 隐私（重要）
- distill **会把会话 prose 外发**（不发工具输出、发送前脱敏、模型输出回程再脱敏）。
- 脱敏是尽力而为，**不是保证**；敏感项目用 `--exclude-project` 直接排除。
- distill **不进每日定时**，只在你手动执行时运行。
- 软链产物进 Obsidian（可选）：
      ln -s ~/agent-archive-data/distilled "~/Documents/Obsidian Vault/精华"
      ln -s ~/agent-archive-data/topics    "~/Documents/Obsidian Vault/主题"
```

- [ ] **Step 2: dry-run 真实数据冒烟（不外发、免 key）**

Run:
```bash
AGENT_ARCHIVE_ROOT=~/agent-archive-data .venv/bin/python -m agent_archive.cli distill --dry-run --limit 5
```
Expected: 打印将外发的候选会话（应来自真实库、约 5 个）+ 一段脱敏后的 prompt 样例，**全程不联网、无需 key**。粘贴输出到报告。

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs(distill): README 配置/用法/隐私 + Obsidian 软链"
```

---

## 后续（不在本计划内）
- 首次真实全量 distill（需用户配 LLM 凭证后手动 `--yes`）。
- 主题页"其他"里高频主题提升为正式大类（人工/单独一轮）。
- 并发处理、语义检索层（北极星后续）。
