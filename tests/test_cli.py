import os
from agent_archive import cli
from agent_archive.collectors.claude import ClaudeCollector

FIX = os.path.join(os.path.dirname(__file__), "fixtures")

def _root_with_data(tmp_path, monkeypatch):
    proj = tmp_path / "src"; proj.mkdir()
    (proj / "sess1.jsonl").write_text(
        open(os.path.join(FIX, "claude_sample.jsonl"), encoding="utf-8").read(), encoding="utf-8")
    monkeypatch.setattr(cli, "get_collectors",
                        lambda only=None: [ClaudeCollector(root=str(proj))])
    return str(tmp_path / "archive")

def test_cli_sync_then_search(tmp_path, monkeypatch, capsys):
    root = _root_with_data(tmp_path, monkeypatch)
    assert cli.main(["--root", root, "sync"]) == 0
    assert cli.main(["--root", root, "search", "脚本"]) == 0
    out = capsys.readouterr().out
    assert "claude:sess1" in out

def test_cli_stats(tmp_path, monkeypatch, capsys):
    root = _root_with_data(tmp_path, monkeypatch)
    cli.main(["--root", root, "sync"])
    assert cli.main(["--root", root, "stats"]) == 0
    assert "claude" in capsys.readouterr().out

def test_cli_day(tmp_path, monkeypatch, capsys):
    root = _root_with_data(tmp_path, monkeypatch)
    cli.main(["--root", root, "sync"])
    # 该 fixture 会话起始日为 2026-06-14
    assert cli.main(["--root", root, "day", "2026-06-14"]) == 0
    out = capsys.readouterr().out
    assert "2026-06-14" in out and "1 个会话" in out and "帮我写个脚本" in out

def test_cli_recent(tmp_path, monkeypatch, capsys):
    root = _root_with_data(tmp_path, monkeypatch)
    cli.main(["--root", root, "sync"])
    assert cli.main(["--root", root, "recent", "30"]) == 0
    assert "2026-06-14" in capsys.readouterr().out
