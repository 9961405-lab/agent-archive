#!/bin/bash
# 自动提炼当天新增/变化的会话（增量，已缓存的跳过），然后重建主题页。
# LLM 凭证从 ~/.config/agent-archive/llm.env 读取（你自己创建，不入 git）。
set -euo pipefail

ENV_FILE="${AGENT_ARCHIVE_LLM_ENV:-$HOME/.config/agent-archive/llm.env}"
if [ ! -f "$ENV_FILE" ]; then
  echo "缺少 $ENV_FILE —— 请创建并写入 AGENT_ARCHIVE_LLM_BASE_URL/_MODEL/_API_KEY" >&2
  exit 1
fi
# shellcheck disable=SC1090
source "$ENV_FILE"

cd "$HOME/agent-archive"
export AGENT_ARCHIVE_ROOT="${AGENT_ARCHIVE_ROOT:-$HOME/agent-archive-data}"
.venv/bin/python -m agent_archive.cli distill --yes
.venv/bin/python -m agent_archive.cli topics
