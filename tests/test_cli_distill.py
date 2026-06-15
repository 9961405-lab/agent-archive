import os, json
from agent_archive import cli, store

def _seed(tmp_path):
    root = str(tmp_path / "arc")
    os.makedirs(root, exist_ok=True)
    conn = store.connect(os.path.join(root, "index.sqlite")); store.init_db(conn)
    conn.execute("INSERT INTO conversations "
        "(id,source,title,project,started_at,updated_at,message_count,content_hash,raw_ref,md_ref) "
        "VALUES ('claude:s1','claude','标题','/p','2026-06-14T00:00:00Z','2026-06-14T00:00:00Z',2,'h','r','m')")
    for i,(role,kind,text) in enumerate([("user","prose","x"*300),("assistant","prose","好的")]):
        conn.execute("INSERT INTO messages (conv_id,seq,role,ts,kind,text) VALUES (?,?,?,?,?,?)",
                     ("claude:s1", i, role, "t", kind, text))
    conn.commit(); conn.close()
    return root

def test_dry_run_needs_no_api_key(tmp_path, monkeypatch, capsys):
    root = _seed(tmp_path)
    monkeypatch.delenv("AGENT_ARCHIVE_LLM_API_KEY", raising=False)
    monkeypatch.delenv("AGENT_ARCHIVE_LLM_BASE_URL", raising=False)
    assert cli.main(["--root", root, "distill", "--dry-run"]) == 0
    out = capsys.readouterr().out
    assert "claude:s1" in out and "1" in out

def test_distill_stats(tmp_path, capsys):
    root = _seed(tmp_path)
    conn = store.connect(os.path.join(root, "index.sqlite"))
    store.upsert_distillation(conn, dict(conv_id="claude:s1", content_hash="h", model="m",
        prompt_version="distill-v1", status="ok", summary="s", bullets="[]", decisions="[]",
        todos="[]", topics='["其他"]', value=3, redacted=1, last_error=None)); conn.close()
    assert cli.main(["--root", root, "distill-stats"]) == 0
    assert "ok" in capsys.readouterr().out
