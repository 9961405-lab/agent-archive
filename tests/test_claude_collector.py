import os
from agent_archive.collectors.claude import ClaudeCollector

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _ref(tmp_path):
    src = os.path.join(FIX, "claude_sample.jsonl")
    dst = tmp_path / "sess1.jsonl"
    dst.write_text(open(src, encoding="utf-8").read(), encoding="utf-8")
    c = ClaudeCollector(root=str(tmp_path))
    refs = list(c.discover())
    return c, refs

def test_discover_finds_session(tmp_path):
    c, refs = _ref(tmp_path)
    assert len(refs) == 1
    assert refs[0].source == "claude"
    assert refs[0].native_id == "sess1"

def test_parse_builds_conversation(tmp_path):
    c, refs = _ref(tmp_path)
    conv = c.parse(refs[0])
    assert conv.id == "claude:sess1"
    assert conv.project == "/Users/mac/Desktop/房间渲染"
    assert conv.title == "帮我写个脚本"
    assert conv.started_at == "2026-06-14T07:12:19.891Z"
    assert conv.updated_at == "2026-06-14T07:12:30.000Z"
    kinds = [(m.role, m.kind) for m in conv.messages]
    assert ("user", "prose") in kinds
    assert ("assistant", "thinking") in kinds
    assert ("assistant", "tool") in kinds
    assert any(m.kind == "sidechain" for m in conv.messages)

def test_queue_operation_is_ignored(tmp_path):
    c, refs = _ref(tmp_path)
    conv = c.parse(refs[0])
    assert all(m.role != "queue-operation" for m in conv.messages)
