# 贡献指南

欢迎 PR。这个项目刻意保持小而纯：**核心运行时零第三方依赖**（只用 Python 标准库），请尽量不要引入新依赖。

## 开发环境

    python3 -m venv .venv
    .venv/bin/python -m pip install -e ".[mcp]"
    .venv/bin/python -m pytest -q          # 跑测试（应全绿）

## 约定

- **测试先行**：新功能/修 bug 都带测试。fixture 用通用假名（如 `demo-project`），**绝不放真实路径、真实密钥、真实对话**。
- **隐私第一**：任何会让数据离开本机的改动，必须经过 `redact` 脱敏，并在 PR 描述里说明数据流向。
- **新增数据源**：实现一个 collector（见 `agent_archive/collectors/`，照 `claude.py` / `codex.py` / `hermes.py` 的 `discover()` + `parse()` 模式），在 `collectors/__init__.py` 注册，并加解析测试。
- 提交信息讲清「为什么」，不只是「改了什么」。

## 提交前自查

    .venv/bin/python -m pytest -q          # 全绿
    git grep -nE 'sk-[a-zA-Z0-9]{20}|/Users/[a-z]+/' -- '*.py' '*.md'   # 无真实密钥/家目录
