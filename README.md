# codeClaw

> Harness 范式的工程落地：核心能力交给 opencode，codeClaw 收敛为接入层 + 后端路由

飞书/微信消息桥接到本机 AI CLI（`opencode` / `codex` / `claude` / `qodercli`），后端运行时可切换。

## 设计哲学

**能力归 agent，编排归 harness。**

codeClaw 不是智能体框架，是一层刻意做薄的 harness：

- **不造智能**：会话记忆、上下文压缩、工具调用、代码生成、文件操作，全部由本机 CLI agent 原生承载，桥接层零重复实现
- **只做编排**：消息收发、渠道适配（格式化/分段/图片上传）、后端路由切换——职责边界到此为止
- **opencode-first**：opencode 为核心后端（原生 `--session` 会话自管）；codex/claude/qodercli 作为可切换备选，只维护不投入

判断标准很简单：一个能力如果 agent 原生支持，codeClaw 就不做。

## 功能特性

**渠道接入**
- 飞书长连接（WebSocket，无需公网回调地址）
- 微信私聊（轻量 sidecar 长轮询 iLink Bot API）
- 私聊文本 / 图片（自动下载交给 CLI）/ 文件（自动归档存储）
- 群聊 @ 机器人触发

**多后端路由**
- 四后端运行时通过 `/opencode` `/codex` `/claude` `/qodercli` 切换
- 状态持久化（`runtime/server/backend.json`，重启保留）
- 切换隔离：清空会话上下文 + 各后端独立工作目录

**会话与任务**
- opencode 走原生会话续接，上下文与压缩由 opencode 自管；备选后端按轮数拼接历史
- 长期记忆 `memory/`：仅用户明确要求时写入并回执，分类 markdown 存放，常驻注入每轮在场，本地 git 快照可审查回滚（详见 [docs/memory.md](docs/memory.md)）
- 消息去重（TTL 1 小时）+ per-session FIFO 消息队列
- 定时提醒 `/remind`、每日定时简报 `/daily`（飞书 + 微信推送）
- 长任务 Typing 回执 + `/stop` 强制终止

**回复体验**
- 流式获取，最终答案单条稳定输出，超长智能分段（保留段落与代码块边界）
- 飞书 Markdown 卡片渲染，失败自动降级纯文本
- 自动识别 CLI 输出中的本地图片路径并上传

**项目级定制**
- `rules/` 提示词规则每条消息动态加载，改完即生效
- `skills/` 项目级技能实时扫描注入
- `hooks/inject-time.js` 时间感知插件（opencode）

## 快速开始

1. 启动（默认后台，`-f` 前台）：

```bash
./bin/start
```

首次启动会提示输入 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`，脚本自动创建虚拟环境、安装依赖、写入 `conf/.env` 并启动服务。

2. 服务命令：

```bash
./bin/server status     # 查看状态
./bin/server stop       # 停止
./bin/server restart    # 重启
./bin/server help       # 帮助
```

3. 默认监听 `http://0.0.0.0:8080`：

- 健康检查：`GET /healthz`
- 飞书回调：`POST /webhook/feishu`（已弃用，默认走长连接）
- 微信回调：`POST /webhook/wechat`

## 渠道配置

### 飞书

在飞书开放平台：

1. 事件订阅方式选择 **使用长连接接收事件**（无需公网回调地址）
2. 订阅事件：`im.message.receive_v1`
3. 开通机器人消息权限（读取、回复、主动发送、上传图片、获取消息资源）
4. 在应用可用范围内允许私聊机器人

### 微信（可选）

微信接入使用轻量 sidecar，负责扫码登录、长轮询和发送消息。

```bash
# 1. conf/.env 配置共享 token
WECHAT_WEBHOOK_TOKEN=请换成一段随机字符串

# 2. 扫码登录 + 启动 sidecar
./bin/server wx login
./bin/server wx start
```

登录凭证保存到 `conf/wechat/account.json`（已 gitignore）。sidecar health：`http://127.0.0.1:8787/healthz`。

> 当前微信支持私聊文本、语音转文字及全部命令；图片、文件、typing 后续再补。

## 命令

| 命令 | 说明 |
|------|------|
| `/help` | 显示帮助 |
| `/new` | 新建会话（不继承旧上下文） |
| `/reset` | 清空当前会话历史 |
| `/compact` | 压缩会话上下文（`/compress` 同义） |
| `/stop` | 终止当前任务 + 清空排队消息 |
| `/backend` | 查看当前后端及可切换列表 |
| `/opencode` `/codex` `/claude` `/qodercli` | 切换后端 |
| `/skills` | 列出本机可用 skills |
| `/remind 10m 喝水` | 定时提醒，支持 `s/m/h/d`（`/timer` 同义） |
| `/daily 08:00 AI简报` | 每日定时任务；`/daily list` 查看，`/daily cancel <id>` 取消 |

> 后端切换成功后会清空当前会话历史，避免跨后端上下文污染。

## 项目级定制

### rules（提示词规则）

| 文件 | 用途 | 提交 GitHub |
|------|------|------------|
| `rules/AGENTS.md` | 公共规则：角色、工具偏好、回复风格 | 是 |
| `rules/admin.md` | 私人信息：管理员身份、个人偏好 | 否（已 gitignore） |
| `rules/admin.md.example` | admin.md 脱敏范例 | 是 |

两个文件通过 opencode 原生 `instructions` 配置直接加载源文件，**修改后立即生效，无需重启**，对新老会话均即时生效。

```bash
cp rules/admin.md.example rules/admin.md   # 首次使用
```

### skills（项目级技能）

`skills/` 目录下每个子目录一个 `SKILL.md`，与 `~/.claude/skills`、`~/.codex/skills`、`~/.agents/skills` 一并实时扫描注入。`/skills` 命令查看识别结果。

### hooks（时间感知）

`hooks/inject-time.js` 是 opencode 插件，在每条用户消息末尾注入当前系统时间，让机器人正确理解"明天"、"刚才"。删除该文件即禁用（fail-open）。

### 提示词隔离

- 工作目录自动初始化为独立 git 仓库，阻断 agent 向上遍历读取本项目开发文件
- 注入 `OPENCODE_DISABLE_CLAUDE_CODE_PROMPT=1`，禁用 `~/.claude/CLAUDE.md` 兼容加载

## 配置项

默认值见 `conf/.env.example`，此处只列常改项。

**飞书**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | | 应用凭证（必填） |
| `FEISHU_BOT_OPEN_ID` | | 群聊只响应 @ 该 open_id |
| `FEISHU_GROUP_REQUIRE_MENTION` | `true` | 群聊是否要求 @ |
| `FEISHU_RECEIVED_IMAGES_DIR` | `./runtime/feishu-images` | 图片下载目录 |
| `FILE_ARCHIVE_DIR` | `/data/file` | 文件消息归档目录 |

**后端路由**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ACTIVE_BACKEND` | `opencode` | 初始后端 |
| `OPENCODE_CLI_BIN` | `opencode` | opencode 二进制 |
| `OPENCODE_MODEL` | | 可空，形如 `provider/model` |
| `OPENCODE_IDLE_TIMEOUT_SECONDS` | `120` | stdout idle 超时 |
| `CODEX_CLI_BIN` / `CLAUDE_CLI_BIN` / `QODERCLI_CLI_BIN` | 同名 | 备选后端二进制 |
| `CODEX_WORK_DIR` | `./runtime/codex-workdir` | 工作目录根 |
| `CODEX_TIMEOUT_SECONDS` 等 | `300` | 各后端 stdout idle 超时 |

**运行行为**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MAX_HISTORY_ROUNDS` | `50` | 备选后端历史拼接轮数（opencode 不受此限） |
| `WECHAT_WEBHOOK_TOKEN` | | 微信 webhook 共享 token |
| `WECHAT_SIDECAR_BASE_URL` | `http://127.0.0.1:8787` | sidecar 地址（主动推送用） |
| `DEDUPLICATE_TTL_SECONDS` | `3600` | 消息去重 TTL |
| `REMINDER_STORE_PATH` | `./runtime/server/reminders.json` | 提醒持久化 |
| `DAILY_TASK_STORE_PATH` | `./runtime/server/daily-tasks.json` | 每日任务持久化 |
| `SERVER_HOST` / `SERVER_PORT` | `0.0.0.0` / `8080` | 监听地址 |

## 项目结构

```text
bin/
  server              # 服务控制（start|stop|restart|status|wx）
  start               # 快捷入口（默认后台，-f 前台）
conf/                 # .env / requirements / pytest.ini
lib/python/
  app/                # FastAPI 入口、配置、命令分发、规则热加载、日志
  channel/feishu/     # 飞书全链路：handler / ws_client / security / client / formatting / media
  channel/wechat/     # 微信渠道处理
  core/agent/         # 多后端路由器 + opencode/claude CLI 客户端
  core/codex/         # Codex CLI 客户端（超时/重试/熔断）
  core/session/       # 会话 / 去重 / 任务注册 / 提醒 / 每日任务 / 消息队列
lib/js/
  wechat-sidecar.mjs  # 微信 sidecar（Node.js）
rules/                # 提示词规则（AGENTS.md 公共 / admin.md 私有）
skills/               # 项目级技能
hooks/                # inject-time.js 时间注入插件
docs/                 # 项目文档（单层目录，索引见 docs/index.md）
tests/                # 单元测试
```

## 测试

```bash
source .venv/bin/activate
pytest -c conf/pytest.ini -q
```

核心功能回归清单见 [docs/functional-tests.md](docs/functional-tests.md)：每次迭代合入前必须全量测试通过，涉及核心功能项的改动额外做手动冒烟。

## 日志与排障

结构化 JSON 日志，核心字段 `trace_id` / `event` / `duration_ms` / `error_code`，日志文件 `logs/codexclaw.log`。

| 错误 | 排查方向 |
|------|---------|
| `invalid feishu signature` | `FEISHU_ENCRYPT_KEY` 与平台不一致 |
| `failed to fetch tenant access token` | `App ID/Secret` 无效或权限不足 |
| `codex cli failed` | 本机 CLI 未登录或不可执行 |
| `codex cli timeout` | 调大对应后端 `*_TIMEOUT_SECONDS`（stdout 沉默超时） |
| `/stop` 未终止任务 | 确认同一会话发送；查日志 `event=pipeline.cancel` |

更多：架构 [docs/architecture.md](docs/architecture.md) · 渠道 [docs/channels.md](docs/channels.md) · 路由 [docs/routing.md](docs/routing.md) · 会话 [docs/sessions.md](docs/sessions.md)
