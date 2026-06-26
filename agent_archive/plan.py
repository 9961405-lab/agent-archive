"""明日计划：从最近几天提炼出的「待办」里，让 LLM 挑出明天最该做的几件、排好优先级。

数据来自 distillations.todos（已脱敏的提炼结果），再脱敏一次后外发。生成结果写进
<root>/tomorrow.md，由 digest 在每日日报末尾附上「🎯 明天要做」一段。纯增量、不入库。
"""
from __future__ import annotations
import json
import datetime
from agent_archive.redact import redact

PLAN_DAYS = 7
MAX_TODOS = 40
MAX_ITEMS = 6

PLAN_SYSTEM = (
    "你是我的日程助手。下面是我最近几天积累的待办事项（来自我和 AI 的工作对话）。"
    "请挑出明天最该优先做的 3-6 件：合并重复、忽略明显已过时或太琐碎的，按优先级从高到低排。"
    "每条一句话、动词开头、具体可执行。只输出条目，每行一条，不要编号、不要标题、不要多余解释。"
)


def gather_todos(conn, days: int = PLAN_DAYS) -> list[str]:
    """取最近 days 天已提炼会话里的待办，去重保序。"""
    since = (datetime.date.today() - datetime.timedelta(days=days - 1)).isoformat()
    rows = conn.execute(
        "SELECT d.todos FROM distillations d JOIN conversations c ON c.id=d.conv_id "
        "WHERE d.status='ok' AND substr(COALESCE(c.started_at,''),1,10) >= ? "
        "ORDER BY c.started_at DESC", (since,)).fetchall()
    seen: set = set()
    out: list[str] = []
    for r in rows:
        for t in json.loads(r["todos"] or "[]"):
            t = (t or "").strip()
            if t and t not in seen:
                seen.add(t)
                out.append(t)
    return out[:MAX_TODOS]


def build_plan(conn, complete, model: str = "", days: int = PLAN_DAYS) -> list[str]:
    """汇集待办 → 一次 LLM 调用 → 明天该做的 3-6 件（按优先级）。无待办则返回空。"""
    todos = gather_todos(conn, days)
    if not todos:
        return []
    body = redact("\n".join(f"- {t}" for t in todos))
    raw = complete(PLAN_SYSTEM, body, model=model) or ""
    items = []
    for ln in raw.splitlines():
        s = ln.strip().lstrip("-·*0123456789.、) ").strip()
        if len(s) > 1:
            items.append(redact(s))
    return items[:MAX_ITEMS]


def render_plan_md(items: list[str]) -> str:
    """渲染成日报可附的一段；无内容返回空串。"""
    if not items:
        return ""
    lines = ["## 🎯 明天要做", ""]
    lines += [f"- [ ] {x}" for x in items]
    return "\n".join(lines) + "\n"
