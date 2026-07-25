# 会话与任务管理

## 会话管理

### opencode 后端

opencode 走原生会话续接，codeClaw 不拼接历史：

- 会话 ID 映射：`user_id:chat_id` -> opencode session_id
- 持久化：`runtime/server/opencode-sessions.json`
- `/new`：生成新 session_id（旧 session 在 opencode 侧保留）
- `/reset`：清空映射，下次对话创建新 session
- `/compact`：透传给 opencode 原生压缩能力

### 备选后端（codex / claude / qodercli）

codeClaw 自行维护 FIFO 历史：

- 会话 Key：`user_id:chat_id`
- 每轮存储：user + assistant 一对
- 超出 `MAX_HISTORY_ROUNDS`（默认 50）时 FIFO 裁剪
- `/new`：清空历史数组
- `/reset`：清空历史数组
- `/compact`：压缩较早轮次为摘要，保留最近 2 轮原文

## 去重

- 基于 `message_id`，TTL 1 小时（`DEDUPLICATE_TTL_SECONDS`）
- 防止飞书/微信重试导致重复处理

## 任务注册

- 会话维度：同一会话同一时刻只允许一个运行中任务
- 注册信息：trace_id、message_id、启动时间、通知状态
- `/stop`：通过 trace_id 找到子进程并 kill
- Quick Ack：收到消息立即发 Typing reaction

## 定时提醒

- `/remind <time> <content>`：时间单位 s/m/h/d
- 持久化：`runtime/server/reminders.json`
- 到期后通过渠道 API 主动发送
- 重启时从文件恢复未触发的提醒

## 文件

```
lib/python/core/session/
  manager.py            → 会话存储与 FIFO 裁剪
  deduplicator.py       → message_id 去重
  task_registry.py      → 运行中任务注册与取消
  reminder_scheduler.py → 定时提醒与持久化
```
