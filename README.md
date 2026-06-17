# agent-archive

把本地 Agent 对话（Claude Code / Codex）沉淀成 **原始镜像 + Markdown + SQLite(FTS5)** 三层档案。纯本地、零网络依赖。

## 安装

    /opt/homebrew/bin/python3.14 -m venv .venv
    .venv/bin/python -m pip install -e .

## 用法

    .venv/bin/python -m agent_archive.cli sync                  # 增量同步
    .venv/bin/python -m agent_archive.cli sync --source codex   # 只同步某源
    .venv/bin/python -m agent_archive.cli sync --full           # 全量重建
    .venv/bin/python -m agent_archive.cli search "关键词"
    .venv/bin/python -m agent_archive.cli search "x" --source claude --project 房间渲染
    .venv/bin/python -m agent_archive.cli stats

档案默认在 `~/agent-archive/`（可用 `--root` 或环境变量 `AGENT_ARCHIVE_ROOT` 覆盖）。
三层产物：`raw/`（原文件镜像，hardlink）、`md/<日期>/`（精炼 Markdown）、`index.sqlite`（FTS5 全文索引 + 增量 manifest）。

## 数据源

- **Claude Code** — `~/.claude/projects/**/*.jsonl`
- **Codex** — `~/.codex/sessions/**/rollout-*.jsonl`（标题取自 `~/.codex/session_index.jsonl`）

中文全文检索：FTS5 默认分词器把整段中文当一个 token，本项目对 CJK 逐字分词（索引与查询两端对称），所以可按任意子串（如「订单」「脚本」）搜索。

## 每日自动（macOS launchd）

    cp scripts/com.agentarchive.sync.plist ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/com.agentarchive.sync.plist

每天 23:30 自动增量同步；日志见 `sync.log` / `sync.err`。

## 隐私

档案含密钥/隐私，纯本地、不上云。`raw/ md/ *.sqlite .venv/` 已在 `.gitignore` 中排除。

## 精炼（distill，可选，需第三方 LLM）

把会话提炼成结构化精华卡 + 主题页（写进 distilled/ 与 topics/）。**会把 prose 正文外发第三方 API**——见下方隐私说明。

配置（OpenAI 兼容，任选 DeepSeek / OpenAI / 自建代理）：

    export AGENT_ARCHIVE_LLM_BASE_URL=https://api.deepseek.com/v1
    export AGENT_ARCHIVE_LLM_API_KEY=sk-xxxx
    export AGENT_ARCHIVE_LLM_MODEL=deepseek-chat

用法：

    agent-archive distill --dry-run         # 免 key，先看会外发哪些会话 + 脱敏样例
    agent-archive distill --limit 10 --yes  # 试跑 10 个
    agent-archive distill --yes             # 全量（顺序，约 15-35 分钟）
    agent-archive distill --exclude-project /Users/mac/secret --yes   # 排除敏感项目
    agent-archive topics                    # 重建主题页
    agent-archive distill-stats             # ok/dropped/error 计数

### 隐私（重要）
- distill **会把会话 prose 外发**（不发工具输出、发送前脱敏、模型输出回程再脱敏）。
- 脱敏是尽力而为，**不是保证**；敏感项目用 `--exclude-project` 直接排除。
- distill **不进每日定时**，只在你手动执行时运行。
- 软链产物进 Obsidian（可选）：
      ln -s ~/agent-archive-data/distilled "~/Documents/Obsidian Vault/精华"
      ln -s ~/agent-archive-data/topics    "~/Documents/Obsidian Vault/主题"

## 接入 Agent（MCP server，让模型读知识库）

把知识库暴露成 MCP 工具，任何 MCP 客户端的模型都能查（只读、纯本地、数据不出本机）。

安装依赖：`.venv/bin/python -m pip install -e ".[mcp]"`

工具：`search` / `get_conversation` / `recent` / `day` / `digest` / `list_topics` / `by_topic`。

### Claude Code
    claude mcp add agent-archive \
      --env AGENT_ARCHIVE_ROOT=/Users/mac/agent-archive-data \
      -- /Users/mac/agent-archive/.venv/bin/agent-archive-mcp
新开会话后，模型即可调用上面的工具查你的对话历史。

### Claude Desktop
编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`，把
`scripts/mcp-config.example.json` 里的 `mcpServers.agent-archive` 段合并进去，重启 Claude Desktop。

### 自测
    AGENT_ARCHIVE_ROOT=~/agent-archive-data .venv/bin/agent-archive-mcp   # 启动 stdio server（Ctrl-C 退出）

## 后续（未实现）

Cursor / Devin（需 API token）/ WorkBuddy / 飞书；以及语义检索（向量）。详见 `docs/superpowers/specs/`。
