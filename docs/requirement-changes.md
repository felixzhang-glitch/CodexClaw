# 需求变更记录

> 本文件稳定维护：每次需求变化（新功能、行为调整、架构决策变更）在此追加一条记录。
> 格式：日期 + 版本/提交 + 需求内容 + 影响范围。新记录添加在最上方。

## 2026-08-19 · pi 升级 0.84.2 + 1M 上下文与 80% 压缩阈值

- **需求**：把 pi 升到最新稳定版，并把上下文窗口拉到 1M、自动压缩阈值改为窗口的 80%
- **pi 升级**：`npm install -g @earendil-works/pi-coding-agent@0.84.2`（0.83.0 → 0.84.2）。`engines: node >=22.19.0`，`/root/.local/bin/pi` wrapper 钉的 v22.23.2 满足，wrapper 未动
- **0.84.0 breaking change 已排查并实测**：`message_update` 改为只发 `assistantMessageEvent` delta、移除累积 `message` 与 `partial`。codeClaw 不受影响，因为 `pi_cli.py` 本来只读 `assistantMessageEvent.text_delta.delta` 与权威的 `message_end.message`。实测 0.84.2 输出：`message_update` 中带累积 `message` 的为 0 个，`text_delta` 在场，用 codeClaw 的解析器直接回放能拼出正确回复
- **1M 上下文**：`~/.pi/agent/models.json` 与 `conf/pi/models.json.example` 的模型条目补 `contextWindow: 1000000` / `maxTokens: 16384`。依据：百炼公告 DeepSeek-V4-Flash-0731「原生 1M 超长上下文，最大输出 384K」；官方 API 文档说 `max_tokens` 与 `thinking_budget` 合计上限 393,216。`maxTokens` 取 16384 = pi 旧隐式默认值，行为零变化，只为防止未来 pi 改默认值时静默漂移。`--list-models` 已从 128K 变为 1M
- **80% 压缩**：`~/.pi/agent/settings.json` 新增 `compaction: {enabled: true, reserveTokens: 200000, keepRecentTokens: 150000}`，仓内新模板 `conf/pi/settings.json.example`。pi 的公式是 `contextTokens > contextWindow - reserveTokens` → `1000000-200000 = 800000`（窗口 80%）。`keepRecentTokens` 从默认 20000 抬到 150000，因为那套默认是按 128K 窗口调的，搭 1M 会变成“压一次只剩 20k”。摘要输出预算 `min(0.8×reserveTokens, maxTokens) = 16384`，与现状一致
- **压缩机制已摸清**（写进 `docs/references/pi-cli.txt` 新增的“上下文自动压缩”一节）：两个触发点在 `AgentSession` 核心（`agent_end` 之后 + 发新 prompt 之前的 pre-prompt check），与运行模式无关，`--mode json` 同样生效；另有 overflow 分支会先压缩再重试。历史实测：微信主会话在 128K 窗口下以 111,616 为阈值触发过 2 次（2026-08-07 tokensBefore=112641、2026-08-14 111738），阈值公式已被真实数据验证
- **验证**：`pi --version` = 0.84.2；`--list-models` 显示 1M / 16.4K；新会话 json 冲烟（delta + message_end 形状与 0.83.0 一致）；0.83.0 写入的存量会话能被 0.84.2 恢复（用 timecheck:1 测试会话，stderr 无 creating a new session，cacheRead=1024）；无效 API key 仍 `EXIT=0` + `stopReason=error` + 401 errorMessage（退出码陷阱在 0.84.2 依旧）；`pytest -q --ignore=tests/test_feishu_ws.py` 188 passed
- 影响：`~/.pi/agent/models.json`、`~/.pi/agent/settings.json`（均已备份 `.bak.20260819`）、`conf/pi/models.json.example`、`conf/pi/settings.json.example`（新增）、`docs/references/pi-cli.txt`、`tests/test_pi_session.py` 与 `tests/test_pi_chain.py` 的版本标注。**无 codeClaw 代码改动，不改 `conf/.env`，不需 supervisorctl 重启**（models.json / settings.json 由每轮新起的 pi 进程读取）
- **成本注意**：阈值从 111,616 提到 800,000 后，微信主会话（当前约 100k tokens/轮）会继续长到约 8 倍才压缩；按百炼 ¥1/百万 input tokens、缓存未命中估算，单轮 input 成本上限从约 ¥0.1 升到约 ¥0.8。需要限制开销时调高 `reserveTokens` 即可
- **遗留**：`/compact` 对 pi 后端仍是空操作（它压的是 codeClaw 自己的 rounds，而 pi 路径只发最后一条用户消息），真要清上下文用 `/new` 或 `/reset`；本次未修，已记入 pi-cli.txt

## 2026-08-07 · 新增 pre-push 密钥扫描钩子

- **需求**：仓库是 public repo，需要一道 `git push` 前的自动闸门，防止 AK/SK、API Key、Token、私钥等敏感信息随代码推上 GitHub（尤其是模型生成内容的误提交）
- **实现**：`.qoder/hooks/secret_scan.py`（Python 3 标准库，零依赖）+ `.qoder/hooks/pre-push`（解析 git 传入的 ref，算出待推送区间），`install.sh` 把它挂到 `.git/hooks/pre-push`
- **扫描策略**：只扫本次待推送 commit 的**新增行**（`git diff --unified=0`），命中即 exit 1 硬阻断；fail-closed（扫描器异常退出、python3 缺失也阻断）；逆转开关 `SKIP_SECRET_SCAN=1 git push`
- **挂载方式**：刻意**不改 `git config core.hooksPath`**，而是在 `.git/hooks/pre-push` 写一个转发脚本。原因：`.git/hooks/post-commit`（Qoder AI tracker）已在使用，改 hooksPath 会让它静默失效
- **规则覆盖**：AWS/Azure/阿里云/腾讯云/火山、OpenAI/Anthropic/DashScope/智谱/Google/HF、GitHub/GitLab/npm/PyPI、飞书（app id / tenant token / 机器人 webhook）/微信/钉钉/Slack、Notion/Stripe/SendGrid/Twilio/Telegram、PRIVATE KEY 块 / JWT / 带口令连接串 / `Authorization: Bearer`、项目专属环境变量（`FEISHU_APP_SECRET` 等六个）、危险文件名（`.env`、`*.pem`、`id_rsa*`、`conf/wechat/account.json`、`rules/admin.md` 等）
- **降噪关键决策**：香农熵**不做独立规则**，仅用于关键字类弱规则命中后的二次确认（否则 lockfile 哈希/UUID 大面积误报）；含非 ASCII 字符的值一律当占位符（实测修正了 `README.md` 里 `WECHAT_WEBHOOK_TOKEN=请换成一段随机字符串` 的误报）；标识符/路径/版本号形态放行；三种白名单条目（`path:` / `regex:` / `fingerprint:`）+ 行尾 `secret-scan: ignore`
- **入库**：`.gitignore` 新增 `!.qoder/hooks/` 白名单（否则 `.qoder/*` 会让钩子无法随仓库分发）；个人白名单 `secret-allowlist.local.txt` 保持 gitignored
- 影响：`.qoder/hooks/`（新增）、`.gitignore`、`docs/index.md`、`tests/test_secret_scan.py`（新增 51 个用例）、`.git/hooks/pre-push`（本机，不入库，克隆后需自行跑 `bash .qoder/hooks/install.sh`）。无服务端改动，不需重启

## 2026-08-04 · v0.6.0 后续补丁 · pi 推理强度 reasoning_effort 可调

- **问题**：pi 的 models.json 里 `compat.supportsReasoningEffort: false`（初次接 pi 时的保守设置）会把 `reasoning_effort` 从每次请求剥掉，叠加 `PI_THINKING=` 空，pi 一个 effort 值都不下发。注：deepseek-v4-flash-0731 服务端默认思考模式即 `high`，所以此前实际仍在 high 档跑，本次是把档位变显式且可调，并解锁 `xhigh`/`max`
- **pi 改动**：`~/.pi/agent/models.json` 与 `conf/pi/models.json.example` 的 `supportsReasoningEffort` 翻为 `true`；`PI_THINKING` 默认值 `"" → "high"`（config.py + conf/.env + .env.example）。取值 `off/minimal/low/medium/high/xhigh/max`，百炼实际两档（low/medium/high→high，xhigh/max→max）
- **opencode**：线上 `~/.config/opencode/opencode.jsonc` 已含 `reasoningEffort: high`（v0.6.0 前的 8e73344 已做），本次仅补仓内模板 `conf/opencode/opencode.jsonc.example` 防重建丢失，无行为变化
- 影响：`lib/python/app/config.py`、`conf/.env*`、`conf/pi/models.json.example`、`conf/opencode/opencode.jsonc.example`（新增）、`docs/references/{pi-cli,opencode-cli}.txt`、`~/.pi/agent/models.json`；上线靠 `supervisorctl restart codeclaw-stack:codeclaw`

## 2026-08-04 · v0.6.0 · 新增 pi 后端并设为默认

- **需求**：新增 pi（Pi Coding Agent 0.83.0）作为第 5 个可切换后端并设为默认，模型走阿里云百炼；skills / 记忆 / 规则等现有能力不受影响
- **集成方式**：`pi --mode json`（每轮一个短进程，与 `opencode_cli.py` 同构，复用重试/熔断/idle 超时/进程组 kill）。选它而不选 `--mode rpc` 是因为 rpc 需要进程池 + 请求响应关联且一进程只能一个 active session；也没用 pi 的 TypeScript SDK（需新增 Node sidecar，而 SDK 的两项独家能力——进程内定义 tool、虚拟内存态 AGENTS.md——对本项目价值为 0）
- **会话管理**：pi 的 `--session-id` 接受任意 ID 并按需创建，所以 session ID **由 codeClaw 生成**（uuid4 hex）并持久化到 `runtime/server/pi-sessions.json`，不需要像 opencode 那样从事件流反解；首轮（skills 摘要 preamble）改用“映射是否新建”判定，而不是 `session_id is None`
- **规则与记忆注入**：复用现有链路，`app/memory.py` 零改动。pi 侧走 `--append-system-prompt <path>`（实测会读文件内容），指向 `rules/AGENTS.md` / `rules/admin.md` / `runtime/server/memory-context.md`，等价于 opencode 的 `instructions[]`；写入协议仍每轮在场
- **事件解析**：pi 是原生 delta，删掉了 opencode 那套按 `part.id` 算增量的逻辑；三个已实测验证的陷阱：① `--mode json` **退出码恒为 0**（认证失败也是 0），成败只能看 `message_end.message.stopReason` 与 `errorMessage`；② `message_end` 对 user 轮也会发，必须判 `role == "assistant"`，否则会把用户提问当回复回显；③ `thinking_delta` / `toolcall_delta` 一律丢弃，思考不进回复
- **时间注入**：pi 不加载 opencode 插件，`hooks/inject-time.js` 的等价物改为 `PiCliClient._time_context()` 在 prompt 首行拼 `<system-context>`（fail-open）
- **百炼 provider**：`~/.pi/agent/models.json` 新增 `bailian`（`https://dashscope.aliyuncs.com/compatible-mode/v1` + `openai-completions` + `compat.supportsDeveloperRole/supportsReasoningEffort: false`），模型 `deepseek-v4-flash-0731`；apiKey 用 `"$DASHSCOPE_API_KEY"` 环境插值，密钥只落 gitignored 的 `conf/.env`，不用 `--api-key`（避免进 `ps`）；仓内模板 `conf/pi/models.json.example`
- **supervisor 相关**：`PI_CLI_BIN` 必须给绝对路径（`bin/run-app` 的 PATH 不含 `/root/.local/bin`，且里面 node 是 v20.19.4 低于 pi 要求的 22.19，靠 `/root/.local/bin/pi` wrapper 钉住 v22.23.2）；spawn 沿用 `stdin=DEVNULL`（supervisor 的 stdin 是永不关闭的 pipe，而 pi 会把管道 stdin 并入首条 prompt）+ `start_new_session=True` + `os.killpg`
- **默认切换**：`ACTIVE_BACKEND=pi` 与 `runtime/server/backend.json` 两处都要改（后者优先级更高）；上线靠 `supervisorctl restart codeclaw-stack:codeclaw`；回退一句 `/opencode`
- **成败判定（last-wins）**：因为退出码不可信，一轮的成败以**最后一条 assistant `message_end` 的 `stopReason`** 为准：它是 `error` / `aborted` 就抛 `CodexClientError`，即使已经流出了部分文本（否则被截断的回答会当完整回答发给用户）。反之，pi 在单个进程内会 auto-retry，**中间尝试失败后重试成功不算失败**，所以不能用“出现任何错误事件就抛”这种写法
- **config 新增**：`PI_CLI_BIN/PI_MODEL/DASHSCOPE_API_KEY/PI_THINKING/PI_TOOLS/PI_CODING_AGENT_DIR/PI_OFFLINE/PI_APPROVE_PROJECT/PI_TIMEOUT_SECONDS/PI_IDLE_TIMEOUT_SECONDS/PI_SESSION_STORE_PATH`
- 新增 28 个测试（`tests/test_pi_chain.py` 5 + `tests/test_pi_session.py` 23），全量 149 passed
- 影响：`core/agent/pi_cli.py`（新增）、`core/agent/router.py`、`app/config.py`、`app/commands.py`、`conf/.env*`、`conf/pi/models.json.example`（新增）、`docs/references/pi-cli.txt`（新增）、`docs/{index,routing,architecture,sessions,functional-tests,core-beliefs}.md`、`README.md`、`.qoder/AGENTS.md`、`~/.pi/agent/models.json`

## 2026-07-31 · v0.5.0 · 长期记忆（memory/）

- **需求**：仅在用户明确要求时记录的长期记忆；类别由 conf 配置；markdown 存放可人工审查增删改查；禁止推送 github
- **三层记忆分工**：`rules/AGENTS.md`（人格，仅人工）/ `rules/admin.md`（权威静态事实，仅人工）/ `memory/*.md`（动态事实，agent 可写）；admin.md 中体重/偏好/投资等动态事实迁入 memory/，消除双源矛盾
- **写入机制**：纯自然语言触发（"记住/记一下"），由 agent 按 `skills/memory/SKILL.md` 规范自行读写；时序事实追加保留趋势、状态事实覆盖、软删除归档、写后必回执；Python 侧不参与写入
- **注入机制**：`app/memory.py` 渲染「写入协议 + 常驻类别全文 + 非常驻索引」到 `runtime/server/memory-context.md`；opencode 走 `instructions` 追加（协议须每轮在场，preamble 仅首轮不可用），claude/qodercli 走 `load_system_rules()` 追加；`MEMORY_MAX_INJECT_CHARS` 只约束记忆内容，协议始终完整
- **防误写与保密**：记忆内容受本地快照仓保护（git dir 在 `runtime/memory-git`，无 remote，物理上不可推送），每轮自动快照；主仓 `.gitignore` 排除记忆内容，仅 `memory/README.md` 占位入库
- **config 新增**：`MEMORY_ENABLED/DIR/CATEGORIES/ALWAYS_INJECT/MAX_INJECT_CHARS/GIT_AUTO_COMMIT/GIT_DIR/CONTEXT_PATH`
- 新增 16 个测试，全量 111 passed
- 影响：`app/memory.py`（新增）、`app/config.py`、`app/rules.py`、`app/main.py`、`core/agent/opencode_cli.py`、`skills/memory/`、`rules/admin.md`、`docs/memory.md`（新增）、`.gitignore`、`conf/.env*`

## 2026-07-27 · 项目定位更新：GitHub About + README 重写

- GitHub About 更新为：「Harness 范式的工程落地：核心能力交给 opencode，codeClaw 收敛为接入层 + 后端路由」
- README 重写：新增设计哲学章节（能力归 agent，编排归 harness）；补全遗漏功能（`/daily`、文件归档 `FILE_ARCHIVE_DIR`、消息队列）；配置表精简为常改项；项目结构与 docs 单层目录同步；312 行 → 230 行
- 影响：README.md、GitHub 仓库描述，无代码变更

## 2026-07-27 · 文档整理：docs 拍平 + AGENTS.md 精简

- docs 拍平为单层目录，统一小写连字符命名：`ARCHITECTURE/CHANNELS/ROUTING/SESSIONS/FUNCTIONAL-TESTS` → 小写；`design-docs/` 下文件全部迁出后移除该目录
- `routing.md` 合并原 `design-docs/backend-routing.md` 的设计决策章节，机制与决策一处看全
- 新增 `docs/index.md` 总索引（取代原 design-docs/index.md）
- 删除：`architecture.drawio`、`architecture.svg`（零引用孤儿文件）、`tech-debt-tracker.md`（技术债追踪机制废弃）
- `.qoder/AGENTS.md` 精简为纯地图：删除后端策略表，文档引用统一指向 `docs/index.md`，约定路径同步新位置
- 影响：`docs/`、`.qoder/AGENTS.md`，无代码变更

## 2026-07-27 · 文档调整：移除 exec-plans + 新增核心功能测试清单

- 删除 `docs/exec-plans/` 目录（active/completed 均为空），`tech-debt-tracker.md` 迁移至 `docs/design-docs/`
- 新增 `docs/FUNCTIONAL-TESTS.md`：10 项核心功能回归清单（文件归档、图片、/daily、/remind、对话链路、微信、后端切换、会话命令/去重、格式化、opencode 会话/规则），每项映射自动化测试或手动冒烟步骤
- `.qoder/AGENTS.md` 新增核心规则：每次迭代完成必须对照清单回归验证；同步更新技术债路径引用
- 影响：`docs/`、`.qoder/AGENTS.md`，无代码变更

## 2026-07-26 · 缺陷修复：opencode 规则（含 admin.md）不加载

- **根因**：`asyncio.create_subprocess_exec(cwd=...)` 只改子进程 cwd，不更新继承的 `$PWD`；opencode 依据 `$PWD` 绑定会话项目目录，导致所有会话绑到项目根（无 AGENTS.md），整份规则丢失（不只 admin.md）
- **修复**：
  - spawn 时显式 `env["PWD"] = work_dir`，会话正确绑定 `runtime/codex-workdir/opencode`
  - 规则加载改用 opencode 原生 `instructions` 配置（`OPENCODE_CONFIG_CONTENT`），直指 `rules/AGENTS.md` + `rules/admin.md` 源文件：admin.md 不落盘拷贝、改完即生效、对已绑错目录的旧会话同样生效
  - 移除 `_sync_agents_md` 工作目录同步及 `_build_prompt` 中的规则重复注入
- 影响：`core/agent/opencode_cli.py`、`tests/test_opencode_session.py`、README

## 2026-07-26 · v0.4.0 · 每日定时简报 + 消息顺序队列

- **每日定时简报（飞书+微信）**：`/daily HH:MM 提示词` 创建、`/daily list` 查看、`/daily cancel <id>` 取消
  - 新增 `DailyTaskScheduler`（`core/session/daily_scheduler.py`）：每任务一个 asyncio 循环，JSON 原子写持久化（`runtime/server/daily-tasks.json`），重启后 6 小时窗口内补偿执行，失败重试 1 次后推送失败通知
  - 执行走 `chat(prompt, session_key=daily:{task_id}:{日期})`，每天新会话；飞书推送 send_markdown 降级 send_text，微信推送 POST sidecar `/send`
  - config 新增 `WECHAT_SIDECAR_BASE_URL`、`DAILY_TASK_STORE_PATH`
- **消息顺序队列（per-session FIFO）**：新增 `SessionMessageQueue`（`core/session/message_queue.py`），修复同会话连发多条只处理第 1 条的问题
  - 飞书队列上限 10，排队回复「已排队，前面还有 N 条」；微信上限 3，hold webhook 至任务完成
  - `/stop` 升级：终止当前任务 + 清空队列（回复附清空条数，被清消息回「已被 /stop 清出队列」）；命令不入队直接响应
- **微信 sidecar token 持久化**：contextTokens 落盘 `runtime/wechat/context_tokens.json`，重启后主动推送仍可用（已知限制：token 可能有时效）
- 新增 17 个测试，全量 97 passed
- 影响：`core/session/`、`app/commands.py`、`app/config.py`、`app/main.py`、两渠道 handler、`wechat-sidecar.mjs`

## 2026-07-26 · v0.4.0 · supervisor 接管 + 稳定性修复

- **运维需求：接入 supervisor 进程管理**
  - 新增 `bin/run-app`、`bin/run-wechat` 前台启动脚本，`/etc/supervisor/conf.d/codeclaw.conf` 管理两个服务（autorestart + 进程组级停止）
  - 原 `bin/server` 脚本保留，日常运维改用 `supervisorctl restart codeclaw-stack:*`
  - 影响：`bin/`、系统 supervisor 配置
- **缺陷修复：CLI 子进程泄漏**
  - 三个后端客户端（opencode/claude/codex）超时或取消时只杀 CLI 主进程，孙进程（如 `codex app-server`）泄漏成孤儿
  - 修复：`start_new_session=True` 独立进程组 + `os.killpg` 整组清理
  - 影响：`core/agent/opencode_cli.py`、`core/agent/claude_cli.py`、`core/codex/client.py`
- **缺陷修复：supervisor 下后端 CLI 挂死**
  - supervisor 给主进程的 stdin 是永不关闭的 pipe，CLI 子进程继承后等待输入 EOF 导致零输出超时
  - 修复：三个后端 spawn 时显式 `stdin=DEVNULL`
- **缺陷修复：微信文件收取失败**
  - iLink 实际下发结构与预期不符：下载地址在 `file_item.media.full_url`、AES 密钥为 base64 包裹的 hex、大小字段是 `len`
  - 影响：`lib/js/wechat-sidecar.mjs`

## 2026-07-26 · v0.3.0 (d760960)

- **文件收藏功能**：飞书 file/audio/media 消息归档到 `FILE_ARCHIVE_DIR`（默认 `/data/file`），回复"已收藏+绝对路径"；微信 sidecar 支持文件/视频下载 AES-128-ECB 解密落盘
- **rules 原生加载**：`rules/system.md` → `rules/AGENTS.md`，opencode 通过 `{work_dir}/AGENTS.md` 原生加载规则，移除 prompt preamble 注入；根 `AGENTS.md`（开发文档）移至 `.qoder/`

## 2026-07-25 (ca22922, 38632bc, 3423e1b, 97a4b28)

- **规则调整**：角色改为 Agent 助手，回复规则精简为"优先中文 + 禁止反问"
- **项目级定制体系**：rules 脱敏拆分（公开 `AGENTS.md` + gitignore 的 `admin.md`）、时间感知 hook（每轮注入当前时间）、提示词隔离
- **飞书长连接模式**：Webhook 之外新增 WebSocket 长连接接入；新增 yfinance skill
- **文档体系重构**：docs/ 分层（design-docs / exec-plans / references）、rules/skills 项目级加载、项目重命名为 codeClaw

## 2026-07-20 (9886812)

- **opencode 原生会话续接**：`user_id:chat_id` → opencode session_id 映射持久化，`/new` 生成新 session；移除飞书"处理中"提示

## 2026-07-07 · opencode 默认后端 (ded3f9b)

- **新增 OpenCode CLI 后端并设为默认**，确立 opencode-first 设计信念（见 core-beliefs.md）
- 各 CLI 超时从 wall-clock 改为 idle-timeout（流式输出期间不计时）

## 2026-07-05 (c488305)

- **代码审查修复**：全量修复 25 项审查问题；生成项目 Wiki 文档

## 2026-06 (c4787c1 ~ 639c1ef)

- **多后端路由**：`/codex` `/claude` `/qodercli` 运行时切换命令，后端选择状态原子写持久化；切换后清空会话隔离上下文
- **稳定性**：Claude 系 CLI wall-clock 超时与请求超时、流式 markdown 空白保留、本地 skills 确定性返回
- **飞书体验**：回复改用 Markdown 卡片渲染

## 2026-05 (3068ab0 ~ 8bce872)

- **微信渠道接入**：新增 WeChat sidecar（Node.js，iLink 协议），项目布局重组
- **飞书图片能力**：图片投递与处理改进

## 2026-03 (96766ee)

- **长任务体验**：长任务进行中提示 + `/stop` 停止支持

## 2026-02-22 · 项目启动 (7f87781)

- **初始需求**：飞书渠道 + codex-cli 后端的对话机器人（CodexClaw）
