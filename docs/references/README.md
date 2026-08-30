## 用途

本目录维护项目需要引用的外部知识：第三方包、外部 API、内部系统规则等。供 Agent 开发时查阅，避免重复搜索。

## 条目规范

- 一个引用对象一个文件，文件名用小写短横线（如 `pi-cli.txt`、`feishu-bot-api.md`）
- 信息来源可由用户直接补充，也可让 Agent 搜索获取后写入，写入时注明来源
- 内容过期时直接更新文件，不留历史版本

## 现有条目

| 条目 | 对象 |
|---|---|
| `pi-cli.txt` | pi（Pi Coding Agent），默认后端 |
| `opencode-cli.txt` | opencode，主要备选后端 |
| `codex-cli.md` | codex，备选后端 |
| `claude-cli.md` | claude / qodercli，备选后端 |
| `feishu-bot-api.md` | 飞书机器人开放平台 |
| `wechat-ilink.md` | 微信 iLink Bot sidecar |
