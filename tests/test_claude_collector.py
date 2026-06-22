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
    assert conv.project == "/home/dev/demo-project"
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

def test_title_falls_back_to_assistant_when_no_user_prose(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"我来帮你"}]},"timestamp":"2026-06-14T07:00:00Z","sessionId":"s"}\n',
        encoding="utf-8")
    c = ClaudeCollector(root=str(tmp_path))
    conv = c.parse(next(iter(c.discover())))
    assert conv.title == "我来帮你"

def test_blank_first_user_does_not_crash(tmp_path):
    p = tmp_path / "s.jsonl"
    p.write_text(
        '{"type":"user","message":{"role":"user","content":"   "},"timestamp":"2026-06-14T07:00:00Z","sessionId":"s"}\n'
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"回答"}]},"timestamp":"2026-06-14T07:00:01Z","sessionId":"s"}\n',
        encoding="utf-8")
    c = ClaudeCollector(root=str(tmp_path))
    conv = c.parse(next(iter(c.discover())))  # 必须不抛
    assert conv.title == "回答"
