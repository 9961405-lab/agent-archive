from __future__ import annotations
import os
import re
import sqlite3
from agent_archive.models import Conversation

MAX_INDEX_BYTES = 65536

# CJK ranges (Unified Ideographs, Compatibility Ideographs, Hiragana/Katakana).
# FTS5's default unicode61 tokenizer keeps a whole CJK run as one token, so a
# short substring query (e.g. a 2-char term) never matches. We space-separate
# CJK codepoints both at index and query time so each char is its own token and
# substring queries become phrase queries.
# CJK表意+扩展A+兼容+假名+谚文+全角半角
_CJK = re.compile("([㐀-鿿豈-﫿぀-ヿ가-힣＀-￯])")


def _segment(text: str) -> str:
    return _CJK.sub(r" \1 ", text)


# 把 snippet 里逐字分词留下的空格收回来（CJK 字之间 / CJK 与高亮括号之间）
_DESEG = re.compile(r"(?<=[㐀-鿿豈-﫿぀-ヿ가-힣＀-￯\[\]]) +(?=[㐀-鿿豈-﫿぀-ヿ가-힣＀-￯\[\]])")


def _desegment(text: str) -> str:
    return _DESEG.sub("", text).strip()

SCHEMA = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, source TEXT NOT NULL, title TEXT, project TEXT,
  started_at TEXT, updated_at TEXT, message_count INTEGER,
  content_hash TEXT NOT NULL, raw_ref TEXT NOT NULL, md_ref TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS messages (
  conv_id TEXT NOT NULL, seq INTEGER NOT NULL, role TEXT NOT NULL,
  ts TEXT, kind TEXT, text TEXT, PRIMARY KEY (conv_id, seq)
);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
  text, conv_id UNINDEXED, role UNINDEXED
);
CREATE TABLE IF NOT EXISTS manifest (
  source TEXT NOT NULL, src_path TEXT NOT NULL, src_mtime REAL,
  src_size INTEGER, content_hash TEXT, last_synced_at TEXT,
  PRIMARY KEY (source, src_path)
);
CREATE TABLE IF NOT EXISTS distillations (
  conv_id TEXT PRIMARY KEY,
  content_hash TEXT NOT NULL,
  model TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  status TEXT NOT NULL,
  summary TEXT, bullets TEXT, decisions TEXT, todos TEXT,
  topics TEXT, value INTEGER,
  redacted INTEGER NOT NULL DEFAULT 0,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  last_error TEXT, last_error_at TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""


def connect(path: str) -> sqlite3.Connection:
    # 确保父目录存在，否则首次 stats/search（在 sync 之前）会以
    # sqlite3.OperationalError: unable to open database file 丑陋崩溃。
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def upsert_conversation(conn, conv: Conversation, md_ref: str) -> None:
    conn.execute("DELETE FROM messages WHERE conv_id=?", (conv.id,))
    conn.execute("DELETE FROM messages_fts WHERE conv_id=?", (conv.id,))
    conn.execute(
        "INSERT OR REPLACE INTO conversations "
        "(id,source,title,project,started_at,updated_at,message_count,content_hash,raw_ref,md_ref) "
        "VALUES (?,?,?,?,?,?,?,?,?,?)",
        (conv.id, conv.source, conv.title, conv.project, conv.started_at,
         conv.updated_at, conv.message_count, conv.content_hash, conv.raw_ref, md_ref))
    for seq, m in enumerate(conv.messages):
        conn.execute(
            "INSERT INTO messages (conv_id,seq,role,ts,kind,text) VALUES (?,?,?,?,?,?)",
            (conv.id, seq, m.role, m.ts, m.kind, m.text))
        if m.kind == "prose" and m.text:
            text = m.text.encode("utf-8")[:MAX_INDEX_BYTES].decode("utf-8", "ignore")
            conn.execute("INSERT INTO messages_fts (text,conv_id,role) VALUES (?,?,?)",
                         (_segment(text), conv.id, m.role))
    conn.commit()


def search(conn, query: str, source: str | None = None, project: str | None = None,
           preview: bool = False) -> list[dict]:
    toks = _segment(query).split()
    if not toks:
        return []  # 空/纯空白查询：直接返回，避免 FTS5 语法错误
    # snippet() 不能与 DISTINCT/GROUP BY 同用，preview 时改为按 rank 取行、Python 端去重
    cols = "c.id AS conv_id, c.source, c.title, c.project, c.md_ref"
    if preview:
        cols += ", snippet(messages_fts, 0, '[', ']', '…', 8) AS preview"
    else:
        cols = "DISTINCT " + cols
    sql = (f"SELECT {cols} FROM messages_fts f JOIN conversations c ON c.id=f.conv_id "
           "WHERE messages_fts MATCH ?")
    # 转义短语内的双引号（"→""），防止用户查询里的引号破坏 FTS 短语
    phrase = " ".join(toks).replace('"', '""')
    args = ['"' + phrase + '"']
    if source:
        sql += " AND c.source=?"; args.append(source)
    if project:
        sql += " AND c.project LIKE ?"; args.append(f"%{project}%")
    if preview:
        sql += " ORDER BY rank"  # 最佳命中在前，去重时保留它的片段
    rows = [dict(r) for r in conn.execute(sql, args).fetchall()]
    if not preview:
        return rows
    seen, out = set(), []
    for r in rows:
        if r["conv_id"] not in seen:
            seen.add(r["conv_id"])
            r["preview"] = _desegment(r.get("preview") or "")
            out.append(r)
    return out


def all_conversation_ids(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT id FROM conversations")}


def delete_conversation(conn, conv_id: str) -> tuple[str | None, str | None]:
    """删除一条会话及其消息/FTS/精炼记录。返回 (raw_ref, md_ref) 供调用方清理文件。"""
    row = conn.execute("SELECT raw_ref, md_ref FROM conversations WHERE id=?",
                       (conv_id,)).fetchone()
    if not row:
        return (None, None)
    conn.execute("DELETE FROM messages_fts WHERE conv_id=?", (conv_id,))
    conn.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
    conn.execute("DELETE FROM distillations WHERE conv_id=?", (conv_id,))
    conn.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    return (row["raw_ref"], row["md_ref"])


def delete_manifest_missing(conn) -> int:
    """删除源文件已不存在的 manifest 行，返回删除数。"""
    import os as _os
    gone = [(s, p) for (s, p) in conn.execute("SELECT source, src_path FROM manifest")
            if not _os.path.exists(p)]
    conn.executemany("DELETE FROM manifest WHERE source=? AND src_path=?", gone)
    return len(gone)


def list_conversations(conn, day: str | None = None, source: str | None = None) -> list[dict]:
    """按会话列出（用于按天浏览）。day 为 'YYYY-MM-DD' 时只列当天，按起始时间倒序。"""
    sql = ("SELECT id AS conv_id, source, title, project, started_at, message_count, md_ref "
           "FROM conversations WHERE 1=1")
    args: list = []
    if day:
        sql += " AND substr(COALESCE(started_at,''),1,10)=?"; args.append(day)
    if source:
        sql += " AND source=?"; args.append(source)
    sql += " ORDER BY started_at DESC, source"
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def manifest_get(conn, source: str, src_path: str) -> dict | None:
    r = conn.execute("SELECT src_mtime AS mtime, src_size AS size, content_hash "
                     "FROM manifest WHERE source=? AND src_path=?",
                     (source, src_path)).fetchone()
    return dict(r) if r else None


def manifest_set(conn, source, src_path, mtime, size, content_hash, last_synced_at="") -> None:
    conn.execute("INSERT OR REPLACE INTO manifest "
                 "(source,src_path,src_mtime,src_size,content_hash,last_synced_at) "
                 "VALUES (?,?,?,?,?,?)",
                 (source, src_path, mtime, size, content_hash, last_synced_at))
    conn.commit()


def stats(conn) -> dict:
    out = {}
    for r in conn.execute("SELECT source, COUNT(*) c, SUM(message_count) m "
                          "FROM conversations GROUP BY source"):
        out[r["source"]] = {"conversations": r["c"], "messages": r["m"] or 0}
    return out


import datetime as _dt


def _now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def upsert_distillation(conn, rec: dict) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO distillations "
        "(conv_id,content_hash,model,prompt_version,status,summary,bullets,decisions,todos,"
        " topics,value,redacted,attempt_count,last_error,last_error_at,created_at,updated_at) "
        "VALUES (:conv_id,:content_hash,:model,:prompt_version,:status,:summary,:bullets,"
        ":decisions,:todos,:topics,:value,:redacted,0,:last_error,NULL,:now,:now) "
        "ON CONFLICT(conv_id) DO UPDATE SET "
        "content_hash=excluded.content_hash, model=excluded.model, "
        "prompt_version=excluded.prompt_version, status=excluded.status, summary=excluded.summary, "
        "bullets=excluded.bullets, decisions=excluded.decisions, todos=excluded.todos, "
        "topics=excluded.topics, value=excluded.value, redacted=excluded.redacted, "
        "last_error=excluded.last_error, updated_at=excluded.updated_at",
        {**rec, "now": now})
    conn.commit()


def record_distill_error(conn, conv_id, content_hash, model, prompt_version, err) -> None:
    now = _now()
    conn.execute(
        "INSERT INTO distillations "
        "(conv_id,content_hash,model,prompt_version,status,attempt_count,last_error,last_error_at,"
        " created_at,updated_at) "
        "VALUES (?,?,?,?, 'error', 1, ?, ?, ?, ?) "
        "ON CONFLICT(conv_id) DO UPDATE SET status='error', "
        "attempt_count=distillations.attempt_count+1, last_error=excluded.last_error, "
        "last_error_at=excluded.last_error_at, content_hash=excluded.content_hash, "
        "model=excluded.model, prompt_version=excluded.prompt_version, updated_at=excluded.updated_at",
        (conv_id, content_hash, model, prompt_version, err, now, now, now))
    conn.commit()


def get_distillation(conn, conv_id) -> dict | None:
    r = conn.execute("SELECT * FROM distillations WHERE conv_id=?", (conv_id,)).fetchone()
    return dict(r) if r else None


def distillations_by_topic(conn, topic) -> list[dict]:
    rows = conn.execute(
        "SELECT d.*, c.title, c.started_at, c.md_ref FROM distillations d "
        "JOIN conversations c ON c.id=d.conv_id "
        "WHERE d.status='ok' AND d.topics LIKE ? ORDER BY c.started_at DESC",
        (f'%"{topic}"%',)).fetchall()
    return [dict(r) for r in rows]


def distill_stats(conn) -> dict:
    out = {"ok": 0, "dropped": 0, "error": 0}
    for status, n in conn.execute("SELECT status, COUNT(*) FROM distillations GROUP BY status"):
        out[status] = n
    return out
