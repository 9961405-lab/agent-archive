import json, datetime
from agent_archive import store, plan


def _conn(tmp_path):
    c = store.connect(str(tmp_path / "a.sqlite")); store.init_db(c); return c


def _conv(conn, cid, started):
    conn.execute("INSERT INTO conversations "
        "(id,source,title,project,started_at,updated_at,message_count,content_hash,raw_ref,md_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (cid, "claude", "标题", "/p", started, started, 3, "h", "r", "m"))


def _dist(conn, cid, todos):
    store.upsert_distillation(conn, dict(conv_id=cid, content_hash="h", model="m",
        prompt_version="distill-v1", status="ok", summary="s", bullets='[]',
        decisions='[]', todos=json.dumps(todos, ensure_ascii=False),
        topics='["工具脚本"]', value=4, redacted=1, last_error=None))


def test_gather_todos_recent_dedup(tmp_path):
    c = _conn(tmp_path)
    today = datetime.date.today().isoformat()
    old = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
    _conv(c, "claude:a", today + "T01:00:00Z"); _dist(c, "claude:a", ["清理上传图片", "写 README"])
    _conv(c, "claude:b", today + "T02:00:00Z"); _dist(c, "claude:b", ["清理上传图片", "部署上线"])
    _conv(c, "claude:old", old + "T01:00:00Z"); _dist(c, "claude:old", ["太久远的事"])
    c.commit()
    todos = plan.gather_todos(c, days=7)
    assert "清理上传图片" in todos and todos.count("清理上传图片") == 1   # 去重
    assert "写 README" in todos and "部署上线" in todos
    assert "太久远的事" not in todos                                    # 超窗口


def test_build_plan_parses_llm_lines(tmp_path):
    c = _conn(tmp_path)
    today = datetime.date.today().isoformat()
    _conv(c, "claude:a", today + "T01:00:00Z"); _dist(c, "claude:a", ["写 README", "部署上线"])
    c.commit()
    captured = {}
    def fake_complete(system, user, **kw):
        captured["user"] = user
        return "1. 先部署上线\n- 补 README\n\n* 收尾测试"
    items = plan.build_plan(c, fake_complete, days=7)
    assert items == ["先部署上线", "补 README", "收尾测试"]            # 去编号/符号
    assert "写 README" in captured["user"]                            # 待办确实喂进去了


def test_build_plan_empty_when_no_todos(tmp_path):
    c = _conn(tmp_path)
    called = []
    items = plan.build_plan(c, lambda *a, **k: called.append(1) or "x", days=7)
    assert items == [] and not called                                 # 无待办不调 LLM


def test_render_plan_md(tmp_path):
    assert plan.render_plan_md([]) == ""
    md = plan.render_plan_md(["先部署上线", "补 README"])
    assert "## 🎯 明天要做" in md
    assert "- [ ] 先部署上线" in md and "- [ ] 补 README" in md
