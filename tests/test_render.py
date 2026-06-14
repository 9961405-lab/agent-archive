from agent_archive.models import Message, Conversation
from agent_archive.render import render_markdown, MD_TRUNCATE_BYTES

def _conv(msgs):
    return Conversation("claude:s1","claude","写脚本","/p",
        "2026-06-14T07:12:19Z","2026-06-14T07:12:30Z", msgs, "raw/claude/s1.jsonl")

def test_frontmatter_and_body():
    md = render_markdown(_conv([Message("user","你好","2026-06-14T07:12:19Z")]))
    assert md.startswith("---\n")
    assert "id: claude:s1" in md
    assert "title: 写脚本" in md
    assert "raw_ref: raw/claude/s1.jsonl" in md
    assert "你好" in md

def test_thinking_collapsed_and_tool_oneline():
    md = render_markdown(_conv([
        Message("assistant","深思","t",kind="thinking"),
        Message("assistant",'{"command":"ls"}',"t",kind="tool",tool="Bash"),
    ]))
    assert "<details>" in md
    assert "🔧 Bash" in md

def test_large_tool_output_truncated():
    big = "x" * (MD_TRUNCATE_BYTES + 100)
    md = render_markdown(_conv([Message("tool",big,"t",kind="tool",tool="tool_result")]))
    assert "[截断" in md
    assert len(md) < MD_TRUNCATE_BYTES + 2000
