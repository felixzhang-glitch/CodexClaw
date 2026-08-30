## 飞书机器人开放平台

- 类型：外部 API
- 用途：飞书渠道接入（WS 长连接 + webhook / 回调解密 / 消息回发 / 图片上传），代码在 `lib/python/channel/feishu/`
- 文档链接：https://open.feishu.cn/document/client-docs/bot-v3/bot-overview
- 版本：bot v3 / lark-oapi>=1.3.0

### 关键用法

- 回调验签与 AES-CBC 解密：`lib/python/channel/feishu/security.py`
- 消息格式化与卡片降级：`lib/python/channel/feishu/formatting.py`
- 凭证在 `conf/.env`（FEISHU_APP_ID / FEISHU_APP_SECRET 等，不入库）

### 来源

- 项目既有接入经验整理，2026-08-30
