## 微信 iLink Bot（sidecar）

- 类型：外部 API / 内部系统规则
- 用途：微信渠道接入，`lib/js/wechat-sidecar.mjs` 长轮询收消息并转发给 FastAPI，`bin/server wx login|start|stop` 管理
- 文档链接：https://docs.openclaw.ai/zh-CN/channels/wechat
- 版本：`TODO: 待补充`

### 关键用法

- webhook 转发带 token 校验，非法请求拒绝（`tests/test_signature_validation.py`）
- 主动推送走本机 sidecar 接口：`curl -X POST http://127.0.0.1:8787/send`
- 账号文件 `conf/wechat/account.json` 属敏感文件，不入库

### 来源

- 项目既有接入经验整理，2026-08-30
