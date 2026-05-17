# CodexClaw (Feishu/WeChat + Codex MVP)

一个单实例可运行服务：接收 Feishu 或 WeChat 私聊文本消息，调用本机 `codex exec`（`full` 权限）处理后回传，支持 streaming 汇总回复。

## 功能覆盖

- Feishu Webhook 回调接入
- WeChat ClawBot 文本私聊接入（通过轻量 sidecar 长轮询 iLink Bot API）
- URL challenge 校验
- 签名校验（配置 `FEISHU_ENCRYPT_KEY` 后启用）
- 私聊文本消息处理（`im.message.receive_v1`）
- 私聊图片消息处理：自动下载飞书用户发来的图片并把本地路径交给 Codex
- 群聊 @ 机器人触发处理（默认要求 @）
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
bin/
  server
  start
conf/
  .env.example
lib/python/
  app/
  config.py
  commands.py
  logging.py
  main.py
  channel/feishu/
  channel/wechat/
  core/codex/
  core/session/
lib/js/
  wechat-sidecar.mjs
logs/
md/
tests/
```

## 5 分钟快速启动（最少操作）

1. 执行（默认后台启动）：

```bash
./bin/start
```

或前台启动并直接打印日志：

```bash
./bin/start -f
```

2. 首次启动会提示输入：

- `FEISHU_APP_ID`（形如 `cli_xxx`）
- `FEISHU_APP_SECRET`

脚本会自动：创建虚拟环境、安装依赖、写入 `conf/.env`、创建独立 Codex 工作目录并启动服务。

3. 常用服务命令：

```bash
./bin/server help
./bin/server status
./bin/server stop
./bin/server start -f
```

`./bin/start` 会转发到 `./bin/server start`，`./bin/start -f` 会转发到 `./bin/server start -f`。

4. 服务默认监听：

- `http://0.0.0.0:8080`
- 健康检查：`GET /healthz`
- Feishu 回调：`POST /webhook/feishu`

## Feishu 配置（一次）

应用凭证获取流程参考：

- [Feishu 渠道配置（获取应用凭证）](https://docs.openclaw.ai/zh-CN/channels/feishu#3-%E8%8E%B7%E5%8F%96%E5%BA%94%E7%94%A8%E5%87%AD%E8%AF%81)

在 Feishu 开放平台配置：

1. 事件订阅地址填：

```text
https://<你的公网域名>/webhook/feishu
```

2. 订阅事件：`im.message.receive_v1`
3. 给应用开通机器人发消息权限（读取、回复、主动发送 IM 文本和图片、上传图片、获取消息资源）
4. 在应用可用范围内允许私聊机器人

说明：

- 若启用验证 Token，请将同值写到 `FEISHU_VERIFICATION_TOKEN`
- 若启用加密 Key，请写到 `FEISHU_ENCRYPT_KEY`（会自动启用签名校验）

## WeChat 配置（可选）

WeChat 接入使用轻量 sidecar。sidecar 负责扫码登录、`getupdates` 长轮询和 `sendmessage`，CodexClaw 只暴露本地 webhook 处理文本对话。

1. 在 `conf/.env` 中配置一个本地共享 token：

```bash
WECHAT_WEBHOOK_TOKEN=请换成一段随机字符串
```

2. 启动 CodexClaw：

```bash
./bin/start
```

3. 扫码登录微信 ClawBot：

```bash
./bin/server wx login
```

登录成功后，凭证会保存到 `conf/wechat/account.json`。该文件已被 `.gitignore` 忽略，不要提交。

4. 启动 sidecar：

```bash
./bin/server wx start
```

默认连接：

- CodexClaw: `http://127.0.0.1:8080/webhook/wechat`
- sidecar health: `http://127.0.0.1:8787/healthz`

当前 WeChat 版本先支持私聊文本、语音转文字文本、`/new`、`/reset`、`/compact`、`/help`、`/stop`。图片、文件、typing 和定时提醒后续再补。

## 命令说明

- `/help`：显示帮助
- `/new`：开启新会话（新 session_id，不继承旧上下文）
- `/reset`：清空当前会话历史
- `/compact`：压缩当前会话上下文，保留最近 2 轮；`/compress` 同义
- `/stop`：终止当前会话中正在运行的任务
- `/remind 10m 喝水`：10 分钟后主动发送“喝水”；时间单位支持 `s/m/h/d`

## 配置项

默认值见 `conf/.env.example`：

- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`
- `FEISHU_VERIFICATION_TOKEN`
- `FEISHU_ENCRYPT_KEY`
- `FEISHU_BOT_OPEN_ID`（可选；配置后群聊只响应 @ 该 open_id）
- `FEISHU_GROUP_REQUIRE_MENTION=true`
- `FEISHU_MAX_RETRIES=2`
- `FEISHU_RETRY_BACKOFF_SECONDS=0.5`
- `FEISHU_RECEIVED_IMAGES_DIR=./runtime/feishu-images`
- `CODEX_CLI_BIN=codex`
- `CODEX_WORK_DIR=./runtime/codex-workdir`
- `CODEX_MODEL`（可空，留空时使用 codex CLI 默认模型）
- `CODEX_PERMISSION_MODE=full`
- `CODEX_TIMEOUT_SECONDS=30`
- `CODEX_STREAM_READ_LIMIT_BYTES=262144`
- `CODEX_CIRCUIT_BREAKER_THRESHOLD=5`
- `CODEX_CIRCUIT_BREAKER_COOLDOWN_SECONDS=30`
- `MAX_HISTORY_ROUNDS=10`
- `STREAMING_ENABLED=true`
- `TASK_RUNNING_NOTICE_SECONDS=30`
- `FEISHU_MESSAGE_CHUNK_CHARS=120`
- `WECHAT_WEBHOOK_TOKEN`
- `WECHAT_MESSAGE_CHUNK_CHARS=1800`
- `REMINDER_STORE_PATH=./runtime/server/reminders.json`
- `SERVER_PORT`
- `LOG_LEVEL`

兼容字段（CLI 模式默认不用）：`CODEX_API_BASE`、`CODEX_API_KEY`。

## 运行测试

```bash
source .venv/bin/activate
pytest -c conf/pytest.ini -q
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
