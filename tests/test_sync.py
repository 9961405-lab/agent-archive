import os, datetime
from agent_archive.collectors.claude import ClaudeCollector
from agent_archive import sync, store

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _make_claude(tmp_path):
    proj = tmp_path / "src"; proj.mkdir()
    (proj / "sess1.jsonl").write_text(
        open(os.path.join(FIX, "claude_sample.jsonl"), encoding="utf-8").read(), encoding="utf-8")
    return ClaudeCollector(root=str(proj))

def test_sync_writes_three_layers(tmp_path):
    root = tmp_path / "archive"
    col = _make_claude(tmp_path)
    res = sync.sync(str(root), collectors=[col])
    assert res["synced"] == 1
    assert (root / "raw" / "claude" / "sess1.jsonl").exists()
    mds = list((root / "md").rglob("*.md"))
    assert len(mds) == 1 and "2026-06-14" in str(mds[0])
    conn = store.connect(str(root / "index.sqlite"))
    assert store.search(conn, "脚本")

def test_sync_incremental_skips_unchanged(tmp_path):
    root = tmp_path / "archive"
    col = _make_claude(tmp_path)
    assert sync.sync(str(root), collectors=[col])["synced"] == 1
    r2 = sync.sync(str(root), collectors=[col])
    assert r2["synced"] == 0 and r2["skipped"] == 1

def test_sync_full_reprocesses(tmp_path):
    root = tmp_path / "archive"
    col = _make_claude(tmp_path)
    sync.sync(str(root), collectors=[col])
    assert sync.sync(str(root), collectors=[col], full=True)["synced"] == 1
