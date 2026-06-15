from __future__ import annotations
import re
import sqlite3
from agent_archive.models import Conversation

MAX_INDEX_BYTES = 65536

# CJK ranges (Unified Ideographs, Compatibility Ideographs, Hiragana/Katakana).
# FTS5's default unicode61 tokenizer keeps a whole CJK run as one token, so a
# short substring query (e.g. a 2-char term) never matches. We space-separate
# CJK codepoints both at index and query time so each char is its own token and
# substring queries become phrase queries.
_CJK = re.compile(r"([㐀-鿿豈-﫿぀-ヿ])")


def _segment(text: str) -> str:
    return _CJK.sub(r" \1 ", text)

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
"""


def connect(path: str) -> sqlite3.Connection:
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


def search(conn, query: str, source: str | None = None, project: str | None = None) -> list[dict]:
    sql = ("SELECT DISTINCT c.id AS conv_id, c.source, c.title, c.project, c.md_ref "
           "FROM messages_fts f JOIN conversations c ON c.id=f.conv_id "
           "WHERE messages_fts MATCH ?")
    toks = _segment(query).split()
    if not toks:
        return []  # 空/纯空白查询：直接返回，避免 FTS5 语法错误
    # 转义短语内的双引号（"→""），防止用户查询里的引号破坏 FTS 短语
    phrase = " ".join(toks).replace('"', '""')
    args = ['"' + phrase + '"']
    if source:
        sql += " AND c.source=?"; args.append(source)
    if project:
        sql += " AND c.project LIKE ?"; args.append(f"%{project}%")
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
