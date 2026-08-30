# RELIABILITY

## 可靠性目标

- 可用性目标：个人服务，无 SLA；要求重启后状态完整恢复
- 数据持久性要求：会话映射、长期记忆、定时任务 / 提醒均为文件持久化，重启不丢

## 监控与告警

- 日志：`logs/` 目录（不入库）；格式与级别约定 `TODO: 待补充`
- 健康检查：`./bin/server status`
- 告警渠道与阈值：`TODO: 待补充`（当前无告警，异常靠对话链路反馈）

## 故障处理

- 常见故障与处置：
  - 后端 CLI 报错 / 卡死：`/stop` 终止当前任务；必要时 `./bin/server restart`
  - codex 后端：客户端自带超时 / 重试 / 熔断（`lib/python/core/codex/`）
  - pi 会话异常：`/new` 或 `/reset` 清理上下文
- 回滚方式：单实例直接回退 git 版本后 `./bin/server restart`

## 运维清单

- 部署方式：本机单实例，`./bin/server start|stop|restart|status`；微信 sidecar 走 `./bin/server wx login|start|stop`
- 定时任务：应用内 `/daily` `/remind` 调度（持久化，重启恢复），无系统级 cron 依赖
- 备份与恢复演练：`TODO: 待补充`
