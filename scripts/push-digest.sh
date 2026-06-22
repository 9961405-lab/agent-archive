#!/bin/bash
# 生成周期总结并推送到飞书「知识库」群。
# 用法: push-digest.sh day|week|month
# 依赖环境变量 AGENT_ARCHIVE_LARK_CHAT_ID（飞书群 chat_id, oc_ 开头）。
set -euo pipefail

# launchd 跑任务时 PATH 极简，缺 node（lark-cli 是 node 脚本）。
# 把常见 node / homebrew 目录补进来，否则推送会 env: node: No such file or directory。
export PATH="$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

PERIOD="${1:-day}"
ROOT="${AGENT_ARCHIVE_ROOT:-$HOME/agent-archive-data}"
REPO="$HOME/agent-archive"
LARK="${LARK_CLI:-/opt/homebrew/bin/lark-cli}"
: "${AGENT_ARCHIVE_LARK_CHAT_ID:?需要设置 AGENT_ARCHIVE_LARK_CHAT_ID=oc_xxx}"

cd "$REPO"
MD="$(AGENT_ARCHIVE_ROOT="$ROOT" .venv/bin/python -m agent_archive.cli digest --period "$PERIOD")"

# 以用户身份发到群；--markdown 自动转飞书 post
"$LARK" im +messages-send --chat-id "$AGENT_ARCHIVE_LARK_CHAT_ID" --as user --markdown "$MD"
