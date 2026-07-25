# 渠道接入

## 飞书

### 架构

```
飞书开放平台 → HTTPS POST /webhook/feishu → FastAPI → FeishuWebhookHandler
                                                              ↓
                                                    签名校验 → 事件解析 → 命令/消息分发
                                                              ↓
                                                    AgentRouter → 回复（Markdown 卡片 / 图片）
```

### 关键实现

- **安全校验**：支持 Verification Token 校验 + Encrypt Key 签名校验（AES-CBC 解密）
- **消息类型**：私聊文本 + 图片；群聊 @ 触发（`FEISHU_GROUP_REQUIRE_MENTION`）
- **回复格式**：Markdown 卡片渲染，失败自动降级纯文本；超长文本智能分段（保留代码块/段落边界）
- **图片处理**：接收图片（下载到本地交给后端）+ 发送图片（识别 CLI 输出中的本地路径自动上传）
- **Quick Ack**：收到消息立即发 Typing reaction，最终答案汇总后单条回复

### 文件

```
lib/python/channel/feishu/
  handler.py     → 主处理流程
  client.py      → OpenAPI 调用（token/reply/send/image/reaction）
  security.py    → 签名校验与解密
  formatting.py  → Markdown 格式化与分段
  media.py       → 图片下载/上传/路径识别
  models.py      → 事件解析模型
```

---

## 微信

### 架构

```
iLink Bot API ← 长轮询 ← wechat-sidecar.mjs (Node.js)
                                    ↓
                        POST /webhook/wechat (本地 HTTP)
                                    ↓
                        WechatWebhookHandler → AgentRouter → 文本回复
                                    ↓
                        POST iLink Bot 发送接口 ← sidecar 代发
```

### 关键实现

- **Sidecar 模式**：wechat-sidecar.mjs 独立进程，负责扫码登录、长轮询、发送消息
- **共享 Token**：sidecar 与 codeClaw 间通过 `WECHAT_WEBHOOK_TOKEN` 做简单鉴权
- **消息类型**：私聊文本 + 语音转文字（当前版本）
- **限制**：暂不支持图片/文件、typing 回执、长任务通知、定时提醒通知

### 文件

```
lib/js/wechat-sidecar.mjs          → sidecar 主程序
lib/python/channel/wechat/handler.py → webhook 处理
```
