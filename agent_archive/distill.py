from __future__ import annotations
import re
from agent_archive.redact import redact
from agent_archive.topics import TOPICS

PROMPT_VERSION = "distill-v1"
PROSE_MIN_CHARS = 200
MAX_PROMPT_CHARS = 12000
VALUE_MIN = 2
MAX_ATTEMPTS = 3

# 整条丢弃：这些 prose 消息整体是系统/工具注入，没有用户正文。
# 注意：harness 把它们注入到任意位置（实测 caveat 在 seq 54/1447），不止首条。
_SYS_OPENERS = ("You are running as", "The following is the Codex", "<local-command-caveat")

# 块内剥离：Codex/Claude 以 XML 块注入环境上下文/指令到用户消息里，可能与真实正文
# 混在同一条 prose（如 <environment_context> 含 cwd/shell/OS）。只剥这份白名单里的
# 已知注入标签，避免误删用户正文里正常出现的 <div>/<T> 等尖括号内容。
_INJECT_TAGS = ("environment_context", "user_instructions", "app_state",
                "INSTRUCTIONS", "local-command-caveat")
_INJECT_RE = re.compile(
    r"<(" + "|".join(_INJECT_TAGS) + r")\b[^>]*>.*?</\1>",
    re.DOTALL | re.IGNORECASE,
)


def _is_sys_message(text: str) -> bool:
    t = text.lstrip()
    return any(t.startswith(p) for p in _SYS_OPENERS)


def _strip_injections(text: str) -> str:
    """剥离嵌在用户消息里的已知注入块，保留其余正文。"""
    return _INJECT_RE.sub("", text)


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
    for r in rows:
        txt = r["text"] or ""
        if _is_sys_message(txt):
            continue
        txt = _strip_injections(txt).strip()
        if not txt:
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


import json
from agent_archive.llm import extract_json
from agent_archive.topics import normalize_topics
from agent_archive import store


def _coerce_int(v, default: int = 0) -> int:
    """把模型给的 value 安全转 int：'4'→4, '5/5'/'high'→default, 3.7→3。"""
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return default


def distill_one(conn, conv_id: str, complete, model: str = "") -> dict:
    """对单会话调模型并解析，输出回程脱敏，返回已 upsert 的记录 dict。"""
    system, user = build_prompt(conn, conv_id)
    ch = conn.execute("SELECT content_hash FROM conversations WHERE id=?", (conv_id,)).fetchone()[0]
    raw = complete(system, user, model=model)
    try:
        data = extract_json(raw)
    except ValueError:                            # 坏 JSON：用更强约束重试一次（设计要求）
        raw2 = complete(system + "\n严格只输出 JSON，不要任何其他文字、不要代码围栏。",
                        user, model=model)
        data = extract_json(raw2)                  # 再失败则抛 ValueError，由 run 记 error
    def _red_list(xs):
        # 模型可能把列表字段返回成字符串：按整体当一条，别按字符拆
        if isinstance(xs, str):
            xs = [xs] if xs.strip() else []
        elif not isinstance(xs, list):
            xs = []
        return [redact(str(x)) for x in xs]
    topics = normalize_topics(data.get("topics") or [])
    value = _coerce_int(data.get("value"))        # 模型可能返回 "high"/"5/5"/3.5 等
    dropped = bool(data.get("drop")) or value < VALUE_MIN
    rec = dict(
        conv_id=conv_id, content_hash=ch, model=model, prompt_version=PROMPT_VERSION,
        status="dropped" if dropped else "ok",
        summary=redact(str(data.get("summary") or "")),
        bullets=json.dumps(_red_list(data.get("bullets")), ensure_ascii=False),
        decisions=json.dumps(_red_list(data.get("decisions")), ensure_ascii=False),
        todos=json.dumps(_red_list(data.get("todos")), ensure_ascii=False),
        topics=json.dumps(topics, ensure_ascii=False),
        value=value, redacted=1, last_error=None)
    store.upsert_distillation(conn, rec)
    return rec


def run(conn, complete, *, model: str = "", limit=None, exclude_projects: tuple = ()) -> dict:
    cands = select_candidates(conn, model=model, exclude_projects=exclude_projects)
    if limit:
        cands = cands[:limit]
    res = {"ok": 0, "dropped": 0, "failed": 0, "skipped": 0}
    for cv in cands:
        try:
            rec = distill_one(conn, cv["id"], complete, model=model)
            res["ok" if rec["status"] == "ok" else "dropped"] += 1
        except Exception as e:                    # 每会话隔离：入库 error，可重试
            ch = cv["content_hash"]
            store.record_distill_error(conn, cv["id"], ch, model, PROMPT_VERSION, str(e)[:500])
            res["failed"] += 1
    return res
