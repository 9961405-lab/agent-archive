from agent_archive.models import Message, Conversation, SessionRef

def _conv(msgs):
    return Conversation(
        id="claude:abc", source="claude", title="t", project="p",
        started_at="2026-06-14T00:00:00Z", updated_at="2026-06-14T00:01:00Z",
        messages=msgs, raw_ref="raw/claude/abc.jsonl",
    )

def test_content_hash_only_covers_prose_and_is_stable():
    prose = [Message(role="user", text="hello"), Message(role="assistant", text="hi")]
    h1 = _conv(prose).content_hash
    h2 = _conv(prose + [Message(role="tool", text="ls -la", kind="tool")]).content_hash
    assert h1 == h2
    assert len(h1) == 64

def test_content_hash_changes_when_prose_changes():
    a = _conv([Message(role="user", text="hello")]).content_hash
    b = _conv([Message(role="user", text="HELLO")]).content_hash
    assert a != b

def test_message_count():
    assert _conv([Message(role="user", text="x")]).message_count == 1
