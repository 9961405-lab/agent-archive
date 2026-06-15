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
    store.upsert_distillation(c, _rec(status="ok"))
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
    # by_topic JOIN 需要 conversations 行存在
    for cid in ("claude:s1", "claude:s2"):
        c.execute("INSERT INTO conversations "
            "(id,source,title,project,started_at,updated_at,message_count,content_hash,raw_ref,md_ref) "
            "VALUES (?,?,?,?,?,?,?,?,?,?)",
            (cid, "claude", "标题", "/p", "2026-06-14T00:00:00Z", "2026-06-14T00:00:00Z", 3, "h", "r", "m"))
    c.commit()
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
