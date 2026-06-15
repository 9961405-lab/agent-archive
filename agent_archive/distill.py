from __future__ import annotations
from agent_archive.redact import redact
from agent_archive.topics import TOPICS

PROMPT_VERSION = "distill-v1"
PROSE_MIN_CHARS = 200
MAX_PROMPT_CHARS = 12000
VALUE_MIN = 2
MAX_ATTEMPTS = 3

_SYS_OPENERS = ("You are running as", "The following is the Codex", "<local-command-caveat")


def _native_id(conv_id: str) -> str:
    return conv_id.split(":", 1)[-1]


def select_candidates(conn, model: str = "", prompt_version: str = PROMPT_VERSION,
                      exclude_projects: tuple = ()) -> list[dict]:
    rows = conn.execute("""
        SELECT c.*,
          SUM(CASE WHEN m.kind='prose' AND m.role='user' THEN 1 ELSE 0 END) up,
          SUM(CASE WHEN m.kind='prose' AND m.role='assistant' THEN 1 ELSE 0 END) ap,
          SUM(CASE WHEN m.kind='prose' THEN LENGTH(m.text) ELSE 0 END) pc
        FROM conversations c JOIN messages m ON m.conv_id=c.id
        GROUP BY c.id
    """).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        if not (d["up"] >= 1 and d["ap"] >= 1 and (d["pc"] or 0) >= PROSE_MIN_CHARS):
            continue
        if _native_id(d["id"]).startswith("agent-"):
            continue
        if d.get("project") in exclude_projects:
            continue
        prev = conn.execute("SELECT status,content_hash,model,prompt_version,attempt_count "
                            "FROM distillations WHERE conv_id=?", (d["id"],)).fetchone()
        if prev:
            same = (prev["content_hash"] == d["content_hash"]
                    and prev["model"] == model and prev["prompt_version"] == prompt_version)
            if prev["status"] in ("ok", "dropped") and same:
                continue
            if prev["status"] == "error" and prev["attempt_count"] >= MAX_ATTEMPTS:
                continue
        out.append(d)
    return out


def build_prompt(conn, conv_id: str):
    rows = conn.execute("SELECT role, text FROM messages "
                        "WHERE conv_id=? AND kind='prose' ORDER BY seq", (conv_id,)).fetchall()
    parts = []
    for i, r in enumerate(rows):
        txt = r["text"] or ""
        if i == 0 and any(txt.lstrip().startswith(p) for p in _SYS_OPENERS):
            continue
        parts.append(f'{r["role"]}: {txt}')
    body = "\n\n".join(parts)
    if len(body) > MAX_PROMPT_CHARS:
        half = MAX_PROMPT_CHARS // 2
        body = body[:half] + "\n…[中间省略]…\n" + body[-half:]
    body = redact(body)
    system = (
        "你是知识整理助手。阅读一段我与 AI 的对话，提炼成结构化 JSON。"
        "只输出 JSON，不要任何其他文字。字段：summary(一句话中文总结)、"
        "bullets(3-5 条要点)、decisions(关键决策，可空数组)、todos(待办，可空数组)、"
        "topics(从下列固定标签中选 1-3 个，不得自造)、value(0-5 价值分)、drop(是否无价值 true/false)。"
        f"可选 topics：{TOPICS}。所有文本用中文。"
    )
    return system, body
