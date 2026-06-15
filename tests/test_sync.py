import os, datetime
from agent_archive.collectors.claude import ClaudeCollector
from agent_archive.models import SessionRef, Conversation, Message
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


class _FlakyCollector:
    source = "claude"
    def __init__(self, good_path, bad_path):
        self._g = good_path; self._b = bad_path
    def discover(self):
        for pth in (self._b, self._g):
            st = os.stat(pth)
            yield SessionRef("claude", os.path.basename(pth), pth, st.st_mtime, st.st_size)
    def parse(self, ref):
        if ref.path == self._b:
            raise ValueError("boom")
        return Conversation("claude:good", "claude", "好会话", "/p",
            "2026-06-14T01:00:00Z", "2026-06-14T01:00:00Z",
            [Message("user", "正文内容", "t")], "")

def test_sync_isolates_bad_file(tmp_path):
    good = tmp_path / "good.jsonl"; good.write_text("{}", encoding="utf-8")
    bad = tmp_path / "bad.jsonl"; bad.write_text("{}", encoding="utf-8")
    root = tmp_path / "archive"
    res = sync.sync(str(root), collectors=[_FlakyCollector(str(good), str(bad))])
    assert res["synced"] == 1
    assert res["failed"] == 1
    conn = store.connect(str(root / "index.sqlite"))
    assert store.manifest_get(conn, "claude", str(bad)) is None      # 坏文件不入 manifest，下次重试
    assert store.manifest_get(conn, "claude", str(good)) is not None

def test_md_path_uses_mtime_when_no_started_at(tmp_path):
    path = sync._md_path("/root",
        Conversation("claude:x", "claude", "t", None, None, None, [], ""),
        fallback_day="2025-01-02")
    assert "/md/2025-01-02/" in path
