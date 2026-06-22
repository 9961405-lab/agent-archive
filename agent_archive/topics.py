from __future__ import annotations

TOPICS = [
    "电商运营", "3D打印", "Agent/AI开发", "部署运维", "网页爬虫",
    "创意设计", "知识管理", "产品规划", "学习研究", "工具脚本", "其他",
]
_KNOWN = set(TOPICS)


def normalize_topics(raw: list) -> list:
    """把模型给的标签收敛到受控词表：丢弃词表外的、去重保序、最多 3 个；全空→['其他']。"""
    out: list = []
    for t in raw or []:
        if t in _KNOWN and t not in out:
            out.append(t)
        if len(out) == 3:
            break
    return out or ["其他"]
