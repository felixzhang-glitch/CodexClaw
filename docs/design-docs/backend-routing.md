# 多后端路由设计决策

## 为什么用 Protocol 抽象

`BackendClient` 是一个 Python Protocol（鸭子类型），不强制继承。各后端客户端只需实现 `chat` / `chat_stream` / `cancel` / `close` 四个方法即可注入 AgentRouter。

决策理由：
- 后端 CLI 调用方式差异大（codex 用 `exec --json`、claude 用 `-p --output-format stream-json`、opencode 用 `run --session`），不适合强继承
- 新增后端只需实现 Protocol，不改路由器代码
- handler 层通过类型标注依赖 Protocol 而非具体类

## 为什么切换时清空会话

后端切换成功后会清空当前会话历史。原因：
- 不同后端的工具能力、skills、回答风格差异大，混用上下文会导致幻觉
- opencode 的 session 是独立于 codeClaw 会话管理的，切到 opencode 不需要旧历史
- 从 opencode 切走时，opencode session 保留（下次切回可续接），但 codeClaw 侧的历史清空

## opencode 会话管理 vs 其他后端

| 维度 | opencode | codex / claude / qodercli |
|------|----------|---------------------------|
| 会话持久化 | opencode 原生 `--session` | codeClaw FIFO 历史拼接 |
| 上下文压缩 | opencode 内部自管 | codeClaw `/compact` 手动触发 |
| session 映射 | `user_id:chat_id` -> opencode session_id，持久化在 `opencode-sessions.json` | 无独立 session 概念 |
| `/new` 行为 | 生成新 opencode session_id | 清空历史数组 |

## 状态持久化方案

后端选择状态写入 `runtime/server/backend.json`，使用原子写（先写 `.tmp` 再 `os.replace`）防止断电损坏。启动时加载；文件不存在则 fallback 到 `ACTIVE_BACKEND` 环境变量。

选择文件而非内存的原因：重启后保留用户上次选择的后端，避免每次重启都回到默认。
