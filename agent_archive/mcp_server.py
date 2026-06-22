"""agent-archive MCP server：把本地知识库暴露成 MCP 工具，供 Claude Code / Claude Desktop
等客户端调用。只读、纯本地，数据不出本机。

运行：AGENT_ARCHIVE_ROOT=~/agent-archive-data agent-archive-mcp
"""
from __future__ import annotations
import os
from mcp.server.fastmcp import FastMCP
from agent_archive import store, mcp_tools

mcp = FastMCP("agent-archive")


def _conn():
    root = os.path.expanduser(os.environ.get("AGENT_ARCHIVE_ROOT", "~/agent-archive-data"))
    conn = store.connect(os.path.join(root, "index.sqlite"))
    store.init_db(conn)
    return conn


@mcp.tool()
def search(query: str, source: str | None = None, project: str | None = None,
           limit: int = 20) -> list:
    """全文检索我与 AI（Claude/Codex）的历史对话。query 支持中文任意子串（如「订单」「SSL」）。
    可按 source（claude/codex）或 project 过滤。返回命中会话的 id/标题/项目/Markdown 路径。"""
    return mcp_tools.search(_conn(), query, source=source, project=project, limit=limit)


@mcp.tool()
def get_conversation(conv_id: str) -> dict:
    """按 id 取一条对话的正文（仅人类可读的 prose，不含工具输出，超长截断）。
    id 形如 'claude:<uuid>' 或 'codex:<uuid>'，可从 search 结果获得。"""
    return mcp_tools.get_conversation(_conn(), conv_id)


@mcp.tool()
def recent(days: int = 7, source: str | None = None) -> list:
    """列出最近的会话（标题/源/项目/时间），用于回顾「最近做了什么」。"""
    return mcp_tools.recent(_conn(), days=days, source=source)


@mcp.tool()
def day(date: str | None = None, source: str | None = None) -> list:
    """列出某一天（YYYY-MM-DD，默认今天）的会话。"""
    return mcp_tools.day(_conn(), date=date, source=source)


@mcp.tool()
def digest(period: str = "day", date: str | None = None) -> str:
    """生成日/周/月总结 Markdown（period = day|week|month）：会话数、主题分布、重点、决策、待办。"""
    return mcp_tools.digest(_conn(), period=period, date=date)


@mcp.tool()
def list_topics() -> list:
    """列出知识库的主题及各自的精华卡数量。"""
    return mcp_tools.list_topics(_conn())


@mcp.tool()
def by_topic(topic: str) -> list:
    """取某主题下的精华卡（一句话总结/价值分/时间/会话 id）。topic 取自 list_topics。"""
    return mcp_tools.by_topic(_conn(), topic)


def main():
    mcp.run()


if __name__ == "__main__":
    main()
