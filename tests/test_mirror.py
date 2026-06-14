import os
from agent_archive.models import SessionRef
from agent_archive.mirror import mirror

def test_hardlink_same_fs(tmp_path):
    src = tmp_path / "src.jsonl"; src.write_text("hello", encoding="utf-8")
    st = src.stat()
    ref = SessionRef("claude", "sess1", str(src), st.st_mtime, st.st_size)
    root = tmp_path / "archive"
    raw_ref = mirror(ref, str(root), prefer_hardlink=True)
    dest = root / raw_ref
    assert dest.exists()
    assert dest.read_text(encoding="utf-8") == "hello"
    assert os.stat(src).st_ino == os.stat(dest).st_ino
    os.remove(src)
    assert dest.read_text(encoding="utf-8") == "hello"

def test_copy_fallback(tmp_path):
    src = tmp_path / "src.db"; src.write_text("data", encoding="utf-8")
    st = src.stat()
    ref = SessionRef("cursor", "x", str(src), st.st_mtime, st.st_size)
    root = tmp_path / "archive"
    raw_ref = mirror(ref, str(root), prefer_hardlink=False)
    dest = root / raw_ref
    assert dest.exists()
    assert os.stat(src).st_ino != os.stat(dest).st_ino
