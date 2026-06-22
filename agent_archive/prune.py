"""清理僵尸记录：源文件已被删除/移走的会话，从库里连同消息/FTS/精炼一并移除，
并删掉对应的 raw 镜像、md 文件和失效 manifest 行。纯本地、只删自己产物。"""
from __future__ import annotations
import os
from agent_archive import store


def _live_ids(collectors) -> set[str]:
    """扫描各数据源当前还存在的会话 id（source:native_id）。"""
    live: set[str] = set()
    for col in collectors:
        for ref in col.discover():
            live.add(f"{col.source}:{ref.native_id}")
    return live


def prune(archive_root: str, collectors, dry_run: bool = False) -> dict:
    conn = store.connect(os.path.join(archive_root, "index.sqlite"))
    store.init_db(conn)
    live = _live_ids(collectors)
    dead = sorted(store.all_conversation_ids(conn) - live)

    if dry_run:
        return {"dead": len(dead), "ids": dead[:50], "manifest_removed": 0, "dry_run": True}

    files_removed = 0
    for cid in dead:
        raw_ref, md_ref = store.delete_conversation(conn, cid)
        for rel in (raw_ref, md_ref):
            if rel:
                path = os.path.join(archive_root, rel)
                if os.path.exists(path):
                    os.remove(path); files_removed += 1
    manifest_removed = store.delete_manifest_missing(conn)
    conn.commit()
    return {"dead": len(dead), "files_removed": files_removed,
            "manifest_removed": manifest_removed, "dry_run": False}
