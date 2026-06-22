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
    assert GENERATED_MARK in cards[0].read_text(encoding="utf-8")
    topic = tmp_path / "arc" / "topics" / "电商运营.md"
    assert topic.exists() and "一句话" in topic.read_text(encoding="utf-8")

def test_dropped_card_removed_on_rerun(tmp_path):
    c = _conn(tmp_path); _conv(c, "claude:s1"); _dist(c, "claude:s1")
    root = str(tmp_path / "arc"); render_all(c, root)
    assert list((tmp_path / "arc" / "distilled").rglob("*.md"))
    _dist(c, "claude:s1", status="dropped")
    render_all(c, root)
    assert not list((tmp_path / "arc" / "distilled").rglob("*.md"))

def test_does_not_delete_user_files(tmp_path):
    c = _conn(tmp_path); _conv(c, "claude:s1"); _dist(c, "claude:s1")
    root = tmp_path / "arc"; (root / "distilled" / "2026-06-14").mkdir(parents=True)
    user_md = root / "distilled" / "2026-06-14" / "我的手写.md"
    user_md.write_text("# 用户手写，无标记", encoding="utf-8")
    render_all(c, str(root))
    assert user_md.exists()
