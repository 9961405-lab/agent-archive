import os
from agent_archive.collectors.workbuddy import WorkBuddyCollector

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _ref(tmp_path):
    proj = tmp_path / "Users-mac-demo"; proj.mkdir()
    (proj / "sess-wb.jsonl").write_text(
        open(os.path.join(FIX, "workbuddy_sample.jsonl"), encoding="utf-8").read(),
        encoding="utf-8")
    c = WorkBuddyCollector(root=str(tmp_path))
    return c, list(c.discover())


def test_discover(tmp_path):
    c, refs = _ref(tmp_path)
    assert len(refs) == 1
    assert refs[0].source == "workbuddy"
    assert refs[0].native_id == "sess-wb"


def test_parse_builds_conversation(tmp_path):
    c, refs = _ref(tmp_path)
    conv = c.parse(refs[0])
    assert conv.id == "workbuddy:sess-wb"
    assert conv.source == "workbuddy"
    assert conv.title == "触发今日自动化任务"          # ai-title 优先
    assert conv.project == "/home/dev/demo-project"
    # epoch 毫秒 → ISO8601 UTC
    assert conv.started_at and conv.started_at.startswith("2026-")

    kinds = [(m.role, m.kind) for m in conv.messages]
    assert ("user", "prose") in kinds
    assert ("assistant", "prose") in kinds
    assert ("assistant", "thinking") in kinds         # reasoning
    assert ("assistant", "tool") in kinds             # function_call
    assert ("tool", "tool") in kinds                  # function_call_result

    prose = [m.text for m in conv.messages if m.kind == "prose"]
    assert "帮我触发闲鱼每日推送" in prose
    assert "已触发，闲鱼推送任务开始执行" in prose
    # system-reminder 注入被过滤
    assert not any("system-reminder" in t for t in prose)


def test_content_hash_only_prose(tmp_path):
    c, refs = _ref(tmp_path)
    conv = c.parse(refs[0])
    assert conv.content_hash                            # 可计算，不抛错
