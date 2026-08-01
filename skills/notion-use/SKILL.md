---
name: notion-use
description: 管理 Notion 笔记的增删改查（CRUD），全部通过本机 `ntn` (Notion CLI) 命令完成。当用户提到 Notion、笔记本、我的笔记、写进 Notion、查一下 Notion 里的 xxx、更新/删除某篇笔记、或给出 notion.so / app.notion.com 链接时使用。也覆盖数据库（database / data source）条目查询与页面属性修改。不负责飞书文档（走 lark-doc）。
---

# notion-use

## 定位

本文件只是**地图**：告诉你走哪条路。参数细节一律现场查，不要凭记忆猜：

- `ntn <命令> --help` — 子命令用法与示例
- `ntn api ls` — 全部可用的 Notion API 端点
- `ntn api <路径> --docs` — 某端点的官方文档
- `ntn api <路径> --spec` — 某端点的参数结构（OpenAPI 片段）

## 前置检查

已登录状态下直接用即可。若报认证错误：

```bash
ntn doctor    # 一次性体检：版本 / 配置 / workspace / token / API 连通性
ntn whoami    # 当前账号
ntn login     # 需要浏览器交互，让用户自己在会话里执行: ! ntn login
```

## ID 怎么来

Notion 链接尾部那串 32 位 hex 就是 page id，带不带连字符都能用。
例：`https://app.notion.com/p/My-Note-0123456789abcdef0123456789abcdef` → `0123456789abcdef0123456789abcdef`

## CRUD 地图

### 查（找页面）

```bash
# 按标题关键词搜（只要页面，不要数据库）
ntn api v1/search -d '{"query":"关键词","filter":{"property":"object","value":"page"},"page_size":10}'
# 空 query = 列出全部可访问内容，用 next_cursor 翻页
```

结果里取 `results[].id` / `properties.title` / `url` / `last_edited_time`。
输出是原始 JSON，量大时用 `python3 -c` 或 `jq` 挑字段再给用户看，别整段回显。

### 读（页面正文）

```bash
ntn pages get <page-id>          # Markdown，属性作为 frontmatter 前置
ntn pages get <page-id> --json   # 结构化；正文被截断时用它看 unknown_block_ids
```

### 增（新建笔记）

```bash
ntn pages create --content '# 标题

正文…'
ntn pages create --parent page:<父页面id> --content '...'   # 也支持 database:<id> / data-source:<id>
cat note.md | ntn pages create --parent page:<id>          # 长内容走 stdin，更稳
```

不给 `--parent` 则落到默认位置。frontmatter 里的 `title` 会成为页面标题，其他属性被忽略。
**不要**用交互式（省略内容源会打开 $EDITOR，在本环境会卡住）。

### 改（更新正文）

```bash
ntn pages edit <page-id> --content '# 新正文'
cat new.md | ntn pages edit <page-id>
```

⚠️ `edit` 是**整篇正文替换**，不是追加。改动前先 `ntn pages get` 拿到原文，本地拼好再写回。
只想在末尾追加块：`ntn api v1/blocks/<page-id>/children -X PATCH -d '{...}'`（先 `--spec` 查结构）。

### 删

```bash
ntn pages trash <page-id>   # 进废纸篓，可在 Notion 里恢复
```

删除属于不可逆感知操作：**执行前先跟用户确认页面标题**，确认后再删。

### 数据库条目

```bash
ntn datasources resolve <database-id>          # database id → data source id（必须先转换）
ntn datasources query <data-source-id> --limit 50
ntn datasources query <ds-id> --filter '{"property":"Done","checkbox":{"equals":true}}'
```

改页面属性（状态、标签、日期等）不走 `pages edit`，走：
`ntn api v1/pages/<page-id> -X PATCH -d '{"properties":{...}}'`

### 其他

评论、用户、文件上传、meeting notes 等都在 `ntn api ls` 里，按需查 `--docs`。
文件上传另有便捷命令：`ntn files create`。

## 版本升级提醒规则

`ntn` 命令输出（含 stderr）或 `ntn doctor` 里若出现新版本提示 / 版本不是 latest：

1. **当前任务照常做完**，不要中途打断去升级；
2. 任务收尾时，在回复末尾附一句轻提醒，例如：
   「顺带一提，ntn 有新版本（当前 x.y.z），想升的话我可以帮你跑 `ntn update`。」
3. 未经用户同意**不要**自己执行 `ntn update`。
4. 同一会话里提醒过一次就够了，别反复念。

## 注意事项

- 私有集成只能看到被显式共享给它的页面；搜不到内容时先怀疑权限，提示用户在 Notion 里把页面 Share 给这个集成，而不是反复换关键词。
- `--json` 输出体积很大，先过滤再阅读。
- 中文标题、emoji 图标都正常支持。
