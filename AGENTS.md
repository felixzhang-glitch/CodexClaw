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
  app/            → FastAPI 入口、配置加载、命令分发、日志
  channel/feishu/ → 飞书渠道全链路（webhook 解析/安全校验/消息回发/图片处理）
  channel/wechat/ → 微信渠道处理（接收 sidecar 转发的消息）
  core/agent/     → 多后端路由器 + 各后端 CLI 客户端封装
  core/codex/     → Codex CLI 客户端（超时/重试/熔断）
  core/session/   → 会话管理、去重、任务注册、定时提醒

lib/js/
  wechat-sidecar.mjs → 微信 iLink Bot 长轮询 sidecar（Node.js）

bin/              → 服务控制脚本（start/stop/restart/status/wx）
conf/             → 环境配置、依赖、pytest
tests/            → 单元测试
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
| 会话/去重/任务 | `lib/python/core/session/` |
| 渠道格式化 | `lib/python/channel/feishu/formatting.py` |
| 配置项 | `lib/python/app/config.py` + `conf/.env.example` |
| 架构决策 | `docs/design-docs/` |
| 技术债 | `docs/exec-plans/tech-debt-tracker.md` |
