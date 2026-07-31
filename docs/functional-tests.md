# 核心功能测试清单

> 每次迭代（新功能 / 行为调整 / 缺陷修复）合入前必须对照本清单验证，避免开发改动破坏核心功能。
> 验证方式分两类：自动化（对应 `tests/` 下测试文件，跑 pytest 即覆盖）、手动冒烟（无法自动化的真实链路）。

## 核心功能项

| # | 功能 | 验证要点 | 验证方式 |
|---|------|---------|---------|
| 1 | 飞书发送文件 | 文件下载成功并归档存储到指定目录 | `tests/test_file_archive.py` |
| 2 | 飞书发送图片 | 图片下载成功并交给 CLI 处理 | `tests/test_feishu_media.py` |
| 3 | 定时任务 `/daily` | 创建 / list / cancel 解析正确；到点执行并推送（飞书 + 微信）；重启后任务恢复 | `tests/test_daily_scheduler.py` |
| 4 | 定时提醒 `/remind` | 时间解析（s/m/h/d）、到点提醒、持久化恢复 | `tests/test_reminder_scheduler.py` |
| 5 | 基础对话链路 | 飞书 WS 收文本 → Typing 回执 → 最终答案单条稳定回复 | `tests/test_feishu_ws.py`、`tests/test_handler_single_reply.py` |
| 6 | 微信文本对话 | sidecar 转发消息处理正常；webhook token 校验拒绝非法请求 | `tests/test_wechat_handler.py`、`tests/test_signature_validation.py` |
| 7 | 后端切换 | `/opencode` `/codex` `/claude` `/qodercli` 切换生效；状态持久化重启保留；切换后清空会话上下文 | 手动冒烟：切换后端 → `/backend` 确认 → 重启服务再确认 |
| 8 | 会话命令与去重 | `/new` `/reset` `/stop` 行为正确；同 `message_id` 消息不重复处理；同会话连发消息按 FIFO 排队 | `tests/test_new_command.py`、`tests/test_session_manager.py`、`tests/test_message_queue.py` |
| 9 | 回复格式化 | 超长文本智能分段（保留段落/代码块边界）；Markdown 卡片渲染失败自动降级纯文本 | `tests/test_feishu_formatting.py` |
| 10 | opencode 会话与规则 | 原生 `--session` 续接（上下文保留）；修改 `rules/AGENTS.md` 后无需重启即生效 | `tests/test_opencode_session.py` + 手动冒烟：改 rules 后发消息验证 |
| 11 | 长期记忆 memory/ | 明确要求时写入并回执（"记住…" → `已记入 memory/…`）；日常提及不写入；查看/修改/软删除可用；重启后记忆仍注入；`memory/` 不被主仓跟踪且无 remote | `tests/test_memory.py` + 手动冒烟：对话中"记住 X"验回执与文件，`git -C memory log` 验快照 |

## 迭代验收规则

1. 任何功能改动合入前必须全量测试通过：

```bash
source .venv/bin/activate
pytest -c conf/pytest.ini -q
```

2. 改动涉及上表功能项时，除自动化测试外，额外执行该项对应的手动冒烟
3. 新增核心功能时，同步在本清单追加一行（功能 + 验证要点 + 验证方式）
