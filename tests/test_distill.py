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
    assert "a@b.com" not in rec["summary"]
    assert json.loads(rec["topics"]) == ["电商运营"]
    assert rec["redacted"] == 1

def test_distill_one_retries_bad_json_then_succeeds(tmp_path):
    c = _conn(tmp_path)
    _add(c, "claude:r", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    good = json.dumps({"summary":"s","bullets":["b"],"decisions":[],"todos":[],
                       "topics":["其他"],"value":3,"drop":False})
    seq = ["这不是JSON", good]
    def complete(system, user, **kw):
        return seq.pop(0)
    rec = distill_one(c, "claude:r", complete)
    assert rec["status"] == "ok" and seq == []

def test_distill_one_drop_or_lowvalue(tmp_path):
    c = _conn(tmp_path)
    _add(c, "claude:y", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    payload = json.dumps({"summary":"s","bullets":[],"decisions":[],"todos":[],
                          "topics":["其他"],"value":0,"drop":True})
    rec = distill_one(c, "claude:y", _fake_complete(payload))
    assert rec["status"] == "dropped"

def test_distill_one_handles_string_value_and_string_list_fields(tmp_path):
    c = _conn(tmp_path)
    _add(c, "claude:z", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    payload = json.dumps({"summary":"s","bullets":"要点一, 要点二","decisions":[],"todos":[],
                          "topics":["其他"],"value":"high","drop":False})
    rec = distill_one(c, "claude:z", _fake_complete(payload))
    assert rec["status"] == "dropped"                       # "high"→0 < VALUE_MIN
    assert json.loads(rec["bullets"]) == ["要点一, 要点二"]   # 整条，不按字符拆

def test_distill_one_numeric_string_value(tmp_path):
    c = _conn(tmp_path)
    _add(c, "claude:n", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    payload = json.dumps({"summary":"s","bullets":["b"],"decisions":[],"todos":[],
                          "topics":["其他"],"value":"4","drop":False})
    rec = distill_one(c, "claude:n", _fake_complete(payload))
    assert rec["status"] == "ok" and rec["value"] == 4

def test_run_isolates_failures(tmp_path):
    c = _conn(tmp_path)
    _add(c, "claude:a", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    _add(c, "claude:b", [("user","prose","x"*PROSE_MIN_CHARS),("assistant","prose","ok")])
    good = json.dumps({"summary":"s","bullets":["b"],"decisions":[],"todos":[],
                       "topics":["其他"],"value":3,"drop":False})
    calls = {"n": 0}
    def complete(system, user, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return good
    res = run(c, complete, model="m")
    assert res["failed"] == 1 and res["ok"] == 1
    errs = c.execute("SELECT COUNT(*) FROM distillations WHERE status='error'").fetchone()[0]
    assert errs == 1
