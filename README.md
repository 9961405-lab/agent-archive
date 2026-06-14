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

## 后续（未实现）

Cursor / Devin（需 API token）/ WorkBuddy / 飞书；以及 LLM 摘要、语义检索、同步层。详见 `docs/superpowers/specs/`。
