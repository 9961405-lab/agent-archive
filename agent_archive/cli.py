from __future__ import annotations
import os, argparse, datetime, collections
from agent_archive import sync as sync_mod, store
from agent_archive.collectors import get_collectors
from agent_archive import distill as distill_mod, render_distill, llm as llm_mod
from agent_archive import digest as digest_mod


_SOURCE_TAGS = {"claude": "🟦claude", "codex": "🟧codex ", "hermes": "🟩hermes"}


def _fmt_row(c: dict) -> str:
    tag = _SOURCE_TAGS.get(c["source"], f"  {c['source']:6.6}")  # 未知源不再误标成 codex
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

    pds = sub.add_parser("distill")
    pds.add_argument("--limit", type=int, default=None)
    pds.add_argument("--exclude-project", action="append", default=[])
    pds.add_argument("--dry-run", action="store_true")
    pds.add_argument("--yes", action="store_true")

    sub.add_parser("topics")
    sub.add_parser("distill-stats")

    pg = sub.add_parser("digest")          # 周期总结（本地聚合，输出 Markdown）
    pg.add_argument("--period", choices=["day", "week", "month"], default="day")
    pg.add_argument("--date", default=None)

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
    if args.cmd == "distill":
        cands = distill_mod.select_candidates(
            conn, model=os.environ.get("AGENT_ARCHIVE_LLM_MODEL", ""),
            exclude_projects=tuple(args.exclude_project))
        if args.limit:
            cands = cands[:args.limit]
        if args.dry_run:
            print(f"[dry-run] 将外发 {len(cands)} 个会话至 "
                  f"{os.environ.get('AGENT_ARCHIVE_LLM_BASE_URL','(未配置)')}")
            for cv in cands:
                print(f"  {cv['id']}  {cv['title'][:40]}")
            if cands:
                _, sample = distill_mod.build_prompt(conn, cands[0]["id"])
                print("\n--- 脱敏后 prompt 样例（首个会话，截断）---\n" + sample[:600])
            return 0
        base = os.environ.get("AGENT_ARCHIVE_LLM_BASE_URL")
        key = os.environ.get("AGENT_ARCHIVE_LLM_API_KEY")
        model = os.environ.get("AGENT_ARCHIVE_LLM_MODEL")
        if not (base and key and model):
            print("缺配置：请设 AGENT_ARCHIVE_LLM_BASE_URL / _API_KEY / _MODEL")
            return 2
        if not args.yes:
            print(f"将把 {len(cands)} 个会话外发至 {base}（model={model}）。加 --yes 确认执行。")
            return 0
        def complete(system, user, **kw):
            return llm_mod.complete(system, user, base_url=base, api_key=key, model=model)
        res = distill_mod.run(conn, complete, model=model, limit=args.limit,
                              exclude_projects=tuple(args.exclude_project))
        render_distill.render_all(conn, root)
        print(f"ok={res['ok']} dropped={res['dropped']} failed={res['failed']}")
        return 0
    if args.cmd == "topics":
        render_distill.render_all(conn, root)
        print("主题页已重建")
        return 0
    if args.cmd == "distill-stats":
        for status, n in store.distill_stats(conn).items():
            print(f"{status}: {n}")
        return 0
    if args.cmd == "digest":
        print(digest_mod.build_digest(conn, period=args.period, date=args.date))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
