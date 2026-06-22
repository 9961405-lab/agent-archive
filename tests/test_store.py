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


def test_connect_creates_missing_parent_dir(tmp_path):
    # 数据根目录还不存在时（朋友先跑 stats/search，未 sync），connect 应自动建目录
    db = tmp_path / "nope" / "deeper" / "index.sqlite"
    conn = store.connect(str(db)); store.init_db(conn)
    assert db.parent.is_dir()
    assert store.list_conversations(conn) == []


def test_segment_covers_cjk_kana_hangul_fullwidth():
    from agent_archive.store import _segment
    for ch in ("中", "あ", "한", "！"):
        assert f" {ch} " in _segment(f"x{ch}y")   # 逐字加空格 → 可子串检索


def test_search_preview_returns_snippet(tmp_path):
    conn = store.connect(str(tmp_path / "a.sqlite")); store.init_db(conn)
    store.upsert_conversation(conn, _conv(prose="帮我核对快团团订单金额对不上"),
                              md_ref="md/x.md")
    hits = store.search(conn, "订单", preview=True)
    assert len(hits) == 1
    assert "preview" in hits[0]
    pv = hits[0]["preview"]
    assert "[订]" in pv                        # 命中字被 [ ] 高亮（逐字分词）
    assert "核对快团团" in pv                  # 上下文可读，分词空格已收回
    assert "  " not in pv                      # 无连续空格
    # 非 preview 不带该字段
    assert "preview" not in store.search(conn, "订单")[0]
