# CodexClaw (Feishu + Codex MVP)

一个单实例可运行服务：接收 Feishu 私聊文本消息，显式触发后调用本机 `codex exec`（默认 `full` 权限）处理并回传 Feishu，支持 streaming 分段回复。

默认配置面向个人 Mac mini trusted deployment。必须保留 `CODEX_ALLOWED_USER_IDS` 白名单和显式触发词，避免把 Feishu 入口变成开放的远程执行面。

## 功能覆盖

- Feishu Webhook 回调接入
- URL challenge 校验
- 签名校验（配置 `FEISHU_ENCRYPT_KEY` 后启用）
- 私聊文本消息处理（`im.message.receive_v1`）
- 群聊 @ 机器人触发处理（默认要求 @）
- Codex 显式触发：默认仅处理 `/codex ...` 或“联动 Codex ...”
- 可选用户白名单：配置 `CODEX_ALLOWED_USER_IDS` 后，仅允许指定 Feishu 用户触发 Codex
- 消息去重（`message_id`）
- Codex 统一客户端（超时、重试、错误处理、结构化日志）
- streaming 增量回传 Feishu
- 收到消息后先快速回执：消息 reaction（`emoji_type=Typing`）
- 最终答案默认单条回复（避免分段刷屏）
- 会话记忆（`user_id + chat_id` 维度，默认 10 轮 FIFO 裁剪）
- 命令支持：`/new`、`/reset`、`/compact`、`/help`
- 运行中任务支持：超过阈值自动通知“仍在运行”，并可用 `/stop` 强制终止
- 主动发送消息能力：普通回复失败时自动按 `chat_id` 兜底发送
- 定时提醒命令：`/remind 10m 内容`
- 飞书回复智能分段：优先按段落、代码块和句子边界拆分
- 自动发送 Codex 生成的本地图片（识别 `file://...png/jpg`，上传为飞书图片消息）
- 服务控制脚本：`server`（`start|stop|status|help`）
- 快捷入口：`start`（默认后台，`-f` 前台）

## 项目结构

```text
app/
  config.py
  commands.py
  logging.py
  main.py
channel/feishu/
  client.py
  handler.py
  models.py
  security.py
core/codex/
  client.py
core/session/
  manager.py
  deduplicator.py
tests/
server
start
start.sh
.env.example
```

## 5 分钟快速启动（最少操作）

1. 执行（默认后台启动）：

```bash
./start
```

或前台启动并直接打印日志：

```bash
./start -f
```

2. 首次启动会提示输入：

- `FEISHU_APP_ID`（形如 `cli_xxx`）
- `FEISHU_APP_SECRET`

脚本会自动：创建虚拟环境、安装依赖、写入 `.env`、配置 Codex 工作目录并启动服务。

3. 常用服务命令：

```bash
./server help
./server status
./server stop
./server start -f
```

`./start` 会转发到 `./server start`，`./start -f` 会转发到 `./server start -f`。

4. 服务默认监听：

- `http://0.0.0.0:8080`
- 健康检查：`GET /healthz`
- Feishu 回调：`POST /webhook/feishu`
- 默认同时启用 Feishu WebSocket 长连接；开启后无需公网回调地址即可收消息。

## Feishu 配置（一次）

应用凭证获取流程参考：

- [Feishu 渠道配置（获取应用凭证）](https://docs.openclaw.ai/zh-CN/channels/feishu#3-%E8%8E%B7%E5%8F%96%E5%BA%94%E7%94%A8%E5%87%AD%E8%AF%81)

默认推荐使用长连接模式：

1. 开通事件订阅并选择长连接。
2. 订阅事件：`im.message.receive_v1`
3. 给应用开通机器人发消息权限（读取、回复、主动发送 IM 文本和图片、上传图片）
4. 在应用可用范围内允许私聊机器人

如改用 webhook 模式，再在 Feishu 开放平台配置：

1. 事件订阅地址填：

```text
https://<你的公网域名>/webhook/feishu
```

2. 订阅事件：`im.message.receive_v1`
3. 给应用开通机器人发消息权限（读取、回复、主动发送 IM 文本和图片、上传图片）
4. 在应用可用范围内允许私聊机器人

说明：

- 若启用验证 Token，请将同值写到 `FEISHU_VERIFICATION_TOKEN`
- 若启用加密 Key，请写到 `FEISHU_ENCRYPT_KEY`（会自动启用签名校验）

## 命令说明

- `/help`：显示帮助
- `/new`：开启新会话（新 session_id，不继承旧上下文）
- `/reset`：清空当前会话历史
- `/compact`：压缩当前会话上下文，保留最近 2 轮；`/compress` 同义
- `/stop`：终止当前会话中正在运行的任务
- `/remind 10m 喝水`：10 分钟后主动发送“喝水”；时间单位支持 `s/m/h/d`
- `/codex <任务>`：显式触发 Codex 执行任务

## 配置项

默认值见 `.env.example`：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`
- `FEISHU_ENCRYPT_KEY`
- `FEISHU_BOT_OPEN_ID`（可选；配置后群聊只响应 @ 该 open_id）
- `FEISHU_GROUP_REQUIRE_MENTION=true`
- `FEISHU_WS_ENABLED=true`
- `FEISHU_MAX_RETRIES=2`
- `FEISHU_RETRY_BACKOFF_SECONDS=0.5`
- `CODEX_CLI_BIN=/Applications/Codex.app/Contents/Resources/codex`
- `CODEX_WORK_DIR=/Users/cesclaw/Desktop/All of CDOU`
- `CODEX_MODEL`（可空，留空时使用 codex CLI 默认模型）
- `CODEX_PERMISSION_MODE=full`
- `CODEX_TIMEOUT_SECONDS=30`
- `CODEX_STREAM_READ_LIMIT_BYTES=262144`
- `CODEX_CIRCUIT_BREAKER_THRESHOLD=5`
- `CODEX_CIRCUIT_BREAKER_COOLDOWN_SECONDS=30`
- `CODEX_ALLOWED_USER_IDS`（可空；逗号分隔 Feishu 用户 open_id 白名单）
- `CODEX_TRIGGER_REQUIRED=true`
- `CODEX_TRIGGER_PREFIXES=/codex,联动 Codex,联动codex,交给 Codex,让 Codex 处理`
- `MAX_HISTORY_ROUNDS=10`
- `STREAMING_ENABLED=true`
- `TASK_RUNNING_NOTICE_SECONDS=30`
- `FEISHU_MESSAGE_CHUNK_CHARS=120`
- `REMINDER_STORE_PATH=./runtime/server/reminders.json`
- `SERVER_PORT`
- `LOG_LEVEL`

兼容字段（CLI 模式默认不用）：`CODEX_API_BASE`、`CODEX_API_KEY`。

## 运行测试

```bash
source .venv/bin/activate
pytest -q
```

覆盖内容：

- 消息解析
- 签名校验
- 会话裁剪
- `/new` 行为
- Codex streaming mock

## 日志与排障

日志为结构化 JSON，包含至少：

- `trace_id`
- `event`
- `duration_ms`
- `status_code`
- `error_code`

常见错误：

- `invalid feishu signature`：签名校验失败，检查 `FEISHU_ENCRYPT_KEY`
- `verification token mismatch`：回调 token 不一致
- `failed to fetch tenant access token`：`App ID/Secret` 无效或权限不足
- `codex cli failed`：本机 `codex` 执行失败，检查 `codex login` 状态与命令可执行性
- `codex cli timeout`：Codex 执行超时，可调大 `CODEX_TIMEOUT_SECONDS`
