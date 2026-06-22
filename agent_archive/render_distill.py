from __future__ import annotations
import os, re, json, glob
from agent_archive import store
from agent_archive.topics import TOPICS

GENERATED_MARK = "generated_by: agent-archive-distill"


def _slug(s: str) -> str:
    return (re.sub(r"[\\/:*?\"<>|\n\r\t ]+", "_", s).strip("_") or "untitled")[:40]


def _is_ours(path: str) -> bool:
    try:
        with open(path, encoding="utf-8") as f:
            return GENERATED_MARK in f.read(400)
    except OSError:
        return False


def _clear_owned(dir_path: str):
    for p in glob.glob(os.path.join(dir_path, "**", "*.md"), recursive=True):
        if _is_ours(p):
            os.remove(p)


def _card_md(d: dict) -> str:
    bullets = "\n".join(f"- {b}" for b in json.loads(d["bullets"] or "[]"))
    decisions = "\n".join(f"- {x}" for x in json.loads(d["decisions"] or "[]"))
    todos = "\n".join(f"- [ ] {x}" for x in json.loads(d["todos"] or "[]"))
    topics = json.loads(d["topics"] or "[]")
    fm = ["---", GENERATED_MARK, f"conv_id: {d['conv_id']}", f"source: {d['source']}",
          f"topics: {topics}", f"value: {d['value']}", f"redacted: {bool(d['redacted'])}",
          f"raw_ref: {d['raw_ref']}", f"md_ref: {d['md_ref']}", "---", ""]
    body = [f"# {d['title']}", "", f"> {d['summary']}", ""]
    if bullets: body += ["## 要点", bullets, ""]
    if decisions: body += ["## 决策", decisions, ""]
    if todos: body += ["## 待办", todos, ""]
    return "\n".join(fm + body)


def render_all(conn, archive_root: str) -> dict:
    distilled = os.path.join(archive_root, "distilled")
    topics_dir = os.path.join(archive_root, "topics")
    os.makedirs(distilled, exist_ok=True); os.makedirs(topics_dir, exist_ok=True)
    _clear_owned(distilled); _clear_owned(topics_dir)

    rows = conn.execute(
        "SELECT d.*, c.title, c.source, c.started_at, c.raw_ref, c.md_ref "
        "FROM distillations d JOIN conversations c ON c.id=d.conv_id "
        "WHERE d.status='ok'").fetchall()
    n = 0
    for r in rows:
        d = dict(r)
        day = (d["started_at"] or "")[:10] or "0000-00-00"
        sub = os.path.join(distilled, day); os.makedirs(sub, exist_ok=True)
        name = f"{d['source']}__{_slug(d['title'])}__{d['conv_id'].split(':',1)[-1]}.md"
        with open(os.path.join(sub, name), "w", encoding="utf-8") as f:
            f.write(_card_md(d))
        n += 1

    for topic in TOPICS:
        items = store.distillations_by_topic(conn, topic)
        if not items:
            continue
        lines = ["---", GENERATED_MARK, f"topic: {topic}", "---", "", f"# 主题：{topic}", ""]
        for it in items:
            day = (it["started_at"] or "")[:10]
            lines.append(f"- [{day}] {it['summary']}  （{it['title']}）")
        with open(os.path.join(topics_dir, f"{_slug(topic)}.md"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    return {"cards": n}
