from __future__ import annotations
import os, argparse
from agent_archive import sync as sync_mod, store
from agent_archive.collectors import get_collectors


def _root(args) -> str:
    return os.path.expanduser(
        args.root or os.environ.get("AGENT_ARCHIVE_ROOT", "~/agent-archive"))


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="agent-archive")
    p.add_argument("--root", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    ps = sub.add_parser("sync")
    ps.add_argument("--source", default=None)
    ps.add_argument("--full", action="store_true")

    pq = sub.add_parser("search")
    pq.add_argument("query")
    pq.add_argument("--source", default=None)
    pq.add_argument("--project", default=None)

    sub.add_parser("stats")

    args = p.parse_args(argv)
    root = _root(args)

    if args.cmd == "sync":
        cols = get_collectors(only=args.source)
        res = sync_mod.sync(root, collectors=cols, full=args.full)
        print(f"synced={res['synced']} skipped={res['skipped']}")
        return 0

    conn = store.connect(os.path.join(root, "index.sqlite"))
    store.init_db(conn)
    if args.cmd == "search":
        for h in store.search(conn, args.query, source=args.source, project=args.project):
            print(f"{h['conv_id']}  [{h['source']}]  {h['title']}\n    {h['md_ref']}")
        return 0
    if args.cmd == "stats":
        for src, s in store.stats(conn).items():
            print(f"{src}: {s['conversations']} 会话 / {s['messages']} 消息")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
