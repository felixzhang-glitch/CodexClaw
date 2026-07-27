# 后端路由策略

## 总览

AgentRouter 持有所有后端客户端实例，对外暴露统一接口（`chat` / `chat_stream` / `cancel` / `close`），作为 drop-in 注入 handler。

默认后端：**opencode**。

## 切换命令

| 命令 | 切换目标 |
|------|---------|
| `/opencode` | OpenCode CLI（默认） |
| `/codex` | Codex CLI |
| `/claude` | Claude Code |
| `/qodercli` | Qoder CLI |
| `/backend` | 查看当前后端 + 可选列表 |

## 切换行为

1. 更新 AgentRouter 活跃后端指针
2. 原子写 `runtime/server/backend.json` 持久化
3. 清空当前会话历史（避免跨后端上下文污染）
4. opencode session 不销毁（下次切回可续接）

## 隔离策略

| 后端 | 工作目录 |
|------|---------|
| opencode | `CODEX_WORK_DIR/opencode/` |
| codex | `CODEX_WORK_DIR`（根） |
| claude | `CODEX_WORK_DIR/claude/` |
| qodercli | `CODEX_WORK_DIR/qodercli/` |

## 各后端调用方式

### opencode（主力）

```bash
opencode run --session <session_id> [--model <model>] [--agent <agent>] <prompt>
```

- 输出：逐行 stdout 流式读取
- 会话管理：opencode 原生，codeClaw 只维护 session ID 映射

### codex

```bash
codex exec --skip-git-repo-check --json -C <work_dir> [perms] <prompt>
```

- 输出：JSON event stream（逐行 NDJSON）
- 稳定性：超时 / 重试 / 熔断

### claude / qodercli

```bash
<bin> -p --output-format stream-json --add-dir <work_dir> [--model X] [perms] <prompt>
```

- 输出：stream-json 格式
- 差异：qodercli 不支持 `--verbose` / `--include-partial-messages`

## 文件

```
lib/python/core/agent/
  router.py        → AgentRouter 路由器
  opencode_cli.py  → OpenCode 客户端
  claude_cli.py    → Claude/Qoder CLI 客户端
  types.py         → BackendClient Protocol
```

## 设计决策

### 为什么用 Protocol 抽象

`BackendClient` 是一个 Python Protocol（鸭子类型），不强制继承。各后端客户端只需实现 `chat` / `chat_stream` / `cancel` / `close` 四个方法即可注入 AgentRouter。

决策理由：
- 后端 CLI 调用方式差异大（codex 用 `exec --json`、claude 用 `-p --output-format stream-json`、opencode 用 `run --session`），不适合强继承
- 新增后端只需实现 Protocol，不改路由器代码
- handler 层通过类型标注依赖 Protocol 而非具体类

### 为什么切换时清空会话

后端切换成功后会清空当前会话历史。原因：
- 不同后端的工具能力、skills、回答风格差异大，混用上下文会导致幻觉
- opencode 的 session 是独立于 codeClaw 会话管理的，切到 opencode 不需要旧历史
- 从 opencode 切走时，opencode session 保留（下次切回可续接），但 codeClaw 侧的历史清空

### opencode 会话管理 vs 其他后端

| 维度 | opencode | codex / claude / qodercli |
|------|----------|---------------------------|
| 会话持久化 | opencode 原生 `--session` | codeClaw FIFO 历史拼接 |
| 上下文压缩 | opencode 内部自管 | codeClaw `/compact` 手动触发 |
| session 映射 | `user_id:chat_id` -> opencode session_id，持久化在 `opencode-sessions.json` | 无独立 session 概念 |
| `/new` 行为 | 生成新 opencode session_id | 清空历史数组 |

### 状态持久化方案

后端选择状态写入 `runtime/server/backend.json`，使用原子写（先写 `.tmp` 再 `os.replace`）防止断电损坏。启动时加载；文件不存在则 fallback 到 `ACTIVE_BACKEND` 环境变量。

选择文件而非内存的原因：重启后保留用户上次选择的后端，避免每次重启都回到默认。
