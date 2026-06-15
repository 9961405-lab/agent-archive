from agent_archive.models import Message, Conversation
from agent_archive import store


def _conv(cid="claude:s1", prose="你好世界"):
    return Conversation(cid, cid.split(":", 1)[0], "标题", "/p",
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
    assert store.search(conn, "可搜索正文")
    assert store.search(conn, "xxxxxxxxxx") == []


def test_upsert_is_idempotent(tmp_path):
    db = tmp_path / "a.sqlite"
    conn = store.connect(str(db)); store.init_db(conn)
    for _ in range(3):
        store.upsert_conversation(conn, _conv(), md_ref="m")
    assert len(store.search(conn, "你好世界")) == 1


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


def test_search_empty_query_returns_empty(tmp_path):
    db = tmp_path / "a.sqlite"
    conn = store.connect(str(db)); store.init_db(conn)
    store.upsert_conversation(conn, _conv(), md_ref="m")
    assert store.search(conn, "") == []
    assert store.search(conn, "   ") == []


def test_search_with_quote_does_not_crash(tmp_path):
    db = tmp_path / "a.sqlite"
    conn = store.connect(str(db)); store.init_db(conn)
    store.upsert_conversation(conn, _conv(prose='他说"你好世界"了'), md_ref="m")
    assert isinstance(store.search(conn, '"'), list)  # 必须不抛
    assert len(store.search(conn, "你好世界")) == 1
