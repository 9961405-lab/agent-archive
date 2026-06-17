from agent_archive import store, mcp_tools


def _conn(tmp_path):
    c = store.connect(str(tmp_path / "a.sqlite")); store.init_db(c); return c


def _conv(conn, cid, title, started="2026-06-15T01:00:00Z", msgs=None):
    conn.execute("INSERT INTO conversations "
        "(id,source,title,project,started_at,updated_at,message_count,content_hash,raw_ref,md_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cid, cid.split(':')[0], title, "/p/proj", started, started,
         len(msgs or []), "h", "r", "m"))
    for i, (role, kind, text) in enumerate(msgs or []):
        conn.execute("INSERT INTO messages (conv_id,seq,role,ts,kind,text) VALUES (?,?,?,?,?,?)",
                     (cid, i, role, started, kind, text))
        if kind == "prose" and text:
            conn.execute("INSERT INTO messages_fts (text,conv_id,role) VALUES (?,?,?)",
                         (store._segment(text), cid, role))
    conn.commit()


def _dist(conn, cid, summary="一句话", topics='["电商运营"]', value=4):
    store.upsert_distillation(conn, dict(conv_id=cid, content_hash="h", model="m",
        prompt_version="distill-v1", status="ok", summary=summary, bullets='["b"]',
        decisions="[]", todos="[]", topics=topics, value=value, redacted=1, last_error=None))


def test_search(tmp_path):
    c = _conn(tmp_path)
    _conv(c, "claude:a", "标题", msgs=[("user", "prose", "帮我核对订单金额"),
                                       ("assistant", "prose", "好的")])
    hits = mcp_tools.search(c, "订单")
    assert len(hits) == 1 and hits[0]["conv_id"] == "claude:a"


def test_get_conversation_prose_only(tmp_path):
    c = _conn(tmp_path)
    _conv(c, "claude:a", "标题", msgs=[("user", "prose", "真实提问"),
                                       ("assistant", "tool", "绝密工具输出"),
                                       ("assistant", "prose", "回答")])
    conv = mcp_tools.get_conversation(c, "claude:a")
    texts = [m["text"] for m in conv["messages"]]
    assert "真实提问" in texts and "回答" in texts
    assert "绝密工具输出" not in texts          # tool 不返回


def test_get_conversation_missing(tmp_path):
    c = _conn(tmp_path)
    assert "error" in mcp_tools.get_conversation(c, "claude:none")


def test_get_conversation_truncates(tmp_path):
    c = _conn(tmp_path)
    big = "字" * (mcp_tools.GET_CONV_MAX_CHARS + 500)
    _conv(c, "claude:b", "标题", msgs=[("user", "prose", big), ("assistant", "prose", "尾巴")])
    conv = mcp_tools.get_conversation(c, "claude:b")
    assert any("截断" in m["text"] for m in conv["messages"])


def test_digest_and_topics(tmp_path):
    c = _conn(tmp_path)
    _conv(c, "claude:a", "标题", started="2026-06-15T01:00:00Z",
          msgs=[("user", "prose", "x" * 50), ("assistant", "prose", "y")])
    _dist(c, "claude:a", summary="搞定订单", topics='["电商运营","工具脚本"]', value=5)
    assert "电商运营" in mcp_tools.digest(c, "day", "2026-06-15")
    topics = mcp_tools.list_topics(c)
    assert {"topic": "电商运营", "count": 1} in topics
    bt = mcp_tools.by_topic(c, "电商运营")
    assert bt and bt[0]["summary"] == "搞定订单"


def test_day_and_recent(tmp_path):
    c = _conn(tmp_path)
    _conv(c, "claude:a", "今天的", started="2026-06-15T01:00:00Z")
    assert mcp_tools.day(c, "2026-06-15")[0]["conv_id"] == "claude:a"
    assert len(mcp_tools.recent(c)) == 1
