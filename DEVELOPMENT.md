# CodexClaw 开发文档

本文档面向后续维护和二次开发，聚焦代码结构、运行链路、关键配置和常见改造点。

## 1. 项目定位

CodexClaw 是一个 Feishu 私聊机器人后端服务，核心职责：

1. 接收 Feishu 事件回调。
2. 解析/校验消息并维护会话上下文。
3. 调用本机 `codex exec`（默认 `full` 权限）生成答案。
4. 将结果回传 Feishu。

当前实现特性：

- 单实例服务（FastAPI + Uvicorn）
- Feishu 文本消息闭环
- 群聊 @ 机器人触发处理
- 会话记忆（默认 10 轮 FIFO）
- `/help`、`/new`、`/reset`、`/compact`、`/stop`
- `/remind <时间> <内容>` 定时提醒，时间单位支持 `s/m/h/d`
- 快速回执（reaction: `emoji_type=Typing`）
- 长任务通知（默认 30 秒后提示“仍在运行中”）
- 普通 reply 失败后，按 `chat_id` 主动发送兜底
- 飞书 OpenAPI transient failure 重试
- 飞书长文本智能分段，尽量保留段落和代码块完整性
- 自动识别 Codex 输出中的本地图片路径并上传为飞书图片消息
- 同一会话同一时刻只允许一个运行中任务
- 最终答案默认单条回复（超长时自动回退分段）
- 结构化日志

---

## 2. 目录结构

```text
app/
  config.py          # 环境变量与配置
  logging.py         # JSON 结构化日志
  commands.py        # /help /new /reset /stop
  main.py            # FastAPI 入口

channel/feishu/
  models.py          # Feishu 事件解析模型
  security.py        # 签名校验与解密
  client.py          # Feishu OpenAPI 调用（reply/reaction/token）
  handler.py         # Feishu webhook 主处理流程

core/codex/
  client.py          # 本机 codex CLI 调用封装（超时/重试/熔断）

core/session/
  manager.py         # 会话存储与 FIFO 裁剪
  deduplicator.py    # message_id 去重
  task_registry.py   # 运行中任务注册与取消
  reminder_scheduler.py # 单实例内存定时提醒

tests/               # 单元测试

server               # 服务控制脚本（start/stop/status/help）
start                # 快捷入口（默认后台，-f 前台）
start.sh             # 兼容入口（转发到 start）
.env.example         # 示例配置
README.md            # 用户使用说明
DEVELOPMENT.md       # 本文档
```

---

## 3. 启动与进程管理

### 3.1 命令入口

- `./start`：后台启动（等价 `./server start`）
- `./start -f`：前台启动并输出日志（等价 `./server start -f`）
- `./server stop`：停止服务
- `./server status`：查看状态
- `./server help`：查看帮助

### 3.2 运行期文件

- PID 文件：`runtime/server/codexclaw.pid`
- 日志文件：`runtime/server/codexclaw.log`
- Codex 工作目录：`runtime/codex-workdir`（可由 `CODEX_WORK_DIR` 覆盖）

### 3.3 首次启动流程

`server` 脚本会自动：

1. 检查 `python3` 和 `codex`。
2. 自动创建 `.venv` 并安装依赖。
3. 初始化 `.env`（若不存在则由 `.env.example` 复制）。
4. 引导填写 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。
5. 确保 `CODEX_PERMISSION_MODE=full`。
6. 启动 Uvicorn。

---

## 4. 配置说明（核心）

配置从 `.env` 读取，关键项如下。

### 4.1 Feishu

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`（可选，配置后会校验）
- `FEISHU_ENCRYPT_KEY`（建议配置，用于签名校验/加密场景）
- `FEISHU_API_BASE`（默认 `https://open.feishu.cn`）
- `FEISHU_BOT_OPEN_ID`（可选，配置后群聊只响应 @ 该 open_id）
- `FEISHU_GROUP_REQUIRE_MENTION`（默认 `true`）
- `FEISHU_MAX_RETRIES`（默认 `2`）
- `FEISHU_RETRY_BACKOFF_SECONDS`（默认 `0.5`）

### 4.2 Codex CLI

- `CODEX_CLI_BIN`（默认 `codex`）
- `CODEX_WORK_DIR`（默认 `./runtime/codex-workdir`）
- `CODEX_PERMISSION_MODE`（默认 `full`）
- `CODEX_MODEL`（可空；空时使用本机 codex 默认模型）
- `CODEX_TIMEOUT_SECONDS`：单次读取 stdout 新行的超时时间，不是总任务时长上限
- `CODEX_STREAM_READ_LIMIT_BYTES`：subprocess stream 读取上限，避免超长单行 JSON 触发默认 64KB 限制
- `CODEX_MAX_RETRIES`
- `CODEX_RETRY_BACKOFF_SECONDS`
- `CODEX_CIRCUIT_BREAKER_THRESHOLD`
- `CODEX_CIRCUIT_BREAKER_COOLDOWN_SECONDS`

说明：

- 当前后端不依赖 `CODEX_API_KEY`，因为走的是本机 `codex exec`。
- 为兼容历史配置，保留了 `CODEX_API_BASE/CODEX_API_KEY` 字段，但 CLI 模式默认不用。

### 4.3 业务行为

- `MAX_HISTORY_ROUNDS`：会话记忆轮数，默认 `10`
- `STREAMING_ENABLED`：是否启用流式获取（当前即使流式获取，也会汇总后单条回发）
- `TASK_RUNNING_NOTICE_SECONDS`：长任务通知阈值，默认 `30`
- `FEISHU_MESSAGE_CHUNK_CHARS`：Feishu 文本拆分长度，默认 `120`
- `REMINDER_STORE_PATH`：待触发提醒持久化文件，默认 `./runtime/server/reminders.json`
- `SERVER_HOST`
- `SERVER_PORT`
- `LOG_LEVEL`

---

## 5. 请求处理链路

### 5.1 Webhook 入口

`POST /webhook/feishu` -> `app/main.py` -> `FeishuWebhookHandler.handle_webhook`

处理顺序：

1. 解析 JSON 请求体
2. 校验签名（如果带签名头）
3. 处理 challenge（`url_verification`）
4. 解析事件，接受私聊文本；群聊默认要求 @ 机器人后触发
5. 异步处理具体消息（立即返回 `{"code": 0}`）

### 5.2 消息处理（_handle_text_event）

1. 去重（`message_id`）
2. 基于 `user_id + chat_id` 生成 session key
3. 特判 `/stop`：终止当前会话中的运行任务
4. 发送 quick ack reaction（`Typing`）
5. 若当前会话已有运行中任务，直接回复“已有任务在运行中”
6. 命令分支：`/help` `/new` `/reset` `/compact`
7. 读取会话历史，拼接当前问题
8. 在 `task_registry` 中登记运行任务并启动长任务通知定时器
9. 调用 Codex CLI
10. 回发答案（单条）
11. 写回会话历史
12. 清理运行任务登记与定时器

`/remind` 命令不进入 Codex 执行链路，会登记到单实例调度器并持久化到 `REMINDER_STORE_PATH`，到期后通过 `im/v1/messages?receive_id_type=chat_id` 主动发送。

`/compact` 会把较早的会话轮次压缩成一条摘要轮次，并保留最近 2 轮原文，适合长会话里降低后续 prompt 体积。

当 Codex 输出里包含 `file://...png/jpg/gif/webp` 或本地绝对图片路径时，handler 会先清理文本里的本地路径，再调用 `POST /open-apis/im/v1/images` 上传图片并用 `msg_type=image` 回复或主动发送到当前 chat。

取消时：回复 `当前任务已终止。`

异常时：记录错误日志并回复 `服务繁忙，请稍后重试。`

---

## 6. Codex CLI 集成细节

文件：`core/codex/client.py`

### 6.1 命令构造

基础命令：

```bash
codex exec --skip-git-repo-check --json -C <CODEX_WORK_DIR>
```

权限映射：

- `full` -> `--dangerously-bypass-approvals-and-sandbox`
- `workspace-write` -> `--sandbox workspace-write --ask-for-approval never`
- `read-only` -> `--sandbox read-only --ask-for-approval never`

### 6.2 模型选择

- 当 `CODEX_MODEL` 为空：不传 `-m`，使用本机 codex 默认模型。
- 为兼容 ChatGPT 账号场景，`codex-mini-latest` 不会显式传入。

### 6.3 事件解析

`codex exec --json` 的输出按行读取 JSON event：

- `item.completed` + `agent_message` 作为最终文本
- `*delta*` 类型事件尝试提取增量文本
- `error` / `turn.failed` / `item.completed(error)` 提取错误信息

### 6.4 稳定性机制

- 超时控制：`CODEX_TIMEOUT_SECONDS`
- 重试：`CODEX_MAX_RETRIES` + 退避
- 熔断：连续失败阈值后冷却窗口拒绝请求
- 取消：通过 `trace_id` 注册当前 `codex exec` 子进程，`/stop` 时调用 `process.kill()`
- 大行保护：subprocess 使用 `CODEX_STREAM_READ_LIMIT_BYTES` 提高 asyncio stream limit

### 6.5 取消与长任务通知

- 运行任务按会话维度注册在 `core/session/task_registry.py`
- 每个运行任务记录 `trace_id`、`message_id`、启动时间和通知状态
- 超过 `TASK_RUNNING_NOTICE_SECONDS` 且任务仍在运行时，会主动发送“仍在运行中”提示
- 用户发送 `/stop` 后：
  - 立即回复“已收到停止请求，正在强制终止当前任务。”
  - 杀掉当前 `codex exec` 子进程
  - 在主任务收敛后回复“当前任务已终止。”

---

## 7. 会话与记忆

文件：`core/session/manager.py`

- 会话 Key：`user_id + ':' + chat_id`
- 每轮存储：`user` + `assistant`
- 超出 `MAX_HISTORY_ROUNDS` 时，按 FIFO 删除最早轮次
- `/new`：生成新会话 ID，清空上下文
- `/reset`：清空当前会话轮次
- `/compact`：压缩较早轮次为一条摘要，保留最近 2 轮原始上下文

补充：

- 当前运行中任务不在 `SessionManager` 中管理，而是在 `task_registry` 中独立管理
- 这样可以把“会话历史”和“运行态控制”解耦，便于后续替换成 Redis/DB

---

## 8. Feishu 客户端能力

文件：`channel/feishu/client.py`

- 获取并缓存 `tenant_access_token`
- 回复文本消息：`POST /im/v1/messages/{message_id}/reply`
- 上传图片：`POST /im/v1/images`
- 回复/发送图片消息：`msg_type=image` + `{"image_key":"..."}`
- 快速回执 reaction：`POST /im/v1/messages/{message_id}/reactions`
  - 请求体：`{"reaction_type":{"emoji_type":"Typing"}}`

---

## 9. 测试说明

运行：

```bash
source .venv/bin/activate
pytest -q
```

当前测试覆盖：

- Feishu 文本事件解析
- Feishu 签名校验
- 会话 FIFO 裁剪
- `/new` 行为
- Codex streaming mock
- quick ack reaction + 单条最终回复行为
- 长任务通知行为
- `/stop` 取消运行中任务
- reaction 请求体校验（`Typing`）

---

## 10. 常见问题排查

### 10.1 Feishu 401

重点检查：

- `FEISHU_ENCRYPT_KEY` 是否与平台一致
- `FEISHU_VERIFICATION_TOKEN` 是否一致
- 回调 URL 是否正确可达

### 10.2 启动失败 address already in use

端口被占用：

- 换端口启动：`SERVER_PORT=18080 ./start`
- 或先停掉旧进程

### 10.3 收到“服务繁忙，请稍后重试”

查看两类日志：

- `runtime/server/codexclaw.log`
- 控制台 JSON 日志中的 `event` 与 `error_code`

常见根因：

- codex CLI 未登录/不可执行
- 模型不可用
- codex 超时
- 超长任务中途长时间无输出
- `codex exec --json` 输出单行过长

重点看：

- `event=pipeline.error`
- `event=codex.stream` / `event=codex.chat`
- `error_code=CodexClientError`

如果近期问题集中在复杂任务：

- 先确认 `.env` 中 `CODEX_TIMEOUT_SECONDS` 是否已调高
- 再确认 `TASK_RUNNING_NOTICE_SECONDS` 是否符合预期
- 如果日志里出现 `chunk is longer than limit`，需要提高 `CODEX_STREAM_READ_LIMIT_BYTES`

### 10.4 `/stop` 没有终止任务

优先检查：

- 是否是同一会话发送的 `/stop`（同 `user_id + chat_id`）
- 日志里是否有 `event=pipeline.cancel`
- 当前运行中的 `codex exec` 是否已被外部回收

已知限制：

- `/stop` 只终止当前会话中的一条活动任务
- 如果任务已经自然结束，再发 `/stop` 会返回“当前没有可终止的运行中任务。”

---

## 11. 后续二开建议

1. 增加持久化存储（Redis/DB）替换内存会话与去重。
2. 支持群聊和 @ 提及策略。
3. 把 quick ack 和最终回复模板做成可配置项。
4. 增加 `/status` 命令，返回当前任务状态、已运行时长、是否已收到停止请求。
5. 增加 Prometheus 指标与健康探针细分。
6. 增加集成测试（Mock Feishu webhook + Mock codex CLI）。
