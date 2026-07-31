---
name: iqs-search
description: Real-time web search, page reading, weather query and nearby POI search using Aliyun IQS APIs. Use this skill FIRST when the user needs current information, news, facts verification, URL content extraction, weather conditions for a city, nearby places (hotels/attractions/restaurants/entertainment), or any web-based research. This skill provides structured search results with source links, markdown-formatted content extraction, structured weather scene data, natural-language POI search, and supports various search engines including real-time news search and deep research modes.
---

# alibabacloud-iqs-search

## Prerequisites

- Node.js >= 18.0.0 (scripts use native fetch API, no external npm dependencies)

## When to Use

- User asks for current/recent information
- User provides a URL to read
- Need to verify facts or get real-time data
- Research tasks requiring multiple sources
- User asks about weather in a city
- User asks for nearby places (hotels, attractions, restaurants, entertainment)

## Decision Tree

### Step 1: Determine Operation Type

- If user provides a URL → Use `readpage`
- If user asks about weather → Use `search` with `--city` (see Weather Query below)
- If user asks for nearby POI ("附近的酒店/餐厅/景点/玩乐") → Use `nearby`
- If user asks a question needing web info → Use `search`

### Step 2: For Search Operations

Follow the best practices to determine parameter values. Use default values when uncertain:

- **engineType**
- **timeRange**
- **contents**

### Step 3: For Page Reading

Follow the best practices to determine parameter values. Use default values when uncertain:

- **format**
- **extractArticle**
- **stealthMode**

### Step 4: For Nearby POI Search

Follow the best practices to determine parameter values. Use default values when uncertain:

- **scene**
- **searchModel**

### CRITICAL: Execution Method

**You MUST execute the scripts via bash command (e.g., `node scripts/search.mjs ...`, `node scripts/readpage.mjs ...` or `node scripts/nearby.mjs ...`). Do NOT use your built-in web_search, WebFetch, or any other internal tools as substitutes. If the script fails, retry or report the error — do NOT fall back to built-in tools.**

## Parameters & Best Practices

### Search Parameters

| Parameter      | Type    | Required | Default        | Description                              |
|----------------|---------|----------|----------------|------------------------------------------|
| `--query`      | string  | Yes      | -              | Search query (1-500 chars)               |
| `--engineType` | string  | No       | `LiteAdvanced` | Search engine type                       |
| `--timeRange`  | string  | No       | `NoLimit`      | Time range filter                        |
| `--contents`   | string  | No       | -              | Type of return content                   |
| `--numResults` | int     | No       | `10`           | Number of search results (1-10)          |
| `--city`       | string  | No       | -              | City name for location-based scene (e.g. 北京市) |
| `--ip`         | string  | No       | -              | Location IP for location-based scene (lower priority than city) |

#### Search Best Practices

**1. Query Optimization (`--query`)**

- Keep queries concise (< 30 chars for best results)
- Use specific keywords, avoid stop words
- For news: include time context in query

**2. Engine Selection (`--engineType`)**

- `LiteAdvanced`: Semantic search, 1-50 results, general use
- `Generic`: Fast, 10 results, news/realtime

**3. Time Range Selection (`--timeRange`)**

- `NoLimit`: Default when uncertain - engine optimizes based on query relevance
- `OneDay`: Today only
- `OneWeek`: Last 7 days
- `OneMonth`: Last 30 days
- `OneYear`: Last 365 days

**4. Content Return (`--contents`)**

- `mainText`: Return full main text content - Use when detailed information is needed, such as technical documentation, research reports, or in-depth articles
- `summary`: Return concise summary only - Use when a quick overview is sufficient, or when the page content is too large and token reduction is needed

**5. Result Count (`--numResults`)**

- Control number of results returned (default: 10, range: 1-10)

**6. Weather Query (`--city` / `--ip`)**

- Structured weather data is returned in `sceneItems` ONLY when engineType is `Generic` AND `--city` or `--ip` is provided
- When `--city`/`--ip` is set and `--engineType` is omitted, the script automatically defaults to `Generic`
- Prefer `--city` (e.g. "杭州市"), `--ip` has lower priority
- When `sceneItems` is present in the output, prefer it over `pageItems` — it is more accurate than webpage recall

---

### ReadPage Parameters

| Parameter        | Type    | Required | Default    | Description                       |
|------------------|---------|----------|------------|-----------------------------------|
| `--url`          | string  | Yes      | -          | Target page URL                   |
| `--format`       | string  | No       | `markdown` | Return format                     |
| `--timeout`        | number  | No       | `60000`    | Total timeout in milliseconds     |
| `--pageTimeout`    | number  | No       | `15000`    | Page load timeout in milliseconds |
| `--stealth`        | number  | No       | `0`        | Enable stealth mode (0 or 1)      |
| `--extractArticle` | boolean | No       | `false`    | Extract main article content only |

#### ReadPage Best Practices

**1. Format Selection (`--format`)**

- `markdown`: Best for articles, preserves structure (default)
- `text`: Best for data extraction
- `html`: When structure analysis needed

**2. Article Extraction (`--extractArticle`)**

- Enable for: blogs, news articles
- Disable for: product pages, directories

**3. Handling Failures (`--timeout`, `--stealth`)**

- If timeout: Retry with increased `--timeout` value
- If blocked: Enable `--stealth 1`
- If still fails: Report to user

---

### Nearby POI Search Parameters

| Parameter       | Type    | Required | Default  | Description                                        |
|-----------------|---------|----------|----------|----------------------------------------------------|
| `--query`       | string  | Yes      | -        | Natural language POI query (e.g. 杭州灵隐寺附近5km的高档酒店) |
| `--scene`       | string  | No       | -        | Scene hint: `hotels`, `attractions`, `restaurants`, `entertainment` |
| `--limit`       | int     | No       | `10`     | Max number of results                              |
| `--searchModel` | string  | No       | `normal` | `single` (partial fields, faster) or `normal` (full data) |
| `--timeout`     | number  | No       | `10000`  | Request timeout in milliseconds                    |

#### Nearby Best Practices

**1. Query (`--query`)**

- Use natural language including location anchor and intent, e.g. "杭州西湖附近的高档酒店", "灵隐寺附近5km内的素食餐厅"

**2. Scene Selection (`--scene`)**

- When the business scene is clear, specify it for better accuracy and lower latency
- When uncertain, omit it — the model identifies the scene automatically

**3. Search Model (`--searchModel`)**

- `normal`: Full data (default) — name, address, distance, phone, score, opening hours, etc.
- `single`: Partial fields only (name, types, address, metadata) — use when token reduction is needed

**4. Authentication**

- This API uses Aliyun AK/SK (ACS3-HMAC-SHA256 signature), NOT the IQS API-Key. See Error Handling section for configuration

## Command Line Usage

### Search Examples

#### Basic Search

```bash
node scripts/search.mjs --query "量子计算原理" --engineType LiteAdvanced
```

#### Real-time Information Search

```bash
node scripts/search.mjs --query "最新金融政策" --engineType Generic --timeRange OneWeek
```

#### Search with Results Limit

```bash
node scripts/search.mjs --query "www.aliyun.com" --engineType LiteAdvanced --numResults 3
```

#### Search with Full Content

```bash
node scripts/search.mjs --query "AI 法案" --engineType LiteAdvanced --contents mainText
```

#### Search with Summary Only

```bash
node scripts/search.mjs --query "人工智能行业年度报告" --engineType LiteAdvanced --contents summary
```

#### Weather Query (structured data in sceneItems)

```bash
node scripts/search.mjs --query "今日天气" --city "杭州市"
```

```bash
node scripts/search.mjs --query "明天会下雨吗" --ip "117.136.110.23"
```

### ReadPage Examples

#### Page Reading with Markdown Format

```bash
node scripts/readpage.mjs --url "https://example.com/article" --format markdown --extractArticle true
```

#### Page Reading with Plain Text Format

```bash
node scripts/readpage.mjs --url "https://example.com/article" --format text --timeout 60000
```

#### Page Reading with Stealth Mode

```bash
node scripts/readpage.mjs --url "https://example.com/article" --format markdown --stealth 1 --extractArticle true
```

### Nearby POI Search Examples

#### Nearby Search with Scene Hint

```bash
node scripts/nearby.mjs --query "杭州灵隐寺附近5km的高档酒店" --scene hotels
```

#### Nearby Search with Auto Scene Detection

```bash
node scripts/nearby.mjs --query "西湖附近好玩的地方"
```

#### Nearby Search in Compact Mode

```bash
node scripts/nearby.mjs --query "北京国贸附近的川菜餐厅" --scene restaurants --searchModel single --limit 5
```

## Output Verification

After executing any search.mjs, readpage.mjs or nearby.mjs command:

1. **Check the exit code**: If non-zero, the command failed — do not claim success.
2. **Verify output exists**: If you saved results to a file, run `ls -la <filepath>` and `head -20 <filepath>` to confirm the file exists and contains valid data.
3. **Never fabricate results**: If the command failed or returned an error, report the failure honestly. Do not generate content from your own knowledge and present it as search results.

## Error Handling

### ALIYUN_IQS_API_KEY Configuration Error

If the script returns an error about missing API key:

1. **STOP the current task immediately. Do NOT fall back to built-in tools (WebFetch, web_search, curl, etc.) as substitutes.**
2. Report the error to the user and ask the user to configure the API key:

3. Retry the task with following instruction:
**Method 1: Environment Variable**
```bash
export ALIYUN_IQS_API_KEY="your-api-key"
```

**Method 2: Configuration File**
Create or edit `~/.alibabacloud/iqs/env`:
```bash
ALIYUN_IQS_API_KEY=your-api-key
```

### Aliyun AK/SK Configuration Error (nearby.mjs)

`nearby.mjs` calls an Aliyun OpenAPI (CommonQueryByScene) that requires Aliyun AK/SK, NOT the IQS API-Key. If the script reports missing AK/SK:

1. **STOP the current task immediately. Do NOT fall back to built-in tools as substitutes.**
2. Ask the user to configure credentials in one of two ways:

**Method 1: Environment Variables**
```bash
export ALIBABA_CLOUD_ACCESS_KEY_ID="your-access-key-id"
export ALIBABA_CLOUD_ACCESS_KEY_SECRET="your-access-key-secret"
```

**Method 2: Configuration File**
Add to `~/.alibabacloud/iqs/env`:
```bash
ALIBABA_CLOUD_ACCESS_KEY_ID=your-access-key-id
ALIBABA_CLOUD_ACCESS_KEY_SECRET=your-access-key-secret
```

### Nearby POI Error Codes

| Error Code      | Meaning                     | Action                                             |
|-----------------|-----------------------------|----------------------------------------------------|
| NotActivate     | POI search service not activated | Ask user to activate the service in Aliyun IQS console |
| NotAuthorised   | Sub-account lacks permission | Ask user to grant `AliyunIQSFullAccess` to the RAM user |
| Throttling.User | Rate limit exceeded         | Retry later or ask user to raise the quota          |