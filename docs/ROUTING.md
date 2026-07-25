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
