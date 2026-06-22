from agent_archive.collectors import get_collectors, Collector


def test_registry_has_claude_and_codex():
    cols = {c.source: c for c in get_collectors()}
    assert set(cols) == {"claude", "codex", "hermes"}
    for c in cols.values():
        assert isinstance(c, Collector)


def test_filter_by_source():
    cols = get_collectors(only="codex")
    assert [c.source for c in cols] == ["codex"]
