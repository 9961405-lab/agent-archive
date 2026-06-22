import os
from agent_archive.collectors.claude import ClaudeCollector
from agent_archive import sync, prune, store

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _make_claude(tmp_path):
    proj = tmp_path / "src"; proj.mkdir()
    (proj / "sess1.jsonl").write_text(
        open(os.path.join(FIX, "claude_sample.jsonl"), encoding="utf-8").read(), encoding="utf-8")
    return proj, ClaudeCollector(root=str(proj))


def test_prune_removes_conversation_when_source_gone(tmp_path):
    root = str(tmp_path / "archive")
    proj, col = _make_claude(tmp_path)
    sync.sync(root, collectors=[col])
    conn = store.connect(os.path.join(root, "index.sqlite"))
    assert "claude:sess1" in store.all_conversation_ids(conn)
    raw = tmp_path / "archive" / "raw" / "claude" / "sess1.jsonl"
    assert raw.exists()

    # 源文件删除后 prune
    (proj / "sess1.jsonl").unlink()
    r = prune.prune(root, [col])
    assert r["dead"] == 1
    assert r["files_removed"] >= 1            # raw + md 被清理
    assert not raw.exists()

    conn2 = store.connect(os.path.join(root, "index.sqlite"))
    assert "claude:sess1" not in store.all_conversation_ids(conn2)
    assert store.search(conn2, "脚本") == []   # FTS 也清掉了


def test_prune_dry_run_keeps_data(tmp_path):
    root = str(tmp_path / "archive")
    proj, col = _make_claude(tmp_path)
    sync.sync(root, collectors=[col])
    (proj / "sess1.jsonl").unlink()
    r = prune.prune(root, [col], dry_run=True)
    assert r["dead"] == 1 and r["dry_run"] is True
    conn = store.connect(os.path.join(root, "index.sqlite"))
    assert "claude:sess1" in store.all_conversation_ids(conn)   # 没动


def test_prune_keeps_live_conversations(tmp_path):
    root = str(tmp_path / "archive")
    proj, col = _make_claude(tmp_path)
    sync.sync(root, collectors=[col])
    r = prune.prune(root, [col])                # 源文件还在
    assert r["dead"] == 0
    conn = store.connect(os.path.join(root, "index.sqlite"))
    assert "claude:sess1" in store.all_conversation_ids(conn)
