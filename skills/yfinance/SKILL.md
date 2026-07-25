---
name: yfinance
description: >-
  查询全球股票行情、财务报表、分析师评级、期权链、选股筛选、K线下载等。
  覆盖美股/港股/A股/全球市场。当用户问到股票价格、行情、K线、财务数据、
  PE/市值/分红/持仓/期权/分析师评级/选股筛选等金融市场数据时触发。
  数据来源 Yahoo Finance，仅限研究和教育用途。
---

# yfinance CLI

> 通过 Yahoo Finance 公开 API 获取全球金融市场数据（基于 yahoo-finance2）

## 执行方式

```bash
bun ./tools/yf_cli.js <subcommand> [flags]
```

首次使用需安装依赖：

```bash
cd tools && bun install
```

## 代码格式

| 市场 | 格式 | 示例 |
|---|---|---|
| 美股 | 直接代码 | `AAPL`, `MSFT`, `GOOG` |
| A股上交所 | 代码.SS | `600519.SS`（茅台）, `601318.SS`（平安） |
| A股深交所 | 代码.SZ | `000858.SZ`（五粮液）, `000001.SZ`（平安银行） |
| 港股 | 代码.HK | `0700.HK`（腾讯）, `9988.HK`（阿里） |
| 日股 | 代码.T | `7203.T`（丰田） |
| 英股 | 代码.L | `SHEL.L`（壳牌） |
| ETF | 直接代码 | `SPY`, `QQQ`, `VOO` |
| 指数 | ^前缀 | `^GSPC`（标普500）, `^DJI`（道琼斯）, `^IXIC`（纳斯达克） |
| 加密货币 | XXX-USD | `BTC-USD`, `ETH-USD` |

## 子命令

### quote - 实时报价

```bash
bun ./tools/yf_cli.js quote --symbols AAPL
bun ./tools/yf_cli.js quote --symbols "AAPL,MSFT,GOOG"
bun ./tools/yf_cli.js quote --symbols 600519.SS --json
```

多个代码用逗号分隔，一次批量请求。返回：当前价、涨跌额/幅、开高低收、成交量、市值、PE、52周高低

### history - 历史K线

```bash
bun ./tools/yf_cli.js history --symbol AAPL --period 5d --interval 1d
bun ./tools/yf_cli.js history --symbol 600519.SS --period 1mo
bun ./tools/yf_cli.js history --symbol MSFT --period 1y --interval 1wk
```

period 可选: `1d, 5d, 1mo, 3mo, 6mo, 1y, 2y, 5y, 10y, ytd, max`
interval 可选: `1m, 2m, 5m, 15m, 30m, 60m, 90m, 1h, 1d, 5d, 1wk, 1mo, 3mo`

### info - 公司信息

```bash
bun ./tools/yf_cli.js info --symbol AAPL
```

返回：公司名称、行业、国家、员工数、市值、PE/PB/PS、分红率、ROE/ROA、利润率、负债率等

### financials - 财务报表

```bash
bun ./tools/yf_cli.js financials --symbol AAPL --type income
bun ./tools/yf_cli.js financials --symbol MSFT --type balance --quarterly
bun ./tools/yf_cli.js financials --symbol GOOG --type cashflow --json
```

type: `income`（利润表）, `balance`（资产负债表）, `cashflow`（现金流量表）
`--quarterly` 获取季报，默认年报。数据来自 fundamentals time-series，指标为行、报告期为列

### holders - 持仓信息

```bash
bun ./tools/yf_cli.js holders --symbol AAPL
```

返回：内部人/机构持股比例、机构持仓Top10、内部人交易记录

### dividends - 分红与拆股

```bash
bun ./tools/yf_cli.js dividends --symbol AAPL
```

返回：历史分红记录（最近20条）、股票拆分记录

### options - 期权链

```bash
bun ./tools/yf_cli.js options --symbol AAPL
bun ./tools/yf_cli.js options --symbol AAPL --date 2026-06-20
```

返回：到期日列表、看涨/看跌期权的行权价、最新价、买卖价、成交量、持仓量、隐含波动率

### analyst - 分析师评级

```bash
bun ./tools/yf_cli.js analyst --symbol AAPL
```

返回：综合评级、评级均分、分析师数量、目标价（高/低/均/中位）、评级趋势、升降级记录

### news - 相关新闻

```bash
bun ./tools/yf_cli.js news --symbol AAPL --limit 5
```

### compare - 多股对比

```bash
bun ./tools/yf_cli.js compare --symbols "AAPL,MSFT,GOOG"
```

返回对比表：价格、市值、PE、前瞻PE、PB、分红率、ROE、利润率、Beta、52周高低

### search - 搜索

```bash
bun ./tools/yf_cli.js search --query "electric vehicle"
bun ./tools/yf_cli.js search --query bank
```

按关键词搜索标的与新闻。Yahoo 搜索端点对中文等非 ASCII 关键词返回 400，
查中概/A股/港股请直接用代码（如 `0700.HK`）或英文名

### market - 市场概况

```bash
bun ./tools/yf_cli.js market --market us_market
bun ./tools/yf_cli.js market --market hk_market
```

通过各市场代表指数汇总行情。market 可选:
`us_market, gb_market, hk_market, cn_market, jp_market, de_market, fr_market, in_market`

### screen - 选股筛选（预设）

```bash
bun ./tools/yf_cli.js screen --preset day_gainers
bun ./tools/yf_cli.js screen --preset undervalued_large_caps --count 50
bun ./tools/yf_cli.js screen --preset most_actives --region US --json
```

使用 Yahoo 内置预设筛选器（不支持自定义条件组合）。`--preset` 取值：
`aggressive_small_caps, conservative_foreign_funds, day_gainers, day_losers,
growth_technology_stocks, high_yield_bond, most_actives, most_shorted_stocks,
portfolio_anchors, small_cap_gainers, solid_large_growth_funds,
solid_midcap_growth_funds, top_mutual_funds, undervalued_growth_stocks,
undervalued_large_caps`
可选 `--region`（如 US/GB/DE）、`--count`（默认25）

### download - 批量下载CSV

```bash
bun ./tools/yf_cli.js download --symbols "AAPL,MSFT" --period 1y --output stocks.csv
```

长表格式输出：Symbol,Date,Open,High,Low,Close,AdjClose,Volume

## 通用参数

- `--json` 所有子命令均支持，输出 JSON 格式
- 多个股票代码用逗号分隔

## 注意事项

- 运行时使用 bun（本机 node 版本可能低于 yahoo-finance2 v4 要求的 v22+）
- 依赖安装: `cd tools && bun install`（yahoo-finance2）
- 数据来源 Yahoo Finance 公开 API，非官方接口，偶尔可能不稳定
- A 股数据可能有 15 分钟延迟
- 分钟级 K 线（1m/2m/5m）最多回溯 7 天
- 期权数据仅美股可用
- 财务报表子模块自 2024-11 起改用 fundamentals time-series，部分历史期次字段可能缺失
- 选股仅支持 15 个预设筛选器，不支持自定义市值/PE/行业条件
