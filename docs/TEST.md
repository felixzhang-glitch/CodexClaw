# TEST

## 测试策略

- 测试层级：单元 / 链路级测试为主（`tests/` 下 pytest），外部调用（CLI 子进程、飞书 / 微信 API）一律 mock；真实链路走手动冒烟
- 运行方式：`cd conf && pytest -q`（配置在 `conf/pytest.ini`，pythonpath 指向 `lib/python`）；当前 201 用例
- 覆盖率要求：不设硬性指标，核心功能必须有用例兜底（见下表与 `docs/functional-tests.md`）

## 测试要点

1. 多渠道消息解析与签名校验必须拒绝非法输入（伪造签名、错误 token）
2. 会话隔离：不同 `user_id:chat_id` 不串会话；同 `message_id` 不重复处理；连发消息按 FIFO 排队
3. CLI 后端封装的输入输出契约稳定（pi 的 json 流、codex 的流式、claude/qodercli 的回复解析）
4. 定时任务与提醒重启后必须恢复
5. 格式化分段不破坏代码块 / 段落边界，卡片渲染失败能降级纯文本
6. 密钥扫描钩子：命中即阻断、白名单放行、异常退出 fail-closed

## 要点与用例映射

| 测试要点 | 用例路径 | 类型 |
|---|---|---|
| 飞书 WS 全链路（收消息 → Typing → 单条回复） | `tests/test_feishu_ws.py`、`tests/test_handler_single_reply.py` | 链路 |
| 飞书格式化与分段 | `tests/test_feishu_formatting.py` | 单元 |
| 飞书图片下载 | `tests/test_feishu_media.py` | 单元 |
| 飞书文件归档 | `tests/test_file_archive.py` | 单元 |
| 飞书 reaction / 回执 | `tests/test_feishu_reaction.py` | 单元 |
| 微信消息处理 | `tests/test_wechat_handler.py` | 单元 |
| 微信 webhook token 校验 | `tests/test_signature_validation.py` | 单元 |
| 消息解析 | `tests/test_message_parsing.py` | 单元 |
| 会话管理与去重 | `tests/test_session_manager.py` | 单元 |
| FIFO 消息队列 | `tests/test_message_queue.py` | 单元 |
| `/new` `/reset` `/stop` 命令 | `tests/test_new_command.py` | 单元 |
| 每日任务调度与恢复 | `tests/test_daily_scheduler.py` | 单元 |
| 定时提醒调度与恢复 | `tests/test_reminder_scheduler.py` | 单元 |
| 长期记忆读写与注入 | `tests/test_memory.py` | 单元 |
| pi 会话与调用链 | `tests/test_pi_session.py`、`tests/test_pi_chain.py` | 单元 |
| opencode 会话续接与调用链 | `tests/test_opencode_session.py`、`tests/test_opencode_chain.py` | 单元 |
| codex 流式输出 | `tests/test_codex_streaming_mock.py` | 单元 |
| claude / qodercli 客户端 | `tests/test_claude_cli.py` | 单元 |
| pre-push 密钥扫描 | `tests/test_secret_scan.py` | 单元 |

## 手工验证清单

- 后端切换（`/pi` `/opencode` `/codex` `/claude` `/qodercli`）、rules 热加载、记忆写入回执等无法自动化的场景，见 `docs/functional-tests.md` 中标"手动冒烟"的条目
- 每次迭代合入前对照 `docs/functional-tests.md` 全量过一遍
