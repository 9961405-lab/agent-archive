from __future__ import annotations
import datetime, json, collections

PERIOD_DAYS = {"day": 1, "week": 7, "month": 30}
PERIOD_LABEL = {"day": "每日", "week": "每周", "month": "每月"}


def _date_range(period: str, date: str | None) -> tuple[str, str]:
    end = datetime.date.fromisoformat(date) if date else datetime.date.today()
    start = end - datetime.timedelta(days=PERIOD_DAYS[period] - 1)
    return start.isoformat(), end.isoformat()


def build_digest(conn, period: str = "day", date: str | None = None) -> str:
    """从本地库聚合一段时间的总结 Markdown。纯本地只读，不调 LLM、不外发。"""
    start, end = _date_range(period, date)
    convs = conn.execute(
        "SELECT id, source, title, project FROM conversations "
        "WHERE substr(COALESCE(started_at,''),1,10) BETWEEN ? AND ? "
        "ORDER BY started_at", (start, end)).fetchall()
    span = end if start == end else f"{start} ~ {end}"
    head = f"# 📊 知识库{PERIOD_LABEL[period]}总结 · {span}"

    if not convs:
        return head + f"\n\n这段时间没有新的对话记录。"

    by_source = collections.Counter(r["source"] for r in convs)
    src_line = " / ".join(f"{s} {n}" for s, n in by_source.items())

    ids = [r["id"] for r in convs]
    ph = ",".join("?" * len(ids))
    dists = [dict(r) for r in conn.execute(
        f"SELECT d.*, c.started_at FROM distillations d JOIN conversations c ON c.id=d.conv_id "
        f"WHERE d.status='ok' AND d.conv_id IN ({ph})", ids).fetchall()]

    lines = [head, "", f"**{len(convs)} 个会话**（{src_line}）｜ **{len(dists)} 篇已提炼精华**", ""]

    # 主题分布
    topics = collections.Counter()
    for d in dists:
        for t in json.loads(d["topics"] or "[]"):
            topics[t] += 1
    if topics:
        lines.append("## 主题分布")
        lines.append("　".join(f"{t}×{n}" for t, n in topics.most_common()))
        lines.append("")

    # 重点（按价值分取高分会话的一句话总结；同分取较新的，避免排序无意义）
    top = sorted([d for d in dists if d.get("summary")],
                 key=lambda d: (d.get("value") or 0, d.get("started_at") or ""),
                 reverse=True)[:8]
    if top:
        lines.append("## 重点")
        for d in top:
            lines.append(f"- {d['summary']}")
        lines.append("")

    # 决策与待办（跨会话聚合）
    decisions, todos = [], []
    for d in dists:
        decisions += json.loads(d["decisions"] or "[]")
        todos += json.loads(d["todos"] or "[]")
    if decisions:
        lines.append("## 关键决策")
        for x in decisions[:10]:
            lines.append(f"- {x}")
        lines.append("")
    if todos:
        lines.append("## 待办")
        for x in todos[:10]:
            lines.append(f"- [ ] {x}")
        lines.append("")

    # 若这段时间还没提炼过，至少列出会话标题
    if not dists:
        lines.append("## 会话列表（尚未提炼）")
        for r in convs[:30]:
            proj = (r["project"] or "").split("/")[-1] or "-"
            lines.append(f"- [{r['source']}] {r['title']}（{proj}）")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"
