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

class _NoneThenCleanupCollector:
    """首轮把会话入库，次轮 parse 返回 None（模拟 collector 改判为非对话）。"""
    source = "codex"
    def __init__(self, path, return_none):
        self._path = path; self._none = return_none
    def discover(self):
        st = os.stat(self._path)
        yield SessionRef("codex", "approval-x", self._path, st.st_mtime, st.st_size)
    def parse(self, ref):
        if self._none:
            return None
        return Conversation("codex:approval-x", "codex", "会话", "/p",
            "2026-06-14T01:00:00Z", "2026-06-14T01:00:00Z",
            [Message("user", "正文内容够长够长够长", "t")], "")

def test_sync_none_conv_cleans_existing(tmp_path):
    f = tmp_path / "s.jsonl"; f.write_text("{}", encoding="utf-8")
    root = tmp_path / "archive"
    # 首轮入库
    assert sync.sync(str(root), collectors=[_NoneThenCleanupCollector(str(f), False)])["synced"] == 1
    conn = store.connect(str(root / "index.sqlite"))
    assert "codex:approval-x" in store.all_conversation_ids(conn)
    # 次轮 parse→None：应清除会话并计为 skipped（强制 full 以重新解析）
    res = sync.sync(str(root), collectors=[_NoneThenCleanupCollector(str(f), True)], full=True)
    assert res["skipped"] == 1 and res["synced"] == 0
    conn2 = store.connect(str(root / "index.sqlite"))
    assert "codex:approval-x" not in store.all_conversation_ids(conn2)


def test_md_path_uses_mtime_when_no_started_at(tmp_path):
    path = sync._md_path("/root",
        Conversation("claude:x", "claude", "t", None, None, None, [], ""),
        fallback_day="2025-01-02")
    assert "/md/2025-01-02/" in path

def test_md_path_no_collision_for_shared_prefix_ids(tmp_path):
    # 子代理会话共享 "agent-" 前缀且都无标题，完整 native_id 必须保证唯一
    def cv(nid):
        return Conversation(f"claude:{nid}", "claude", "(无标题)",
            None, "2026-06-14T00:00:00Z", None, [], "")
    p1 = sync._md_path("/root", cv("agent-ac3c8b73-1111"), "x")
    p2 = sync._md_path("/root", cv("agent-af127cd7-2222"), "x")
    assert p1 != p2
    assert "agent-ac3c8b73-1111" in p1 and "agent-af127cd7-2222" in p2
