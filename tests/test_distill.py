from agent_archive import store
from agent_archive.distill import select_candidates, build_prompt, PROSE_MIN_CHARS, MAX_PROMPT_CHARS

def _conn(tmp_path):
    c = store.connect(str(tmp_path / "a.sqlite")); store.init_db(c); return c

def _add(conn, cid, msgs, started="2026-06-14T00:00:00Z"):
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
    _add(c, "claude:onlyuser", [("user","prose",long)])
    _add(c, "claude:short", [("user","prose","hi"),("assistant","prose","yo")])
    _add(c, "claude:tooly", [("user","tool","x"*9999),("assistant","tool","y"*9999)])
    ids = [cv["id"] for cv in select_candidates(c)]
    assert ids == ["claude:good"]

def test_select_excludes_subagent_and_excluded_project(tmp_path):
    c = _conn(tmp_path)
    long = "x"*PROSE_MIN_CHARS
    _add(c, "claude:agent-abc", [("user","prose",long),("assistant","prose","ok")])
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
    assert "绝密工具输出" not in user
    assert "sk-abcdefghijklmnopqrstuvwx" not in user
    assert "好的" in user
    assert "电商运营" in system

def test_build_prompt_truncates_overlong(tmp_path):
    c = _conn(tmp_path)
    big = "甲" * (MAX_PROMPT_CHARS * 2)
    _add(c, "claude:big", [("user","prose",big),("assistant","prose","乙乙乙")])
    _, user = build_prompt(c, "claude:big")
    assert "…[中间省略]…" in user
    assert len(user) < MAX_PROMPT_CHARS + 200
