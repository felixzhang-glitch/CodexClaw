# Codex 后端客户端

## 模块职责

封装本机 `codex exec --json` CLI 调用，提供超时控制、重试、熔断、取消（kill 子进程）、streaming JSON 事件解析能力。

## 关键文件

| 文件 | 职责 | 行数 |
|------|------|------|
| `lib/python/core/codex/client.py` | Codex CLI 客户端全部逻辑 | 599 |

## 核心接口/类

### `CodexClient`

- **用途**：codex CLI 封装，作为 `BackendClient` Protocol 的实现之一
- **关键方法**：
  - `chat(messages, trace_id)` → 非流式调用，返回完整文本
  - `chat_stream(messages, trace_id)` → 流式调用，`AsyncIterator[str]`
  - `cancel(trace_id)` → kill 子进程（仅当该 trace_id 有活跃进程时生效）
  - `close()` → 空操作（CLI 模式无持久连接）

### 命令构造

```bash
codex exec --skip-git-repo-check --json -C <CODEX_WORK_DIR> [权限参数] [模型参数] <prompt>
```

权限映射：
- `full` → `--dangerously-bypass-approvals-and-sandbox`
- `workspace-write` → `--sandbox workspace-write --ask-for-approval never`
- `read-only` → `--sandbox read-only --ask-for-approval never`

### 超时机制

使用总 deadline 而非逐行超时：

```python
deadline = time.monotonic() + self._settings.codex_timeout_seconds
# 每行读取时计算剩余时间
remaining = deadline - time.monotonic()
if remaining <= 0:
    raise asyncio.TimeoutError
```

### 事件解析

`codex exec --json` 按行输出 JSON 事件：
- `item.completed` + `agent_message` → 最终文本
- `*delta*` 类型 → 增量文本
- `error` / `turn.failed` / `item.completed(error)` → 错误信息

## 设计模式

| 模式 | 应用位置 | 意图 |
|------|----------|------|
| 熔断器 | `_assert_circuit_closed` / `_record_failure` | 连续失败 N 次后冷却窗口拒绝请求 |
| 注册表 | `_active_processes` dict | trace_id → subprocess 映射，支持 cancel |
| 重试策略 | `chat` / `chat_stream` 的 while 循环 | 可重试错误指数退避重试 |

## 依赖关系

### 上游依赖

- **app.config**：`Settings` 读取 CLI 路径、工作目录、超时、重试、熔断参数

### 下游被依赖

- **core.agent.router**：作为 `AgentRouter` 的三个后端客户端之一

### 外部依赖

- **codex CLI**：本机安装的 `codex` 二进制，需 `codex login` 完成

## 注意事项

- `cancel()` 先检查 `_active_processes` 是否有匹配 trace_id，无匹配则直接返回 False，不污染 `_cancel_requests` 集合
- 熔断阈值默认 5 次，冷却 30 秒
- `CODEX_STREAM_READ_LIMIT_BYTES` 默认 262144（256KB），避免超长单行 JSON 触发默认 64KB 限制
- 重试时不重试认证类错误（`unauthorized` / `authentication`）和 `return_code=2`
