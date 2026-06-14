from __future__ import annotations
import os, re, datetime
from agent_archive import store, mirror as mirror_mod, render as render_mod


def _slug(s: str) -> str:
    s = re.sub(r"[\\/:*?\"<>|\n\r\t]+", "_", s).strip("_ ")
    return (s or "untitled")[:40]


def _md_path(root: str, conv) -> str:
    day = (conv.started_at or "")[:10] or "0000-00-00"
    short = conv.id.split(":")[-1][:8]
    name = f"{conv.source}__{_slug(conv.title)}__{short}.md"
    return os.path.join(root, "md", day, name)


def sync(archive_root: str, collectors, full: bool = False) -> dict:
    os.makedirs(archive_root, exist_ok=True)
    conn = store.connect(os.path.join(archive_root, "index.sqlite"))
    store.init_db(conn)
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    synced = skipped = 0
    for col in collectors:
        prefer_hl = col.source in ("claude", "codex")
        for ref in col.discover():
            prev = store.manifest_get(conn, ref.source, ref.path)
            if not full and prev and prev["mtime"] == ref.mtime and prev["size"] == ref.size:
                skipped += 1
                continue
            conv = col.parse(ref)
            conv.raw_ref = mirror_mod.mirror(ref, archive_root, prefer_hardlink=prefer_hl)
            md_path = _md_path(archive_root, conv)
            os.makedirs(os.path.dirname(md_path), exist_ok=True)
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(render_mod.render_markdown(conv))
            md_ref = os.path.relpath(md_path, archive_root)
            store.upsert_conversation(conn, conv, md_ref=md_ref)
            store.manifest_set(conn, ref.source, ref.path, ref.mtime, ref.size,
                               conv.content_hash, now)
            synced += 1
    return {"synced": synced, "skipped": skipped}
