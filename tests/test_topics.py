from agent_archive.topics import TOPICS, normalize_topics

def test_topics_is_closed_set_with_other():
    assert "其他" in TOPICS
    assert "电商运营" in TOPICS

def test_normalize_keeps_known_drops_unknown():
    assert normalize_topics(["电商运营", "瞎编的标签", "3D打印"]) == ["电商运营", "3D打印"]

def test_normalize_unknown_only_becomes_other():
    assert normalize_topics(["瞎编", "也瞎编"]) == ["其他"]

def test_normalize_dedups_and_limits_to_3():
    out = normalize_topics(["电商运营","电商运营","3D打印","部署运维","学习研究"])
    assert out == ["电商运营","3D打印","部署运维"]

def test_normalize_handles_empty():
    assert normalize_topics([]) == ["其他"]
