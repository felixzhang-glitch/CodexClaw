# AGENTS.md

个人 IM -> CLI 桥接服务。飞书 + 微信双通道接入，opencode 为核心后端。

## 核心规则

1. **opencode-first**：凡是 opencode 能做的事，不在 codeClaw 中实现。会话记忆、上下文压缩、工具调用、代码生成、文件操作等智能能力全部交给 opencode 原生处理。
2. **只做桥接**：codeClaw 的职责边界是——消息收发、后端路由切换、渠道适配（格式化/分段/图片上传）。不膨胀成“智能体框架”。
3. **备选后端只保留不投入**：codex / claude / qodercli 作为可切换备选，维护现有功能即可，不投入新特性开发。
4. **个人项目简洁优先**：单实例部署，文件持久化，不引入外部存储；代码改动优先验证现有测试通过。

## 代码地图

```
lib/python/
  app/            → FastAPI 入口(main)、配置(config)、命令分发(commands)、规则热加载(rules)、日志
  channel/feishu/ → 飞书渠道全链路：webhook 解析(handler)、WS 长连接(ws_client)、
                    安全校验(security)、消息回发(client)、格式化(formatting)、图片(media)
  channel/wechat/ → 微信渠道处理（接收 sidecar 转发的消息）
  core/agent/     → 多后端路由器(router) + CLI 客户端封装
                    （claude_cli 同时承载 claude/qodercli，无独立 qodercli 文件）
  core/codex/     → Codex CLI 客户端（超时/重试/熔断）
  core/session/   → 会话管理(manager)、去重(deduplicator)、任务注册(task_registry)、定时提醒(reminder_scheduler)

lib/js/
  wechat-sidecar.mjs → 微信 iLink Bot 长轮询 sidecar（Node.js）

bin/server        → 主控制脚本（start/stop/restart/status/wx login|start|stop）
bin/start(.sh)    → server 的薄包装
conf/             → .env 环境配置、requirements、pytest.ini
rules/            → 注入 opencode 的规则：AGENTS.md 公共 / admin.md 私有（gitignored）
hooks/            → inject-time.js 时间注入 hook
skills/           → opencode skills（iqs-search / lark-cli / self-admin / yfinance）
docs/             → 设计文档(design-docs)、执行计划(exec-plans)、渠道/路由/会话说明
tests/            → 单元测试
logs/ runtime/    → 运行时产物（gitignored）
```

## 后端策略

| 后端 | 定位 | 会话管理方式 |
|------|------|-------------|
| opencode (默认) | 主力后端 | 原生 `--session` 持久化，上下文由 opencode 自管 |
| codex | 备选 | codexclaw 拼接历史（FIFO N 轮） |
| claude | 备选 | 同上 |
| qodercli | 备选 | 同上 |

## 修改前看这里

| 要改什么 | 先看 |
|---------|------|
| 新增/修改命令 | `lib/python/app/commands.py` |
| 飞书消息处理逻辑 | `lib/python/channel/feishu/handler.py` |
| 微信消息处理逻辑 | `lib/python/channel/wechat/handler.py` |
| 后端路由/切换 | `lib/python/core/agent/router.py` |
| opencode 集成 | `lib/python/core/agent/opencode_cli.py` |
| 飞书 WS 长连接 | `lib/python/channel/feishu/ws_client.py` |
| 规则注入 | `lib/python/app/rules.py` + `rules/` |
| 会话/去重/任务 | `lib/python/core/session/` |
| 渠道格式化 | `lib/python/channel/feishu/formatting.py` |
| 配置项 | `lib/python/app/config.py` + `conf/.env.example` |
| 架构决策 | `docs/design-docs/` |
| 技术债 | `docs/exec-plans/tech-debt-tracker.md` |

## 开发文档
- 微信接入参考:https://docs.openclaw.ai/zh-CN/channels/wechat
- 飞书应用开发: https://open.feishu.cn/document/client-docs/bot-v3/bot-overview
