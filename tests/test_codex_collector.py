import os
from agent_archive.collectors.codex import CodexCollector

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _setup(tmp_path):
    sub = tmp_path / "2026" / "05" / "08"
    sub.mkdir(parents=True)
    name = "rollout-2026-05-08T05-24-12-019e060b-1e4c-79a3-b534-9e4cc5dc2450.jsonl"
    (sub / name).write_text(
        open(os.path.join(FIX, "codex_sample.jsonl"), encoding="utf-8").read(), encoding="utf-8")
    idx = tmp_path / "session_index.jsonl"
    idx.write_text(open(os.path.join(FIX, "codex_session_index.jsonl"), encoding="utf-8").read(),
                   encoding="utf-8")
    c = CodexCollector(root=str(tmp_path), index_path=str(idx))
    return c, list(c.discover())

def test_discover(tmp_path):
    c, refs = _setup(tmp_path)
    assert len(refs) == 1
    assert refs[0].native_id == "019e060b-1e4c-79a3-b534-9e4cc5dc2450"

def test_title_from_index(tmp_path):
    c, refs = _setup(tmp_path)
    assert c.parse(refs[0]).title == "快团团订单核对"

def test_prose_authoritative_and_no_compacted_dup(tmp_path):
    c, refs = _setup(tmp_path)
    conv = c.parse(refs[0])
    prose = [m for m in conv.messages if m.kind == "prose"]
    assert [(m.role, m.text) for m in prose] == [
        ("user", "帮我核对快团团订单"), ("assistant", "我先看下项目结构")]

def test_developer_noise_and_encrypted_reasoning_excluded(tmp_path):
    c, refs = _setup(tmp_path)
    conv = c.parse(refs[0])
    assert all("permissions instructions" not in m.text for m in conv.messages)
    assert all(m.kind != "thinking" for m in conv.messages)

def test_function_call_becomes_tool(tmp_path):
    c, refs = _setup(tmp_path)
    conv = c.parse(refs[0])
    assert any(m.kind == "tool" and m.tool == "exec_command" for m in conv.messages)

def test_project_from_meta(tmp_path):
    c, refs = _setup(tmp_path)
    assert c.parse(refs[0]).project == "/home/dev/demo-project"
