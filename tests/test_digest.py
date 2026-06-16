import json
from agent_archive import store
from agent_archive.digest import build_digest, _date_range


def _conn(tmp_path):
    c = store.connect(str(tmp_path / "a.sqlite")); store.init_db(c); return c


def _conv(conn, cid, started):
    conn.execute("INSERT INTO conversations "
        "(id,source,title,project,started_at,updated_at,message_count,content_hash,raw_ref,md_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cid, cid.split(':')[0], "标题", "/p/proj", started, started, 5, "h", "r", "m"))
    conn.commit()


def _dist(conn, cid, summary="一句话", topics='["电商运营"]', value=4,
          decisions='[]', todos='[]'):
    store.upsert_distillation(conn, dict(conv_id=cid, content_hash="h", model="m",
        prompt_version="distill-v1", status="ok", summary=summary, bullets='["b"]',
        decisions=decisions, todos=todos, topics=topics, value=value, redacted=1, last_error=None))


def test_date_range_periods():
    assert _date_range("day", "2026-06-15") == ("2026-06-15", "2026-06-15")
    assert _date_range("week", "2026-06-15") == ("2026-06-09", "2026-06-15")
    assert _date_range("month", "2026-06-30") == ("2026-06-01", "2026-06-30")


def test_empty_period():
    import tempfile, pathlib
    d = pathlib.Path(tempfile.mkdtemp())
    c = _conn(d)
    md = build_digest(c, "day", "2026-06-15")
    assert "没有新的对话" in md


def test_digest_aggregates_distillations(tmp_path):
    c = _conn(tmp_path)
    _conv(c, "claude:a", "2026-06-15T01:00:00Z")
    _conv(c, "codex:b", "2026-06-15T02:00:00Z")
    _dist(c, "claude:a", summary="搞定了订单核对", topics='["电商运营","工具脚本"]', value=5,
          decisions='["用原子递增防并发"]', todos='["清理上传图片"]')
    _dist(c, "codex:b", summary="部署到腾讯云", topics='["部署运维"]', value=4)
    md = build_digest(c, "day", "2026-06-15")
    assert "2 个会话" in md and "1 篇" not in md.split("个会话")[0]
    assert "2 篇已提炼精华" in md
    assert "电商运营" in md and "部署运维" in md      # 主题分布
    assert "搞定了订单核对" in md                      # 重点（高分在前）
    assert "用原子递增防并发" in md                    # 决策
    assert "清理上传图片" in md                        # 待办


def test_digest_window_excludes_outside(tmp_path):
    c = _conn(tmp_path)
    _conv(c, "claude:in", "2026-06-15T01:00:00Z")
    _conv(c, "claude:out", "2026-06-01T01:00:00Z")   # 窗口外
    _dist(c, "claude:in"); _dist(c, "claude:out")
    md = build_digest(c, "day", "2026-06-15")
    assert "1 个会话" in md


def test_digest_lists_titles_when_no_distillations(tmp_path):
    c = _conn(tmp_path)
    _conv(c, "claude:x", "2026-06-15T01:00:00Z")     # 有会话但没提炼
    md = build_digest(c, "day", "2026-06-15")
    assert "尚未提炼" in md and "标题" in md
