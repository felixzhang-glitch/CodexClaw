# CodexClaw

飞书/微信 私聊机器人 → 本机 OpenCode / Codex / Claude / Qoder CLI，运行时可切换后端。

<img width="818" height="1456" alt="image" src="https://github.com/user-attachments/assets/4d78591b-1c42-44e9-a772-0c5c38921b5d" />

## 概述

CodexClaw 是一个单实例 IM → CLI 桥接服务：接收飞书或微信私聊消息，调用本机已安装的 AI CLI 后端（`opencode`、`codex`、`claude`、`qodercli`）处理后回传。核心设计是 **运行时多后端路由**——通过聊天命令即可切换后端，切换状态持久化，重启保留。默认后端为 `opencode`。

### 功能特性

**渠道接入**
- 飞书 Webhook 回调（URL challenge 校验 + 签名校验）
- 微信私聊（轻量 sidecar 长轮询 iLink Bot API）
- 私聊文本 + 图片消息（自动下载图片并交给 CLI）
- 群聊 @ 机器人触发（默认要求 @）

**多后端路由**
- `opencode` / `codex` / `claude` / `qodercli` 四后端，运行时通过 `/opencode` `/codex` `/claude` `/qodercli` 切换
- 状态持久化（`runtime/server/backend.json`，重启保留）
- 切换隔离：清空当前会话上下文 + claude/qodercli/opencode 使用独立工作目录

**会话与任务**
- 会话记忆（`user_id + chat_id` 维度，默认 10 轮 FIFO 裁剪）
- 消息去重（`message_id`，TTL 1 小时）
- 长任务通知（超阈值提示"仍在运行"）+ `/stop` 强制终止
- 定时提醒 `/remind 10m 内容`，支持 `s/m/h/d`

**回复体验**
- 流式获取 + 快速回执（Typing reaction），最终答案汇总后单条回复
- 最终答案默认单条回复，超长时智能分段（保留段落与代码块边界）
- 飞书 Markdown 卡片渲染，失败自动降级为纯文本
- 自动识别 CLI 输出中的本地图片路径并上传为飞书图片消息

**工程化**
- 超时 / 重试 / 熔断（Codex 客户端）
- 结构化 JSON 日志（`trace_id` / `event` / `duration_ms` / `error_code`）
- 回复失败时按 `chat_id` 主动发送兜底
- 服务控制脚本（`start|stop|restart|status|wx|help`）

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
./bin/server restart    # 重启服务
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

> 当前微信版本支持私聊文本、语音转文字文本及全部命令；图片、文件、typing、长任务通知和定时提醒后续再补。

## 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/new` | 新建会话（新 session_id，不继承旧上下文） |
| `/reset` | 清空当前会话历史 |
| `/compact` | 压缩会话上下文，保留最近 2 轮（`/compress` 同义） |
| `/stop` | 终止当前会话中正在运行的任务 |
| `/backend` | 查看当前后端及可切换列表 |
| `/opencode` | 切换后端为 OpenCode CLI（默认） |
| `/codex` | 切换后端为 Codex CLI |
| `/claude` | 切换后端为 Claude Code |
| `/qodercli` | 切换后端为 Qoder CLI |
| `/skills` | 列出本机可用 skills |
| `/remind 10m 喝水` | 定时提醒，时间单位支持 `s/m/h/d`（`/timer` 同义） |

> 后端切换成功后会清空当前会话历史，避免旧后端的工具、skills 或回答风格污染新后端。

## 配置项

默认值见 `conf/.env.example`。

**飞书**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FEISHU_APP_ID` | | 应用 ID |
| `FEISHU_APP_SECRET` | | 应用 Secret |
| `FEISHU_API_BASE` | `https://open.feishu.cn` | 飞书 API 基址 |
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
| `CODEX_GENERATED_IMAGES_DIR` | `~/.codex/generated_images` | Codex 生成图片目录（用于自动上传） |
| `CODEX_MODEL` | | 可空，留空用 CLI 默认模型 |
| `CODEX_PERMISSION_MODE` | `full` | 权限模式 |
| `CODEX_TIMEOUT_SECONDS` | `300` | 单行 stdout idle 超时（沉默 N 秒判超时） |
| `CODEX_STREAM_READ_LIMIT_BYTES` | `262144` | subprocess stream 读取上限 |
| `CODEX_MAX_RETRIES` | `2` | Codex CLI 重试次数 |
| `CODEX_RETRY_BACKOFF_SECONDS` | `1.0` | Codex CLI 重试退避 |
| `CODEX_CIRCUIT_BREAKER_THRESHOLD` | `5` | 熔断阈值 |
| `CODEX_CIRCUIT_BREAKER_COOLDOWN_SECONDS` | `30` | 熔断冷却 |

**多后端路由**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ACTIVE_BACKEND` | `opencode` | 初始后端（`opencode`/`codex`/`claude`/`qodercli`） |
| `BACKEND_STATE_PATH` | `./runtime/server/backend.json` | 后端状态持久化 |
| `OPENCODE_CLI_BIN` | `opencode` | opencode 二进制 |
| `OPENCODE_MODEL` | | 可空，形如 `provider/model` |
| `OPENCODE_AGENT` | | 可空，`opencode run --agent` |
| `OPENCODE_TIMEOUT_SECONDS` | `300` | 兼容字段（不再作为总超时使用） |
| `OPENCODE_IDLE_TIMEOUT_SECONDS` | `120` | 单行 stdout idle 超时 |
| `CLAUDE_CLI_BIN` | `claude` | claude 二进制 |
| `CLAUDE_MODEL` | | 可空 |
| `CLAUDE_PERMISSION_MODE` | `auto` | root 下 `auto` 为最大权限 |
| `CLAUDE_TIMEOUT_SECONDS` | `300` | 单行 stdout idle 超时 |
| `QODERCLI_CLI_BIN` | `qodercli` | qodercli 二进制 |
| `QODERCLI_MODEL` | | 可空 |
| `QODERCLI_PERMISSION_MODE` | `dangerously-skip-permissions` | 权限模式 |
| `QODERCLI_TIMEOUT_SECONDS` | `300` | 单行 stdout idle 超时 |

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
  core/agent/         # router(多后端路由) / claude_cli / opencode_cli
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
| `codex cli timeout` | 调大 `CODEX_TIMEOUT_SECONDS`（当前是 stdout 逐行 idle 超时，仅在流沉默时触发） |
| `chunk is longer than limit` | 调大 `CODEX_STREAM_READ_LIMIT_BYTES` |
| `/stop` 未终止任务 | 确认同一会话发送；查日志 `event=pipeline.cancel` |

关键日志事件：`pipeline.error`、`codex.stream` / `codex.chat`、`error_code=CodexClientError`。
