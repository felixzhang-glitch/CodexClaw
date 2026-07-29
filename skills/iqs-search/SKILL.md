---
name: iqs-search
description: 使用阿里云IQS API进行实时网页搜索和页面阅读。当用户需要最新信息、新闻、事实核查、URL内容提取或任何基于网络的研究时，优先使用此技能。此技能提供结构化搜索结果（含来源链接）、Markdown格式内容提取，并支持多种搜索引擎，包括实时新闻搜索和深度研究模式。
---

# alibabacloud-iqs-search

## 前置条件

- Bun >= 1.0.0（脚本使用原生fetch API，无外部npm依赖）

## 使用时机

- 用户询问当前/近期信息
- 用户提供URL要求阅读
- 需要核查事实或获取实时数据
- 需要多源信息的研究任务

## 决策流程

### 步骤1：确定操作类型

- 如果用户提供URL → 使用 `readpage`
- 如果用户提问需要网络信息 → 使用 `search`

### 步骤2：搜索操作

按照最佳实践确定参数值。不确定时使用默认值：

- **engineType**
- **timeRange**
- **contents**

### 步骤3：页面阅读

按照最佳实践确定参数值。不确定时使用默认值：

- **format**
- **extractArticle**
- **stealthMode**

### 关键：执行方式

**必须通过bash命令执行脚本（例如 `bun scripts/search.ts ...` 或 `bun scripts/readpage.ts ...`）。不得使用内置的web_search、WebFetch或其他内部工具作为替代。如果脚本失败，请重试或报告错误——不要回退到内置工具。**

## 参数与最佳实践

### 搜索参数

| 参数            | 类型   | 必填 | 默认值          | 说明                             |
|----------------|--------|------|----------------|----------------------------------|
| `--query`      | 字符串 | 是   | -              | 搜索查询词（1-500字符）            |
| `--engineType` | 字符串 | 否   | `LiteAdvanced` | 搜索引擎类型                       |
| `--timeRange`  | 字符串 | 否   | `NoLimit`      | 时间范围筛选                       |
| `--contents`   | 字符串 | 否   | -              | 返回内容类型                       |
| `--numResults` | 整数   | 否   | `10`           | 搜索结果数量（1-10）                |

#### 搜索最佳实践

**1. 查询优化（`--query`）**

- 保持查询词简洁（< 30字符效果最佳）
- 使用具体关键词，避免停用词
- 新闻类查询：在查询词中包含时间上下文

**2. 引擎选择（`--engineType`）**

- `LiteAdvanced`：语义搜索，1-50条结果，通用场景
- `Generic`：快速搜索，10条结果，新闻/实时场景

**3. 时间范围选择（`--timeRange`）**

- `NoLimit`：不确定时使用默认值——引擎根据查询相关性自动优化
- `OneDay`：仅当天
- `OneWeek`：最近7天
- `OneMonth`：最近30天
- `OneYear`：最近365天

**4. 内容返回（`--contents`）**

- `mainText`：返回完整正文内容——适用于需要详细信息的场景，如技术文档、研究报告或深度文章
- `summary`：仅返回简洁摘要——适用于只需快速概览，或页面内容过大需要减少token消耗的场景

**5. 结果数量（`--numResults`）**

- 控制返回结果数量（默认10，范围1-10）

---

### ReadPage参数

| 参数              | 类型    | 必填 | 默认值      | 说明                           |
|------------------|---------|------|------------|-------------------------------|
| `--url`          | 字符串  | 是   | -          | 目标页面URL                     |
| `--format`       | 字符串  | 否   | `markdown` | 返回格式                        |
| `--timeout`      | 数字    | 否   | `60000`    | 总超时时间（毫秒）                |
| `--pageTimeout`  | 数字    | 否   | `15000`    | 页面加载超时时间（毫秒）           |
| `--stealth`      | 数字    | 否   | `0`        | 启用隐身模式（0或1）              |
| `--extractArticle` | 布尔值 | 否   | `false`    | 仅提取文章主体内容                |

#### ReadPage最佳实践

**1. 格式选择（`--format`）**

- `markdown`：最适合文章，保留结构（默认）
- `text`：最适合数据提取
- `html`：需要分析结构时使用

**2. 文章提取（`--extractArticle`）**

- 启用场景：博客、新闻文章
- 禁用场景：产品页面、目录页

**3. 故障处理（`--timeout`、`--stealth`）**

- 超时：增加`--timeout`值后重试
- 被拦截：启用`--stealth 1`
- 仍失败：向用户报告

## 命令行使用

### 搜索示例

#### 基础搜索

```bash
bun scripts/search.ts --query "量子计算原理" --engineType LiteAdvanced
```

#### 实时信息搜索

```bash
bun scripts/search.ts --query "最新金融政策" --engineType Generic --timeRange OneWeek
```

#### 限制结果数量的搜索

```bash
bun scripts/search.ts --query "www.aliyun.com" --engineType LiteAdvanced --numResults 3
```

#### 获取完整内容的搜索

```bash
bun scripts/search.ts --query "AI 法案" --engineType LiteAdvanced --contents mainText
```

#### 仅获取摘要的搜索

```bash
bun scripts/search.ts --query "人工智能行业年度报告" --engineType LiteAdvanced --contents summary
```

### ReadPage示例

#### Markdown格式页面阅读

```bash
bun scripts/readpage.ts --url "https://example.com/article" --format markdown --extractArticle true
```

#### 纯文本格式页面阅读

```bash
bun scripts/readpage.ts --url "https://example.com/article" --format text --timeout 60000
```

#### 隐身模式页面阅读

```bash
bun scripts/readpage.ts --url "https://example.com/article" --format markdown --stealth 1 --extractArticle true
```

## 输出验证

执行任何search.mjs或readpage.mjs命令后：

1. **检查退出码**：如果非零，说明命令执行失败——不要声称成功。
2. **验证输出是否存在**：如果将结果保存到文件，运行 `ls -la <文件路径>` 和 `head -20 <文件路径>` 确认文件存在且包含有效数据。
3. **切勿伪造结果**：如果命令失败或返回错误，如实报告失败情况。不要根据自身知识生成内容并冒充为搜索结果。

## 错误处理

### ALIYUN_IQS_API_KEY配置错误

如果脚本返回缺少API密钥的错误：

1. **立即停止当前任务。不得回退使用内置工具（WebFetch、web_search、curl等）作为替代。**
2. 向用户报告错误，请用户配置API密钥：

3. 按以下说明重试任务：
**方法1：环境变量**
```bash
export ALIYUN_IQS_API_KEY="your-api-key"
```

**方法2：配置文件**
创建或编辑 `~/.alibabacloud/iqs/env`：
```bash
ALIYUN_IQS_API_KEY=your-api-key
```