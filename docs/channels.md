# 渠道接入

## 飞书

### 架构

```
lark-oapi SDK (WebSocket 长连接) → FeishuWsClient → FeishuWebhookHandler.handle_event
                                                          ↓
                                               事件解析 → 命令/消息分发
                                                          ↓
                                               AgentRouter → 回复（Markdown 卡片 / 图片）
```

### 接入方式：长连接模式

使用飞书官方 Python SDK (`lark-oapi`) 建立 WebSocket 全双工通道，无需公网域名或加密策略配置。

**配置步骤**：
1. 确保 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET` 已配置
2. 启动 codeClaw 服务，SDK 自动建立长连接
3. 登录[开发者后台](https://open.feishu.cn/app) → 事件与回调 → 事件配置
4. 编辑订阅方式，选择「使用长连接接收事件」并保存
5. 添加事件 `im.message.receive_v1`（接收消息 v2.0）

**与 Webhook 模式对比**：

| | 长连接模式 | Webhook 模式（已废弃） |
|---|---|---|
| 公网域名 | 不需要 | 需要 |
| 加密/验签 | SDK 内置 | 需手动实现 |
| 防火墙/白名单 | 不需要 | 需配置 |
| 部署 | 服务器能访问公网即可 | 需暴露 8080 端口 |

**约束与限制**：
- 仅支持企业自建应用
- 事件处理需在 3 秒内完成（当前用 `asyncio.create_task` 后台处理，满足要求）
- 每个应用最多 50 个长连接
- 集群模式：多 client 部署时随机一个收到消息（不支持广播）
- 失败重推间隔：15s → 5min → 1h → 6h，最多重试 4 次

**SDK 依赖**：`lark-oapi>=1.3.0`

**参考文档**：[使用长连接接收事件](https://open.feishu.cn/document/ukTMukTMukTM/uYDNxYjL2QTM24iN0EjN/event-subscription-configure-/request-url-configuration-case)

### 关键实现

- **消息类型**：私聊文本 + 图片；群聊 @ 触发（`FEISHU_GROUP_REQUIRE_MENTION`）
- **回复格式**：Markdown 卡片渲染，失败自动降级纯文本；超长文本智能分段（保留代码块/段落边界）
- **图片处理**：接收图片（下载到本地交给后端）+ 发送图片（识别 CLI 输出中的本地路径自动上传）
- **Quick Ack**：收到消息立即发 Typing reaction，最终答案汇总后单条回复

### 文件

```
lib/python/channel/feishu/
  ws_client.py   → SDK 长连接封装（主入口）
  handler.py     → 消息处理流程
  client.py      → OpenAPI 调用（token/reply/send/image/reaction）
  security.py    → 签名校验与解密（legacy webhook 模式）
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
