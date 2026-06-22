import os, json, sqlite3, time
import pytest
from agent_archive.collectors.hermes import HermesCollector


def _make_db(path: str):
    """构造一个最小 Hermes state.db：两个 session，含 prose / tool / tool_call / system。"""
    conn = sqlite3.connect(path)
    conn.executescript("""
    CREATE TABLE sessions (
        id TEXT PRIMARY KEY, source TEXT NOT NULL, user_id TEXT, model TEXT,
        model_config TEXT, system_prompt TEXT, parent_session_id TEXT,
        started_at REAL NOT NULL, ended_at REAL, end_reason TEXT,
        message_count INTEGER DEFAULT 0, tool_call_count INTEGER DEFAULT 0,
        input_tokens INTEGER, output_tokens INTEGER, cache_read_tokens INTEGER,
        cache_write_tokens INTEGER, reasoning_tokens INTEGER,
        cwd TEXT, billing_provider TEXT, billing_base_url TEXT,
        billing_mode TEXT, estimated_cost_usd REAL, actual_cost_usd REAL,
        cost_status TEXT, cost_source TEXT, pricing_version TEXT,
        title TEXT, api_call_count INTEGER, handoff_state TEXT,
        handoff_platform TEXT, handoff_error TEXT,
        rewind_count INTEGER NOT NULL DEFAULT 0,
        archived INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT NOT NULL,
        role TEXT NOT NULL, content TEXT, tool_call_id TEXT, tool_calls TEXT,
        tool_name TEXT, timestamp REAL NOT NULL, token_count INTEGER,
        finish_reason TEXT, reasoning TEXT, reasoning_content TEXT,
        reasoning_details TEXT, codex_reasoning_items TEXT,
        codex_message_items TEXT, platform_message_id TEXT,
        observed INTEGER DEFAULT 0, active INTEGER NOT NULL DEFAULT 1
    );
    """)
    # session A：含 prose + tool_call + tool + system（system 不入正文）
    t = 1750000000.0
    conn.execute(
        "INSERT INTO sessions (id, source, title, started_at, ended_at, cwd, model) "
        "VALUES (?,?,?,?,?,?,?)",
        ("sess-a", "tui", "标题A", t, t + 60, "/p/proj", "deepseek-v4"))
    rows = [
        ("sess-a", "user", "帮我看看订单", None, None, t + 1),
        ("sess-a", "system", "系统提示别看", None, None, t + 2),
        ("sess-a", "assistant", "好的", None, None, t + 3),
        ("sess-a", "assistant", "", json.dumps(
            [{"id": "c1", "function": {"name": "shell", "arguments": "ls"}}]),
         None, t + 4),
        ("sess-a", "tool", '{"output": "file.txt"}', None, "shell", t + 5),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO messages (session_id, role, content, tool_calls, "
            "tool_name, timestamp) VALUES (?,?,?,?,?,?)", r)
    # session B：归档的应被跳过
    conn.execute(
        "INSERT INTO sessions (id, source, title, started_at, archived) "
        "VALUES (?,?,?,?,?)", ("sess-b", "tui", "归档", t, 1))
    conn.commit(); conn.close()


def test_discover_dumps_active_sessions_only(tmp_path):
    db = tmp_path / "state.db"; _make_db(str(db))
    col = HermesCollector(db_path=str(db),
                          export_dir=str(tmp_path / "exp"))
    refs = list(col.discover())
    assert [r.native_id for r in refs] == ["sess-a"]
    assert os.path.exists(refs[0].path)


def test_parse_skips_system_and_marks_tool(tmp_path):
    db = tmp_path / "state.db"; _make_db(str(db))
    col = HermesCollector(db_path=str(db),
                          export_dir=str(tmp_path / "exp"))
    (ref,) = list(col.discover())
    conv = col.parse(ref)
    assert conv.id == "hermes:sess-a"
    assert conv.title == "标题A"
    assert conv.project == "/p/proj"
    kinds = [(m.role, m.kind, m.text[:20], m.tool) for m in conv.messages]
    # system 不应出现
    assert all("系统提示别看" not in m.text for m in conv.messages)
    # 用户/助手 prose 在
    prose = [m for m in conv.messages if m.kind == "prose"]
    assert any("订单" in m.text for m in prose)
    # 工具调用 + 工具结果
    tools = [m for m in conv.messages if m.kind == "tool"]
    assert any(m.tool == "shell" and m.role == "assistant" for m in tools)
    assert any(m.tool == "shell" and m.role == "tool" for m in tools)


def test_discover_idempotent_mtime_stable(tmp_path):
    db = tmp_path / "state.db"; _make_db(str(db))
    col = HermesCollector(db_path=str(db),
                          export_dir=str(tmp_path / "exp"))
    r1 = list(col.discover())[0]
    time.sleep(0.05)
    r2 = list(col.discover())[0]
    # 内容未变 → mtime / size 必须一致，才能让 sync 走 skip 分支
    assert (r1.mtime, r1.size) == (r2.mtime, r2.size)


def test_missing_db_yields_nothing(tmp_path):
    col = HermesCollector(db_path=str(tmp_path / "nope.db"),
                          export_dir=str(tmp_path / "exp"))
    assert list(col.discover()) == []
