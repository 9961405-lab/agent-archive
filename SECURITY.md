# 安全与隐私

agent-archive 处理的是你与 AI 的**完整对话记录**——里面几乎必然含有密钥、token、内网地址、个人信息。请认真对待下面几点。

## 数据边界

- **默认纯本地、零网络**：`sync` / `search` / `stats` 全程不出本机。
- **唯一会外发数据的功能是 `distill`**：它把对话 prose 正文发给你配置的第三方 LLM（DeepSeek / OpenAI / 自建代理）。
  - 不发送工具输出（命令、文件内容）。
  - 发送前做脱敏（`redact`：抹除 `sk-`/`gho_`/AWS key/Bearer/邮箱/家目录路径等）。
  - 模型返回后再脱敏一次。
  - 可用 `--exclude-project <path>` 排除敏感项目，先用 `--dry-run` 预览会外发什么。
- **MCP server 只读**，数据不出本机。

## 绝不入库的东西

`.gitignore` 已排除，但请自查 commit：

- `raw/`、`md/`、`*.sqlite`、`*.db` —— 对话档案本体
- API key —— 只通过环境变量 / `~/.config/agent-archive/llm.env`（`chmod 600`）传入，**绝不写进任何被 git 跟踪的文件**
- 飞书 `chat_id`、launchd plist 里的真实值 —— 模板用 `__CHAT_ID__` 占位

## 报告漏洞

发现安全问题请私下联系维护者，不要公开开 issue。
