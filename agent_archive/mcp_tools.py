"""知识库 MCP 工具的纯逻辑层：每个函数接收一个 sqlite 连接，返回 JSON 可序列化结果。
只读、纯本地。与 MCP 传输解耦，便于单测（不依赖 mcp 包）。"""
from __future__ import annotations
import json
from agent_archive import store, digest as digest_mod

GET_CONV_MAX_CHARS = 20000   # get_conversation 正文总上限，避免把超大会话灌爆上下文


def search(conn, query: str, source: str | None = None,
           project: str | None = None, limit: int = 20) -> list[dict]:
    """全文检索对话，返回命中会话的元信息。"""
    rows = store.search(conn, query, source=source, project=project)
    return rows[:limit]


def get_conversation(conn, conv_id: str) -> dict:
    """取一条对话：元信息 + prose 正文（截断到上限）。"""
    c = conn.execute(
        "SELECT id, source, title, project, started_at, updated_at, message_count "
        "FROM conversations WHERE id=?", (conv_id,)).fetchone()
    if not c:
        return {"error": f"not found: {conv_id}"}
    conv = dict(c)
    msgs, total = [], 0
    for r in conn.execute("SELECT role, text FROM messages "
                          "WHERE conv_id=? AND kind='prose' ORDER BY seq", (conv_id,)):
        t = r["text"] or ""
        if total + len(t) > GET_CONV_MAX_CHARS:
            msgs.append({"role": "system", "text": "…[后续内容已截断，完整见原始档案]"})
            break
        msgs.append({"role": r["role"], "text": t})
        total += len(t)
    conv["messages"] = msgs
    return conv


def recent(conn, days: int = 7, source: str | None = None) -> list[dict]:
    """最近活动列表（按起始时间倒序）。"""
    rows = store.list_conversations(conn, source=source)
    return rows[: days * 60]  # 粗上限，避免超大返回；按需可加日期过滤


def day(conn, date: str | None = None, source: str | None = None) -> list[dict]:
    """某天的会话列表（默认今天）。"""
    import datetime
    d = date or datetime.date.today().isoformat()
    return store.list_conversations(conn, day=d, source=source)


def digest(conn, period: str = "day", date: str | None = None) -> str:
    """生成日/周/月总结 Markdown。"""
    return digest_mod.build_digest(conn, period=period, date=date)


def list_topics(conn) -> list[dict]:
    """列出各主题及其精华卡数量（按数量倒序）。"""
    import collections
    cnt = collections.Counter()
    for (t,) in conn.execute("SELECT topics FROM distillations WHERE status='ok'"):
        for x in json.loads(t or "[]"):
            cnt[x] += 1
    return [{"topic": k, "count": v} for k, v in cnt.most_common()]


def by_topic(conn, topic: str) -> list[dict]:
    """取某主题下的精华卡（总结/价值/时间/会话 id）。"""
    out = []
    for r in store.distillations_by_topic(conn, topic):
        out.append({"conv_id": r["conv_id"], "title": r.get("title"),
                    "summary": r.get("summary"), "value": r.get("value"),
                    "started_at": r.get("started_at"), "md_ref": r.get("md_ref")})
    return out
