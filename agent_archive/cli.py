from __future__ import annotations
import os, argparse, datetime, collections
from agent_archive import sync as sync_mod, store
from agent_archive.collectors import get_collectors


def _fmt_row(c: dict) -> str:
    tag = "🟦claude" if c["source"] == "claude" else "🟧codex "
    when = (c.get("started_at") or "")[11:16]  # HH:MM
    proj = os.path.basename((c.get("project") or "").rstrip("/")) or "-"
    return f"  {when:5} {tag}  {c['title'][:46]}   ({proj}, {c['message_count']}条)"


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

    pd = sub.add_parser("day")            # 某天做了什么（默认今天）
    pd.add_argument("date", nargs="?", default=None)
    pd.add_argument("--source", default=None)

    pr = sub.add_parser("recent")         # 最近 N 天概览
    pr.add_argument("days", nargs="?", type=int, default=7)
    pr.add_argument("--source", default=None)

    sub.add_parser("stats")

    args = p.parse_args(argv)
    root = _root(args)

    if args.cmd == "sync":
        cols = get_collectors(only=args.source)
        res = sync_mod.sync(root, collectors=cols, full=args.full)
        print(f"synced={res['synced']} skipped={res['skipped']} failed={res.get('failed', 0)}")
        return 0

    conn = store.connect(os.path.join(root, "index.sqlite"))
    store.init_db(conn)
    if args.cmd == "search":
        for h in store.search(conn, args.query, source=args.source, project=args.project):
            print(f"{h['conv_id']}  [{h['source']}]  {h['title']}\n    {h['md_ref']}")
        return 0
    if args.cmd == "day":
        day = args.date or datetime.date.today().isoformat()
        rows = store.list_conversations(conn, day=day, source=args.source)
        print(f"📅 {day}  （{len(rows)} 个会话）")
        for c in rows:
            print(_fmt_row(c))
        return 0
    if args.cmd == "recent":
        rows = store.list_conversations(conn, source=args.source)
        byday = collections.OrderedDict()
        for c in rows:
            d = (c.get("started_at") or "无日期")[:10]
            byday.setdefault(d, []).append(c)
        for d in list(byday)[:args.days]:
            print(f"\n📅 {d}  （{len(byday[d])} 个会话）")
            for c in byday[d]:
                print(_fmt_row(c))
        return 0
    if args.cmd == "stats":
        for src, s in store.stats(conn).items():
            print(f"{src}: {s['conversations']} 会话 / {s['messages']} 消息")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
