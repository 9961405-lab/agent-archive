# agent-archive

![CI](https://github.com/9961405-lab/agent-archive/actions/workflows/ci.yml/badge.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue)
![License](https://img.shields.io/badge/license-MIT-green)

把本地 AI Agent 对话（Claude Code / Codex / Hermes）沉淀成 **原始镜像 + Markdown + SQLite(FTS5)** 三层档案。纯本地、**核心零第三方依赖**（只用 Python 标准库）、零网络。

可选加挂：第三方 LLM 提炼精华卡、飞书定时推送、Obsidian 浏览、MCP 让任意 AI 读你的知识库。

## 5 分钟上手

```bash
git clone https://github.com/9961405-lab/agent-archive && cd agent-archive
python3 --version                           # 必须 ≥ 3.11；低于 3.11 请先装新版（brew install python@3.12）
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip   # 老 pip 不支持 pyproject 的 editable 安装
.venv/bin/python -m pip install -e .

# 把你本机的 Claude Code / Codex 对话扫进知识库（纯本地，不联网）
AGENT_ARCHIVE_ROOT=~/agent-archive-data .venv/bin/python -m agent_archive.cli sync
AGENT_ARCHIVE_ROOT=~/agent-archive-data .venv/bin/python -m agent_archive.cli search "关键词"
```

就这样，**核心功能（sync + search）到此为止：免费、离线、不依赖任何账号**。下面都是可选增强：

| 想要 | 看哪节 | 需要 |
|---|---|---|
| 提炼精华卡 / 主题页 | [精炼](#精炼distill可选需第三方-llm) | 自备 LLM key（DeepSeek/OpenAI…） |
| 每天自动同步 | [每日自动](#每日自动macos-launchd) | macOS launchd |
| 让 AI 读你的知识库 | [接入 Agent](#接入-agentmcp-server让模型读知识库) | MCP 客户端 |
| 飞书定时推送日报 | `scripts/push-digest.sh` | 飞书 CLI + chat_id |

## 用法

    .venv/bin/python -m agent_archive.cli sync                    # 增量同步
    .venv/bin/python -m agent_archive.cli sync --source codex     # 只同步某源
    .venv/bin/python -m agent_archive.cli sync --full             # 全量重建
    .venv/bin/python -m agent_archive.cli search "关键词"
    .venv/bin/python -m agent_archive.cli search "关键词" --preview          # 显示命中片段
    .venv/bin/python -m agent_archive.cli search "关键词" --format json      # 导出 JSON，便于喂给其他工具
    .venv/bin/python -m agent_archive.cli search "x" --source claude --project demo-project
    .venv/bin/python -m agent_archive.cli stats
    .venv/bin/python -m agent_archive.cli prune --dry-run                   # 列出源文件已删除的僵尸会话
    .venv/bin/python -m agent_archive.cli prune --yes                       # 清理它们（含 raw/md 文件）

档案默认在 `~/agent-archive-data/`（可用 `--root` 或环境变量 `AGENT_ARCHIVE_ROOT` 覆盖）。
三层产物：`raw/`（原文件镜像，hardlink）、`md/<日期>/`（精炼 Markdown）、`index.sqlite`（FTS5 全文索引 + 增量 manifest）。

## 数据源

- **Claude Code** — `~/.claude/projects/**/*.jsonl`
- **Codex** — `~/.codex/sessions/**/rollout-*.jsonl`（标题取自 `~/.codex/session_index.jsonl`）
- **Hermes** — `~/.hermes/state.db`（SQLite：`sessions` + `messages` 表）

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
    agent-archive distill --exclude-project ~/work/secret --yes   # 排除敏感项目
    agent-archive topics                    # 重建主题页
    agent-archive distill-stats             # ok/dropped/error 计数

### 隐私（重要）
- distill **会把会话 prose 外发**（不发工具输出、发送前脱敏、模型输出回程再脱敏）。
- 脱敏是尽力而为，**不是保证**；敏感项目用 `--exclude-project` 直接排除。
- distill **不进每日定时**，只在你手动执行时运行。
- 在 Obsidian 里浏览（可选）：把 vault 直接指向 `~/agent-archive-data`，或软链产物进已有 vault：
      ln -s ~/agent-archive-data/distilled "$HOME/Documents/Obsidian Vault/精华"
      ln -s ~/agent-archive-data/topics    "$HOME/Documents/Obsidian Vault/主题"
  注意：Obsidian 对外部软链只在打开/重载库时扫描一次，新文件可能要 Cmd-R 重载才出现。

## 接入 Agent（MCP server，让模型读知识库）

把知识库暴露成 MCP 工具，任何 MCP 客户端的模型都能查（只读、纯本地、数据不出本机）。

安装依赖：`.venv/bin/python -m pip install -e ".[mcp]"`

工具：`search` / `get_conversation` / `recent` / `day` / `digest` / `list_topics` / `by_topic`。

### Claude Code
    claude mcp add agent-archive \
      --env AGENT_ARCHIVE_ROOT="$HOME/agent-archive-data" \
      -- "$HOME/agent-archive/.venv/bin/agent-archive-mcp"
新开会话后，模型即可调用上面的工具查你的对话历史。

### Claude Desktop
编辑 `~/Library/Application Support/Claude/claude_desktop_config.json`，把
`scripts/mcp-config.example.json` 里的 `mcpServers.agent-archive` 段合并进去，重启 Claude Desktop。

### 自测
    AGENT_ARCHIVE_ROOT=~/agent-archive-data .venv/bin/agent-archive-mcp   # 启动 stdio server（Ctrl-C 退出）

## 后续（未实现）

Cursor / Devin（需 API token）/ WorkBuddy / 飞书；以及语义检索（向量）。详见 `docs/superpowers/specs/`。
