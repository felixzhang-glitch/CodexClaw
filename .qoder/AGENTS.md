# AGENTS.md

个人 IM -> CLI 桥接服务。飞书 + 微信双通道接入，pi（Pi Coding Agent）为默认后端。纯harnees开发

## 设计哲学

**能力归 agent，编排归 harness。**

codeClaw 不是智能体框架，是一层刻意做薄的 harness：

- **不造智能**：会话记忆、上下文压缩、工具调用、代码生成、文件操作，全部由本机 CLI agent 原生承载，桥接层零重复实现
- **只做编排**：消息收发、渠道适配（格式化/分段/图片上传）、后端路由切换——职责边界到此为止
- **CLI-native**：pi 为默认后端（原生 `--session-id` 会话自管，参考 `docs/references/pi-cli.txt`），opencode 为主要备选；codex/claude/qodercli 作为可切换备选，只维护不投入新特性，但需关注 CLI 升级后的变化，避免 bug

判断标准很简单：一个能力如果 agent 原生支持，codeClaw 就不做。

## 核心规则

1. **个人项目简洁优先**：单实例部署，文件持久化，不引入外部存储；代码改动优先验证现有测试通过。
2. **迭代必须回归核心功能**：每次迭代完成后对照 `docs/functional-tests.md` 验证核心功能项，避免开发改动破坏已有功能。

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
  core/session/   → 会话管理(manager)、去重(deduplicator)、任务注册(task_registry)、
                    定时提醒(reminder_scheduler)、每日任务(daily_scheduler)、消息队列(message_queue)

lib/js/wechat-sidecar.mjs → 微信 iLink Bot 长轮询 sidecar（Node.js）
bin/server        → 服务控制（start/stop/restart/status/wx login|start|stop）
conf/.env.example → 全部配置项及默认值（配置绑定在 lib/python/app/config.py）
rules/            → 注入后端的规则：AGENTS.md 公共 / admin.md 私有（gitignored）；pi 走 `--append-system-prompt`，opencode 走 `instructions`
hooks/ skills/    → opencode 时间注入插件（pi 不加载，它在 prompt 首行拼时间）/ 项目级 skills
docs/index.md     → 项目文档索引（架构/渠道/路由/会话/回归清单） **重点, 不了解项目的话优先看这里**
```

> 约定：每次需求变化（新功能/行为调整/缺陷修复）完成后，在 `docs/requirement-changes.md` 顶部追加一条记录（日期 + 需求内容 + 影响范围）。

## 指令
- 每次开发完更新docs文档
- 推送github优先使用gh, 推送包括.qoder文件夹内容, 但是注意脱敏, 一般rules里面的admin.md 还有其他用户没注意到的你也要检查, 不要推送带有明显用户敏感信息的数据到github

## 开发文档
- 微信接入参考:https://docs.openclaw.ai/zh-CN/channels/wechat
- 飞书应用开发: https://open.feishu.cn/document/client-docs/bot-v3/bot-overview
