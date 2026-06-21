# CodexClaw

飞书/微信 私聊机器人 → 本机 Codex / Claude / Qoder CLI，运行时可切换后端。

<img width="818" height="1456" alt="image" src="https://github.com/user-attachments/assets/4d78591b-1c42-44e9-a772-0c5c38921b5d" />

## 概述

CodexClaw 是一个单实例 IM → CLI 桥接服务：接收飞书或微信私聊消息，调用本机已安装的 AI CLI 后端（`codex`、`claude`、`qodercli`）处理后回传。核心设计是 **运行时多后端路由**——通过聊天命令即可切换后端，切换状态持久化，重启保留。

### 功能特性

**渠道接入**
- 飞书 Webhook 回调（URL challenge 校验 + 签名校验）
- 微信私聊（轻量 sidecar 长轮询 iLink Bot API）
- 私聊文本 + 图片消息（自动下载图片并交给 CLI）
- 群聊 @ 机器人触发（默认要求 @）

**多后端路由**
- `codex` / `claude` / `qodercli` 三后端，运行时通过 `/codex` `/claude` `/qodercli` 切换
- 状态持久化（`runtime/server/backend.json`，重启保留）
- 切换隔离：清空当前会话上下文 + claude/qodercli 使用独立工作目录

**会话与任务**
- 会话记忆（`user_id + chat_id` 维度，默认 10 轮 FIFO 裁剪）
- 消息去重（`message_id`，TTL 1 小时）
- 长任务通知（超阈值提示"仍在运行"）+ `/stop` 强制终止
- 定时提醒 `/remind 10m 内容`，支持 `s/m/h/d`

**回复体验**
- streaming 增量回传 + 快速回执（`Typing` reaction）
- 最终答案默认单条回复，超长时智能分段（保留段落与代码块边界）
- 飞书 Markdown 卡片渲染，失败自动降级为纯文本
- 自动识别 CLI 输出中的本地图片路径并上传为飞书图片消息

**工程化**
- 超时 / 重试 / 熔断（Codex 客户端）
- 结构化 JSON 日志（`trace_id` / `event` / `duration_ms` / `error_code`）
- 回复失败时按 `chat_id` 主动发送兜底
- 服务控制脚本（`start|stop|status|help`）

## 快速开始

1. 启动（默认后台）：

```bash
./bin/start
```

前台启动并打印日志：

```bash
./bin/start -f
```

2. 首次启动会提示输入 `FEISHU_APP_ID`（形如 `cli_xxx`）和 `FEISHU_APP_SECRET`，脚本自动完成：创建虚拟环境、安装依赖、写入 `conf/.env`、创建 Codex 工作目录并启动服务。

3. 常用服务命令：

```bash
./bin/server help       # 查看帮助
./bin/server status     # 查看状态
./bin/server stop       # 停止
./bin/server start -f   # 前台启动
```

> `./bin/start` 等价 `./bin/server start`，`./bin/start -f` 等价 `./bin/server start -f`。

4. 服务默认监听：

- `http://0.0.0.0:8080`
- 健康检查：`GET /healthz`
- 飞书回调：`POST /webhook/feishu`
- 微信回调：`POST /webhook/wechat`

## 渠道配置

### 飞书

应用凭证获取参考 [Feishu 渠道配置](https://docs.openclaw.ai/zh-CN/channels/feishu#3-%E8%8E%B7%E5%8F%96%E5%BA%94%E7%94%A8%E5%87%AD%E8%AF%81)。在飞书开放平台：

1. 事件订阅地址填：`https://<你的公网域名>/webhook/feishu`
2. 订阅事件：`im.message.receive_v1`
3. 开通机器人消息权限（读取、回复、主动发送 IM 文本和图片、上传图片、获取消息资源）
4. 在应用可用范围内允许私聊机器人

> 若启用验证 Token，写到 `FEISHU_VERIFICATION_TOKEN`；若启用加密 Key，写到 `FEISHU_ENCRYPT_KEY`（自动启用签名校验）。

### 微信（可选）

微信接入使用轻量 sidecar，负责扫码登录、长轮询和发送消息，CodexClaw 只暴露本地 webhook 处理文本对话。

1. 在 `conf/.env` 中配置共享 token：

```bash
WECHAT_WEBHOOK_TOKEN=请换成一段随机字符串
```

2. 启动 CodexClaw：`./bin/start`
3. 扫码登录微信 ClawBot：

```bash
./bin/server wx login
```

登录凭证保存到 `conf/wechat/account.json`（已被 `.gitignore` 忽略）。

4. 启动 sidecar：

```bash
./bin/server wx start
```

默认连接：
- CodexClaw：`http://127.0.0.1:8080/webhook/wechat`
- sidecar health：`http://127.0.0.1:8787/healthz`

> 当前微信版本支持私聊文本、语音转文字文本及全部命令；图片、文件、typing 和定时提醒后续再补。

## 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/new` | 新建会话（新 session_id，不继承旧上下文） |
| `/reset` | 清空当前会话历史 |
| `/compact` | 压缩会话上下文，保留最近 2 轮（`/compress` 同义） |
| `/stop` | 终止当前会话中正在运行的任务 |
| `/backend` | 查看当前后端及可切换列表 |
| `/codex` | 切换后端为 Codex CLI |
| `/claude` | 切换后端为 Claude Code |
| `/qodercli` | 切换后端为 Qoder CLI |
| `/skills` | 列出本机可用 skills（自然语言询问"列出所有可用 skills"同样触发） |
| `/remind 10m 喝水` | 定时提醒，时间单位支持 `s/m/h/d` |

> 后端切换成功后会清空当前会话历史，避免旧后端的工具、skills 或回答风格污染新后端。

## 配置项

默认值见 `conf/.env.example`。

**飞书**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FEISHU_APP_ID` | | 应用 ID |
| `FEISHU_APP_SECRET` | | 应用 Secret |
| `FEISHU_VERIFICATION_TOKEN` | | 验证 Token（可选） |
| `FEISHU_ENCRYPT_KEY` | | 加密 Key，配置后启用签名校验 |
| `FEISHU_BOT_OPEN_ID` | | 可选，配置后群聊只响应 @ 该 open_id |
| `FEISHU_GROUP_REQUIRE_MENTION` | `true` | 群聊是否要求 @ |
| `FEISHU_MAX_RETRIES` | `2` | OpenAPI 重试次数 |
| `FEISHU_RETRY_BACKOFF_SECONDS` | `0.5` | 重试退避 |
| `FEISHU_RECEIVED_IMAGES_DIR` | `./runtime/feishu-images` | 下载图片目录 |

**Codex 后端**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CODEX_CLI_BIN` | `codex` | codex 二进制路径 |
| `CODEX_WORK_DIR` | `./runtime/codex-workdir` | 工作目录（claude/qodercli 用其下子目录） |
| `CODEX_MODEL` | | 可空，留空用 CLI 默认模型 |
| `CODEX_PERMISSION_MODE` | `full` | 权限模式 |
| `CODEX_TIMEOUT_SECONDS` | `30` | 单次读取 stdout 超时 |
| `CODEX_STREAM_READ_LIMIT_BYTES` | `262144` | subprocess stream 读取上限 |
| `CODEX_CIRCUIT_BREAKER_THRESHOLD` | `5` | 熔断阈值 |
| `CODEX_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | `30` | 熔断冷却 |

**多后端路由**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ACTIVE_BACKEND` | `codex` | 初始后端（`codex`/`claude`/`qodercli`） |
| `BACKEND_STATE_PATH` | `./runtime/server/backend.json` | 后端状态持久化 |
| `CLAUDE_CLI_BIN` | `claude` | claude 二进制 |
| `CLAUDE_MODEL` | | 可空 |
| `CLAUDE_PERMISSION_MODE` | `auto` | root 下 `auto` 为最大权限 |
| `CLAUDE_TIMEOUT_SECONDS` | `60` | 单次请求总时长上限 |
| `QODERCLI_CLI_BIN` | `qodercli` | qodercli 二进制 |
| `QODERCLI_MODEL` | | 可空 |
| `QODERCLI_PERMISSION_MODE` | `dangerously-skip-permissions` | 权限模式 |
| `QODERCLI_TIMEOUT_SECONDS` | `60` | 单次请求总时长上限 |

**运行行为**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MAX_HISTORY_ROUNDS` | `10` | 会话记忆轮数 |
| `STREAMING_ENABLED` | `true` | 是否流式获取 |
| `TASK_RUNNING_NOTICE_SECONDS` | `30` | 长任务通知阈值 |
| `FEISHU_MESSAGE_CHUNK_CHARS` | `1500` | 飞书文本分段长度 |
| `WECHAT_WEBHOOK_TOKEN` | | 微信 webhook 共享 token |
| `WECHAT_MESSAGE_CHUNK_CHARS` | `1800` | 微信文本分段长度 |
| `DEDUPLICATE_TTL_SECONDS` | `3600` | 去重 TTL |
| `REMINDER_STORE_PATH` | `./runtime/server/reminders.json` | 提醒持久化文件 |

**服务与日志**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `SERVER_HOST` | `0.0.0.0` | 监听地址 |
| `SERVER_PORT` | `8080` | 监听端口 |
| `LOG_LEVEL` | `INFO` | 日志级别 |

> 兼容字段（CLI 模式默认不用）：`CODEX_API_BASE`、`CODEX_API_KEY`。

## 项目结构

```text
bin/
  server              # 服务控制（start|stop|status|help|wx）
  start               # 快捷入口（默认后台，-f 前台）
conf/
  .env.example        # 示例配置
  pytest.ini
  requirements.txt
lib/python/
  app/                # config / commands / logging / main(FastAPI)
  channel/feishu/     # models / security / client / handler / formatting / media
  channel/wechat/     # handler
  core/agent/         # router(多后端路由) / claude_cli
  core/codex/         # client(Codex CLI 封装)
  core/session/       # manager / deduplicator / task_registry / reminder_scheduler
lib/js/
  wechat-sidecar.mjs  # 微信 sidecar
md/
tests/
```

## 运行测试

```bash
source .venv/bin/activate
pytest -c conf/pytest.ini -q
```

覆盖：消息解析、签名校验、会话裁剪、`/new` 行为、Codex streaming mock、quick ack + 单条回复、长任务通知、`/stop` 取消。

## 日志与排障

日志为结构化 JSON，核心字段：`trace_id` / `event` / `duration_ms` / `status_code` / `error_code`。日志文件：`logs/codexclaw.log`。

常见错误：

| 错误 | 排查方向 |
|------|---------|
| `invalid feishu signature` | `FEISHU_ENCRYPT_KEY` 与平台不一致 |
| `verification token mismatch` | `FEISHU_VERIFICATION_TOKEN` 不一致 |
| `failed to fetch tenant access token` | `App ID/Secret` 无效或权限不足 |
| `codex cli failed` | 本机 `codex` 未登录或不可执行，检查 `codex login` |
| `codex cli timeout` | 调大 `CODEX_TIMEOUT_SECONDS` |
| `chunk is longer than limit` | 调大 `CODEX_STREAM_READ_LIMIT_BYTES` |
| `/stop` 未终止任务 | 确认同一会话发送；查日志 `event=pipeline.cancel` |

关键日志事件：`pipeline.error`、`codex.stream` / `codex.chat`、`error_code=CodexClientError`。
# CodexClaw (Feishu/WeChat + Multi-Backend)

一个单实例可运行服务：接收 Feishu 或 WeChat 私聊文本消息，调用本机 CLI 后端（`codex`、`claude`、`qodercli`）处理后回传，支持 streaming 汇总回复和运行时全局后端切换。

<img width="818" height="1456" alt="image" src="https://github.com/user-attachments/assets/4d78591b-1c42-44e9-a772-0c5c38921b5d" />


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
- 多后端路由：支持 `codex`、`claude`、`qodercli` 三个 CLI 后端，运行时通过命令切换
- 后端状态持久化：切换后重启保留选择（`runtime/server/backend.json`）
- 后端切换隔离：切换成功后清空当前会话上下文，`claude`/`qodercli` 使用独立工作目录避免工具状态串扰
- streaming 增量回传 Feishu
- 收到消息后先快速回执：消息 reaction（`emoji_type=Typing`）
- 最终答案默认单条回复（避免分段刷屏）
- Feishu 文本回复默认使用 Markdown 卡片渲染，失败时自动降级为普通文本
- 会话记忆（`user_id + chat_id` 维度，默认 10 轮 FIFO 裁剪）
- 命令支持：`/new`、`/reset`、`/compact`、`/help`
- 本机 skills 清单命令：`/skills` 或自然语言询问“列出所有可用 skills”时直接扫描 `SKILL.md` 返回
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
  core/agent/
    router.py
    claude_cli.py
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

当前 WeChat 版本先支持私聊文本、语音转文字文本、`/new`、`/reset`、`/compact`、`/help`、`/stop`、`/backend`、`/codex`、`/claude`、`/qodercli`、`/skills`。图片、文件、typing 和定时提醒后续再补。

## 命令说明

- `/help`：显示帮助
- `/new`：开启新会话（新 session_id，不继承旧上下文）
- `/reset`：清空当前会话历史
- `/compact`：压缩当前会话上下文，保留最近 2 轮；`/compress` 同义
- `/stop`：终止当前会话中正在运行的任务
- `/backend`：查看当前后端及可切换列表
- `/codex`：切换后端为 Codex CLI
- `/claude`：切换后端为 Claude Code
- `/qodercli`：切换后端为 Qoder CLI
- 后端切换成功后会清空当前会话历史，避免旧后端的工具、skills 或回答风格污染新后端
- `/skills`：列出本机可用 skills；自然语言询问“列出所有可用 skills”也会直接返回该清单
- `/remind 10m 喝水`：10 分钟后主动发送”喝水”；时间单位支持 `s/m/h/d`

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
- `CODEX_WORK_DIR=./runtime/codex-workdir`（`codex` 直接使用该目录；`claude`、`qodercli` 分别使用其下的 `claude/`、`qodercli/` 子目录）
- `CODEX_MODEL`（可空，留空时使用 codex CLI 默认模型）
- `CODEX_PERMISSION_MODE=full`
- `CODEX_TIMEOUT_SECONDS=30`
- `CODEX_STREAM_READ_LIMIT_BYTES=262144`
- `CODEX_CIRCUIT_BREAKER_THRESHOLD=5`
- `CODEX_CIRCUIT_BREAKER_COOLDOWN_SECONDS=30`
- `ACTIVE_BACKEND=codex`（默认后端，可选 `codex`/`claude`/`qodercli`）
- `BACKEND_STATE_PATH=./runtime/server/backend.json`
- `CLAUDE_CLI_BIN=claude`
- `CLAUDE_MODEL`（可空）
- `CLAUDE_PERMISSION_MODE=auto`（root 下 claude 不支持 bypass，`auto` 为最大权限模式）
- `CLAUDE_TIMEOUT_SECONDS=60`（Claude Code 单次请求总时长上限）
- `QODERCLI_CLI_BIN=qodercli`
- `QODERCLI_MODEL`（可空）
- `QODERCLI_PERMISSION_MODE=dangerously-skip-permissions`
- `QODERCLI_TIMEOUT_SECONDS=60`（Qoder CLI 单次请求总时长上限）
- `MAX_HISTORY_ROUNDS=10`
- `STREAMING_ENABLED=true`
- `TASK_RUNNING_NOTICE_SECONDS=30`
- `FEISHU_MESSAGE_CHUNK_CHARS=1500`
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
