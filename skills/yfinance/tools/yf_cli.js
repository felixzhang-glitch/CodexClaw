#!/usr/bin/env bun
// yfinance CLI - unified command-line interface for Yahoo Finance data.
// Powered by yahoo-finance2. Run with: bun ./tools/yf_cli.js <subcommand> [flags]

import YahooFinance from "yahoo-finance2";

const yf = new YahooFinance({
  suppressNotices: ["yahooSurvey", "ripHistorical"],
  validation: { logErrors: false },
});

// --- helpers ---

function safeGet(v, def = "N/A") {
  return v === null || v === undefined ? def : v;
}

function fmtNumber(n) {
  if (n === null || n === undefined || n === "N/A") return "N/A";
  if (typeof n === "string") return n;
  const a = Math.abs(n);
  if (a >= 1e12) return (n / 1e12).toFixed(2) + "T";
  if (a >= 1e9) return (n / 1e9).toFixed(2) + "B";
  if (a >= 1e6) return (n / 1e6).toFixed(2) + "M";
  if (a >= 1e4) return (n / 1e4).toFixed(2) + "W";
  if (!Number.isInteger(n)) return n.toFixed(2);
  return String(n);
}

// value is a fraction (0.33 => 33%)
function pctFrac(n) {
  if (n === null || n === undefined || n === "N/A") return "N/A";
  return (n * 100).toFixed(2) + "%";
}

// value is already a percentage number (0.33 => 0.33%)
function pctRaw(n) {
  if (n === null || n === undefined || n === "N/A") return "N/A";
  return n.toFixed(2) + "%";
}

function num2(n) {
  if (n === null || n === undefined || n === "N/A") return "N/A";
  if (typeof n === "number") return Number.isInteger(n) ? String(n) : n.toFixed(2);
  return String(n);
}

function ymd(d) {
  if (!d) return "N/A";
  const dt = d instanceof Date ? d : new Date(d);
  if (isNaN(dt.getTime())) return String(d);
  return dt.toISOString().slice(0, 10);
}

// Render an aligned text table. headers: string[], rows: string[][]
function printTable(headers, rows) {
  const widths = headers.map((h, i) =>
    Math.max(String(h).length, ...rows.map((r) => String(r[i] ?? "").length))
  );
  const line = (cells) =>
    cells.map((c, i) => String(c ?? "").padStart(widths[i])).join("  ");
  console.log(line(headers));
  for (const r of rows) console.log(line(r));
}

function out(obj) {
  console.log(JSON.stringify(obj, null, 2));
}

// --- subcommands ---

async function cmdQuote(args) {
  const symbols = args.symbols.split(",").map((s) => s.trim());
  const results = await yf.quote(symbols);
  const list = Array.isArray(results) ? results : [results];
  const rows = list.map((q) => ({
    symbol: (q.symbol || "").toUpperCase(),
    name: safeGet(q.shortName),
    price: safeGet(q.regularMarketPrice),
    change: safeGet(q.regularMarketChange),
    "change%": q.regularMarketChangePercent != null ? pctRaw(q.regularMarketChangePercent) : "N/A",
    open: safeGet(q.regularMarketOpen),
    high: safeGet(q.regularMarketDayHigh),
    low: safeGet(q.regularMarketDayLow),
    prev_close: safeGet(q.regularMarketPreviousClose),
    volume: fmtNumber(q.regularMarketVolume),
    market_cap: fmtNumber(q.marketCap),
    pe: safeGet(q.trailingPE),
    "52w_high": safeGet(q.fiftyTwoWeekHigh),
    "52w_low": safeGet(q.fiftyTwoWeekLow),
    currency: safeGet(q.currency),
    exchange: safeGet(q.fullExchangeName),
  }));

  if (args.json) return out(rows);
  for (const r of rows) {
    console.log(`=== ${r.symbol} (${r.name}) ===`);
    console.log(`  Price:      ${num2(r.price)}  Change: ${num2(r.change)} (${r["change%"]})`);
    console.log(`  Open:       ${num2(r.open)}  Prev Close: ${num2(r.prev_close)}`);
    console.log(`  High:       ${num2(r.high)}  Low: ${num2(r.low)}`);
    console.log(`  Volume:     ${r.volume}  Market Cap: ${r.market_cap}`);
    console.log(`  PE:         ${num2(r.pe)}  Currency: ${r.currency}`);
    console.log(`  52W High:   ${num2(r["52w_high"])}  52W Low: ${num2(r["52w_low"])}`);
    console.log(`  Exchange:   ${r.exchange}`);
    console.log();
  }
}

const PERIOD_DAYS = {
  "1d": 1, "5d": 5, "1mo": 31, "3mo": 93, "6mo": 186,
  "1y": 366, "2y": 731, "5y": 1827, "10y": 3653,
};

function periodToStart(period) {
  const now = new Date();
  if (period === "max") return new Date("1970-01-01");
  if (period === "ytd") return new Date(now.getFullYear(), 0, 1);
  const days = PERIOD_DAYS[period] ?? 31;
  return new Date(now.getTime() - days * 86400000);
}

async function fetchChart(symbol, period, interval) {
  return yf.chart(symbol, {
    period1: periodToStart(period),
    period2: new Date(),
    interval,
  });
}

async function cmdHistory(args) {
  const chart = await fetchChart(args.symbol, args.period, args.interval);
  const quotes = chart.quotes || [];
  if (!quotes.length) {
    console.log(`No history data for ${args.symbol}`);
    return;
  }
  if (args.json) return out(quotes);
  console.log(`=== ${args.symbol.toUpperCase()} History (${args.period}, ${args.interval}) ===`);
  const rows = quotes.map((q) => [
    ymd(q.date),
    num2(q.open), num2(q.high), num2(q.low), num2(q.close),
    q.adjclose != null ? num2(q.adjclose) : "N/A",
    q.volume != null ? String(q.volume) : "N/A",
  ]);
  printTable(["Date", "Open", "High", "Low", "Close", "AdjClose", "Volume"], rows);
}

async function cmdInfo(args) {
  const qs = await yf.quoteSummary(args.symbol, {
    modules: ["assetProfile", "summaryDetail", "defaultKeyStatistics", "financialData", "price"],
  });
  const ap = qs.assetProfile || {};
  const sd = qs.summaryDetail || {};
  const ks = qs.defaultKeyStatistics || {};
  const fd = qs.financialData || {};
  const pr = qs.price || {};

  const fields = [
    ["Name", pr.shortName],
    ["Full Name", pr.longName],
    ["Sector", ap.sector],
    ["Industry", ap.industry],
    ["Country", ap.country],
    ["City", ap.city],
    ["Website", ap.website],
    ["Employees", ap.fullTimeEmployees != null ? ap.fullTimeEmployees.toLocaleString("en-US") : null],
    ["Market Cap", fmtNumber(pr.marketCap)],
    ["Enterprise Value", fmtNumber(ks.enterpriseValue)],
    ["Trailing PE", num2(sd.trailingPE)],
    ["Forward PE", num2(sd.forwardPE)],
    ["P/B", num2(ks.priceToBook)],
    ["P/S", num2(sd.priceToSalesTrailing12Months)],
    ["Dividend Yield", sd.dividendYield != null ? pctFrac(sd.dividendYield) : null],
    ["Payout Ratio", sd.payoutRatio != null ? pctFrac(sd.payoutRatio) : null],
    ["Beta", num2(sd.beta)],
    ["EPS (TTM)", num2(ks.trailingEps)],
    ["EPS (FWD)", num2(ks.forwardEps)],
    ["Book Value", num2(ks.bookValue)],
    ["Revenue Growth", fd.revenueGrowth != null ? pctFrac(fd.revenueGrowth) : null],
    ["Earnings Growth", fd.earningsGrowth != null ? pctFrac(fd.earningsGrowth) : null],
    ["Profit Margin", fd.profitMargins != null ? pctFrac(fd.profitMargins) : null],
    ["Operating Margin", fd.operatingMargins != null ? pctFrac(fd.operatingMargins) : null],
    ["ROE", fd.returnOnEquity != null ? pctFrac(fd.returnOnEquity) : null],
    ["ROA", fd.returnOnAssets != null ? pctFrac(fd.returnOnAssets) : null],
    ["D/E Ratio", num2(fd.debtToEquity)],
    ["Current Ratio", num2(fd.currentRatio)],
    ["Free Cash Flow", fmtNumber(fd.freeCashflow)],
    ["Total Revenue", fmtNumber(fd.totalRevenue)],
    ["Total Debt", fmtNumber(fd.totalDebt)],
    ["Total Cash", fmtNumber(fd.totalCash)],
    ["Currency", pr.currency],
  ];

  if (args.json) {
    const o = {};
    for (const [label, val] of fields) if (val != null && val !== "N/A") o[label] = val;
    return out(o);
  }
  console.log(`=== ${args.symbol.toUpperCase()} Info ===`);
  for (const [label, val] of fields) {
    if (val != null && val !== "N/A") console.log(`  ${label.padEnd(20)}: ${val}`);
  }
  const summary = ap.longBusinessSummary;
  if (summary) console.log(`\n  Summary: ${summary.slice(0, 300)}...`);
}

const FIN_MODULE = { income: "financials", balance: "balance-sheet", cashflow: "cash-flow" };
const FIN_TITLE = { income: "Income Statement", balance: "Balance Sheet", cashflow: "Cash Flow" };
const FIN_SKIP = new Set(["date", "TYPE", "periodType"]);

async function cmdFinancials(args) {
  const module = FIN_MODULE[args.type] || "financials";
  const title = FIN_TITLE[args.type] || "Income Statement";
  const period = args.quarterly ? "Quarterly" : "Annual";
  const now = new Date();
  const p1 = new Date(now.getFullYear() - (args.quarterly ? 3 : 5), 0, 1);
  const series = await yf.fundamentalsTimeSeries(args.symbol, {
    period1: p1,
    period2: now,
    type: args.quarterly ? "quarterly" : "annual",
    module,
  });
  if (!series || !series.length) {
    console.log(`No ${title} data for ${args.symbol}`);
    return;
  }
  if (args.json) return out(series);

  const periods = [...series].sort((a, b) => new Date(a.date) - new Date(b.date));
  const dates = periods.map((p) => ymd(p.date));
  const metrics = [];
  const seen = new Set();
  for (const p of periods) {
    for (const k of Object.keys(p)) {
      if (!FIN_SKIP.has(k) && !seen.has(k)) {
        seen.add(k);
        metrics.push(k);
      }
    }
  }
  console.log(`=== ${args.symbol.toUpperCase()} ${title} (${period}) ===`);
  const rows = metrics.map((m) => [m, ...periods.map((p) => fmtNumber(p[m]))]);
  printTable(["Metric", ...dates], rows);
}

async function cmdHolders(args) {
  const qs = await yf.quoteSummary(args.symbol, {
    modules: ["majorHoldersBreakdown", "institutionOwnership", "insiderTransactions"],
  });
  const sym = args.symbol.toUpperCase();

  if (args.json) {
    return out({
      majorHolders: qs.majorHoldersBreakdown || {},
      institutionalHolders: (qs.institutionOwnership?.ownershipList || []).slice(0, 10),
      insiderTransactions: (qs.insiderTransactions?.transactions || []).slice(0, 10),
    });
  }

  console.log(`=== ${sym} Major Holders ===`);
  const mh = qs.majorHoldersBreakdown;
  if (mh) {
    if (mh.insidersPercentHeld != null) console.log(`  Insiders Held:        ${pctFrac(mh.insidersPercentHeld)}`);
    if (mh.institutionsPercentHeld != null) console.log(`  Institutions Held:    ${pctFrac(mh.institutionsPercentHeld)}`);
    if (mh.institutionsFloatPercentHeld != null) console.log(`  Institutions Float:   ${pctFrac(mh.institutionsFloatPercentHeld)}`);
    if (mh.institutionsCount != null) console.log(`  Institutions Count:   ${mh.institutionsCount}`);
  } else {
    console.log("  No major holder data.");
  }

  console.log(`\n=== Institutional Holders (Top 10) ===`);
  const ih = qs.institutionOwnership?.ownershipList || [];
  if (ih.length) {
    const rows = ih.slice(0, 10).map((h) => [
      safeGet(h.organization), ymd(h.reportDate),
      h.pctHeld != null ? pctFrac(h.pctHeld) : "N/A",
      fmtNumber(h.position), fmtNumber(h.value),
    ]);
    printTable(["Organization", "Date", "% Held", "Shares", "Value"], rows);
  } else {
    console.log("  No institutional holder data.");
  }

  console.log(`\n=== Insider Transactions (Recent) ===`);
  const it = qs.insiderTransactions?.transactions || [];
  if (it.length) {
    const rows = it.slice(0, 10).map((t) => [
      safeGet(t.filerName), safeGet(t.filerRelation), ymd(t.startDate),
      fmtNumber(t.shares), fmtNumber(t.value), safeGet(t.transactionText, ""),
    ]);
    printTable(["Insider", "Relation", "Date", "Shares", "Value", "Text"], rows);
  } else {
    console.log("  No insider transaction data.");
  }
}

async function cmdDividends(args) {
  const chart = await yf.chart(args.symbol, {
    period1: new Date("1970-01-01"),
    period2: new Date(),
    interval: "1d",
    events: "div|split",
  });
  const divs = chart.events?.dividends || [];
  const splits = chart.events?.splits || [];

  if (args.json) {
    return out({
      dividends: divs.map((d) => ({ date: ymd(d.date), amount: d.amount })),
      splits: splits.map((s) => ({ date: ymd(s.date), splitRatio: s.splitRatio })),
    });
  }

  console.log(`=== ${args.symbol.toUpperCase()} Dividends ===`);
  if (divs.length) {
    const rows = divs.slice(-20).map((d) => [ymd(d.date), num2(d.amount)]);
    printTable(["Date", "Dividend"], rows);
  } else {
    console.log("  No dividend data.");
  }

  console.log(`\n=== Stock Splits ===`);
  if (splits.length) {
    const rows = splits.map((s) => [ymd(s.date), safeGet(s.splitRatio)]);
    printTable(["Date", "Split"], rows);
  } else {
    console.log("  No split data.");
  }
}

async function cmdOptions(args) {
  const opt = await yf.options(args.symbol, args.date ? { date: new Date(args.date) } : {});
  const dates = (opt.expirationDates || []).map((d) => ymd(d));
  if (!dates.length) {
    console.log(`No options data for ${args.symbol}`);
    return;
  }
  const chain = opt.options?.[0];
  const target = chain ? ymd(chain.expirationDate) : dates[0];

  if (args.json) {
    return out({
      expiration: target,
      availableDates: dates,
      calls: chain?.calls || [],
      puts: chain?.puts || [],
    });
  }

  console.log(`=== ${args.symbol.toUpperCase()} Options (Exp: ${target}) ===`);
  console.log(`Available dates: ${dates.slice(0, 10).join(", ")}`);

  const render = (contracts, label) => {
    console.log(`\n--- ${label} (${contracts.length} contracts) ---`);
    const rows = contracts.slice(0, 20).map((c) => [
      num2(c.strike), num2(c.lastPrice), num2(c.bid), num2(c.ask),
      c.volume != null ? String(c.volume) : "N/A",
      c.openInterest != null ? String(c.openInterest) : "N/A",
      c.impliedVolatility != null ? c.impliedVolatility.toFixed(4) : "N/A",
    ]);
    printTable(["strike", "lastPrice", "bid", "ask", "volume", "openInt", "impliedVol"], rows);
  };
  render(chain?.calls || [], "Calls");
  render(chain?.puts || [], "Puts");
}

async function cmdAnalyst(args) {
  const qs = await yf.quoteSummary(args.symbol, {
    modules: ["financialData", "recommendationTrend", "upgradeDowngradeHistory"],
  });
  const fd = qs.financialData || {};
  const trend = qs.recommendationTrend?.trend || [];
  const upgrades = qs.upgradeDowngradeHistory?.history || [];

  if (args.json) {
    return out({
      targetHighPrice: fd.targetHighPrice,
      targetLowPrice: fd.targetLowPrice,
      targetMeanPrice: fd.targetMeanPrice,
      targetMedianPrice: fd.targetMedianPrice,
      recommendationKey: fd.recommendationKey,
      recommendationMean: fd.recommendationMean,
      numberOfAnalystOpinions: fd.numberOfAnalystOpinions,
      recommendationTrend: trend,
      upgradesDowngrades: upgrades.slice(0, 10),
    });
  }

  console.log(`=== ${args.symbol.toUpperCase()} Analyst ===`);
  console.log(`  Recommendation:    ${safeGet(fd.recommendationKey)}`);
  console.log(`  Rec Mean Score:    ${safeGet(fd.recommendationMean)}`);
  console.log(`  Analyst Count:     ${safeGet(fd.numberOfAnalystOpinions)}`);
  console.log(`  Target High:       ${safeGet(fd.targetHighPrice)}`);
  console.log(`  Target Low:        ${safeGet(fd.targetLowPrice)}`);
  console.log(`  Target Mean:       ${safeGet(fd.targetMeanPrice)}`);
  console.log(`  Target Median:     ${safeGet(fd.targetMedianPrice)}`);

  if (trend.length) {
    console.log(`\n--- Recommendation Trend ---`);
    const rows = trend.map((t) => [
      t.period, String(t.strongBuy), String(t.buy), String(t.hold), String(t.sell), String(t.strongSell),
    ]);
    printTable(["Period", "StrongBuy", "Buy", "Hold", "Sell", "StrongSell"], rows);
  }

  if (upgrades.length) {
    console.log(`\n--- Upgrades/Downgrades (Recent) ---`);
    const rows = upgrades.slice(0, 10).map((u) => [
      ymd(u.epochGradeDate), safeGet(u.firm), safeGet(u.toGrade), safeGet(u.fromGrade), safeGet(u.action),
    ]);
    printTable(["Date", "Firm", "To", "From", "Action"], rows);
  }
}

async function cmdNews(args) {
  const res = await yf.search(args.symbol, { newsCount: Math.max(args.limit, 10) });
  const news = res.news || [];
  if (!news.length) {
    console.log(`No news for ${args.symbol}`);
    return;
  }
  const items = news.slice(0, args.limit);
  if (args.json) return out(items);
  console.log(`=== ${args.symbol.toUpperCase()} News ===`);
  items.forEach((item, i) => {
    console.log(`  [${i + 1}] ${safeGet(item.title)}`);
    console.log(`      Source: ${safeGet(item.publisher)}  Date: ${ymd(item.providerPublishTime)}`);
    console.log(`      URL: ${safeGet(item.link)}`);
    console.log();
  });
}

async function cmdCompare(args) {
  const symbols = args.symbols.split(",").map((s) => s.trim());
  const data = await Promise.all(
    symbols.map(async (sym) => {
      const qs = await yf.quoteSummary(sym, {
        modules: ["price", "summaryDetail", "defaultKeyStatistics", "financialData"],
      });
      return { sym, qs };
    })
  );
  const rows = data.map(({ sym, qs }) => {
    const pr = qs.price || {}, sd = qs.summaryDetail || {}, ks = qs.defaultKeyStatistics || {}, fd = qs.financialData || {};
    return {
      Symbol: sym.toUpperCase(),
      Name: safeGet(pr.shortName),
      Price: num2(pr.regularMarketPrice),
      MarketCap: fmtNumber(pr.marketCap),
      PE: num2(sd.trailingPE),
      FwdPE: num2(sd.forwardPE),
      "P/B": num2(ks.priceToBook),
      DivYield: sd.dividendYield != null ? pctFrac(sd.dividendYield) : "N/A",
      ROE: fd.returnOnEquity != null ? pctFrac(fd.returnOnEquity) : "N/A",
      Margin: fd.profitMargins != null ? pctFrac(fd.profitMargins) : "N/A",
      Beta: num2(sd.beta),
      "52wHigh": num2(sd.fiftyTwoWeekHigh),
      "52wLow": num2(sd.fiftyTwoWeekLow),
    };
  });

  if (args.json) return out(rows);
  console.log(`=== Compare: ${symbols.join(", ")} ===`);
  const headers = Object.keys(rows[0]);
  printTable(headers, rows.map((r) => headers.map((h) => r[h])));
}

async function cmdSearch(args) {
  const res = await yf.search(args.query);
  const quotes = res.quotes || [];
  const news = res.news || [];

  if (args.json) return out({ quotes, news: news.slice(0, 5) });

  console.log(`=== Search: ${args.query} ===`);
  if (quotes.length) {
    console.log(`\n--- Quotes (${quotes.length} results) ---`);
    const rows = quotes.slice(0, 10).map((q) => [
      safeGet(q.symbol), safeGet(q.shortname || q.longname), safeGet(q.quoteType), safeGet(q.exchange),
    ]);
    printTable(["Symbol", "Name", "Type", "Exchange"], rows);
  } else {
    console.log("  No quotes found.");
  }
  if (news.length) {
    console.log(`\n--- Related News ---`);
    for (const n of news.slice(0, 5)) console.log(`  - ${safeGet(n.title)}`);
  }
}

const MARKET_INDICES = {
  us_market: ["^GSPC", "^DJI", "^IXIC", "^RUT"],
  gb_market: ["^FTSE"],
  hk_market: ["^HSI"],
  cn_market: ["000001.SS", "399001.SZ"],
  jp_market: ["^N225"],
  de_market: ["^GDAXI"],
  fr_market: ["^FCHI"],
  in_market: ["^BSESN", "^NSEI"],
};

async function cmdMarket(args) {
  const indices = MARKET_INDICES[args.market] || MARKET_INDICES.us_market;
  const results = await yf.quote(indices);
  const list = Array.isArray(results) ? results : [results];

  if (args.json) {
    return out({
      market: args.market,
      indices: list.map((q) => ({
        symbol: q.symbol,
        name: q.shortName,
        price: q.regularMarketPrice,
        change: q.regularMarketChange,
        changePercent: q.regularMarketChangePercent,
        marketState: q.marketState,
      })),
    });
  }

  console.log(`=== Market: ${args.market} ===`);
  const rows = list.map((q) => [
    safeGet(q.symbol), safeGet(q.shortName), num2(q.regularMarketPrice),
    num2(q.regularMarketChange),
    q.regularMarketChangePercent != null ? pctRaw(q.regularMarketChangePercent) : "N/A",
    safeGet(q.marketState),
  ]);
  printTable(["Symbol", "Name", "Price", "Change", "Change%", "State"], rows);
}

const PRESETS = [
  "aggressive_small_caps", "conservative_foreign_funds", "day_gainers", "day_losers",
  "growth_technology_stocks", "high_yield_bond", "most_actives", "most_shorted_stocks",
  "portfolio_anchors", "small_cap_gainers", "solid_large_growth_funds",
  "solid_midcap_growth_funds", "top_mutual_funds", "undervalued_growth_stocks",
  "undervalued_large_caps",
];

async function cmdScreen(args) {
  if (!args.preset) {
    console.error(`--preset is required. Available presets:\n  ${PRESETS.join("\n  ")}`);
    process.exit(1);
  }
  if (!PRESETS.includes(args.preset)) {
    console.error(`Unknown preset "${args.preset}". Available:\n  ${PRESETS.join("\n  ")}`);
    process.exit(1);
  }
  const opts = { count: args.count };
  if (args.region) opts.region = args.region;
  const res = await yf.screener(args.preset, opts);
  const quotes = res.quotes || [];

  if (args.json) return out(res);

  if (!quotes.length) {
    console.log("No results.");
    return;
  }
  console.log(`=== Screener: ${args.preset} (${res.count}/${res.total}) ===`);
  const rows = quotes.map((q) => [
    safeGet(q.symbol), safeGet(q.shortName || q.longName),
    num2(q.regularMarketPrice), fmtNumber(q.marketCap), num2(q.trailingPE),
    q.regularMarketChangePercent != null ? pctRaw(q.regularMarketChangePercent) : "N/A",
  ]);
  printTable(["Symbol", "Name", "Price", "MarketCap", "PE", "Change%"], rows);
}

async function cmdDownload(args) {
  const symbols = args.symbols.split(",").map((s) => s.trim());
  const header = "Symbol,Date,Open,High,Low,Close,AdjClose,Volume";
  const lines = [header];
  let rowCount = 0;
  for (const sym of symbols) {
    const chart = await fetchChart(sym, args.period, args.interval);
    for (const q of chart.quotes || []) {
      lines.push([
        sym.toUpperCase(), ymd(q.date),
        q.open ?? "", q.high ?? "", q.low ?? "", q.close ?? "",
        q.adjclose ?? "", q.volume ?? "",
      ].join(","));
      rowCount++;
    }
  }
  const output = args.output || `yf_${symbols.join("_")}_${args.period}.csv`;
  await Bun.write(output, lines.join("\n") + "\n");
  console.log(`Saved to ${output} (${rowCount} rows)`);
}

// --- arg parsing ---

const ALIASES = {
  s: "symbols_or_symbol", p: "period", i: "interval", t: "type",
  q: "query_or_quarterly", l: "limit", d: "date", m: "market", o: "output",
};

function parseArgs(argv) {
  const args = { _positional: [] };
  for (let i = 0; i < argv.length; i++) {
    let tok = argv[i];
    if (tok.startsWith("--")) {
      const key = tok.slice(2);
      if (key === "json" || key === "quarterly") {
        args[key] = true;
      } else {
        args[key.replace(/-/g, "_")] = argv[++i];
      }
    } else if (tok.startsWith("-") && tok.length === 2) {
      const short = tok[1];
      // resolve short flags contextually below in normalize()
      args["__short_" + short] = i + 1 < argv.length && !argv[i + 1].startsWith("-") ? argv[++i] : true;
    } else {
      args._positional.push(tok);
    }
  }
  return args;
}

// Map short flags to their canonical names per command.
function normalize(cmd, a) {
  const g = (long, short) => {
    if (a[long] !== undefined) return a[long];
    if (a["__short_" + short] !== undefined) return a["__short_" + short];
    return undefined;
  };
  const r = { json: !!a.json };

  if (["quote", "compare", "download"].includes(cmd)) r.symbols = g("symbols", "s") ?? a._positional[0];
  if (["history", "info", "financials", "holders", "dividends", "options", "analyst", "news"].includes(cmd))
    r.symbol = g("symbol", "s") ?? a._positional[0];

  if (["history", "download"].includes(cmd)) {
    r.period = g("period", "p") ?? "1mo";
    r.interval = g("interval", "i") ?? "1d";
  }
  if (cmd === "download") { r.period = g("period", "p") ?? "1y"; r.output = g("output", "o"); }
  if (cmd === "financials") {
    r.type = g("type", "t") ?? "income";
    r.quarterly = !!(a.quarterly || a.__short_q === true);
  }
  if (cmd === "options") r.date = g("date", "d");
  if (cmd === "news") r.limit = parseInt(g("limit", "l") ?? "10", 10);
  if (cmd === "search") r.query = g("query", "q") ?? a._positional[0];
  if (cmd === "market") r.market = g("market", "m") ?? a._positional[0] ?? "us_market";
  if (cmd === "screen") {
    r.preset = a.preset ?? a._positional[0];
    r.region = a.region;
    r.count = parseInt(a.count ?? "25", 10);
  }
  return r;
}

const COMMANDS = {
  quote: cmdQuote, history: cmdHistory, info: cmdInfo, financials: cmdFinancials,
  holders: cmdHolders, dividends: cmdDividends, options: cmdOptions, analyst: cmdAnalyst,
  news: cmdNews, compare: cmdCompare, search: cmdSearch, market: cmdMarket,
  screen: cmdScreen, download: cmdDownload,
};

function usage() {
  console.log(`yfinance CLI (yahoo-finance2)

Usage: bun ./tools/yf_cli.js <command> [flags]

Commands:
  quote      Real-time quotes          --symbols AAPL,MSFT [--json]
  history    Historical OHLCV          --symbol AAPL --period 1mo --interval 1d [--json]
  info       Company information       --symbol AAPL [--json]
  financials Financial statements      --symbol AAPL --type income|balance|cashflow [--quarterly] [--json]
  holders    Holder information        --symbol AAPL [--json]
  dividends  Dividends and splits      --symbol AAPL [--json]
  options    Options chain             --symbol AAPL [--date YYYY-MM-DD] [--json]
  analyst    Analyst ratings           --symbol AAPL [--json]
  news       Related news              --symbol AAPL [--limit 10] [--json]
  compare    Compare multiple stocks   --symbols AAPL,MSFT,GOOG [--json]
  search     Search quotes and news    --query "electric vehicle" [--json]
  market     Market overview           --market us_market|hk_market|... [--json]
  screen     Preset stock screener     --preset day_gainers [--region US] [--count 25] [--json]
  download   Download OHLCV to CSV     --symbols AAPL,MSFT --period 1y [--output file.csv]

Symbol formats: AAPL (US), 600519.SS / 000858.SZ (A-share), 0700.HK (HK),
  7203.T (JP), SHEL.L (UK), ^GSPC (index), BTC-USD (crypto)`);
}

async function main() {
  const argv = process.argv.slice(2);
  const cmd = argv[0];
  if (!cmd || cmd === "-h" || cmd === "--help" || !COMMANDS[cmd]) {
    usage();
    process.exit(cmd && !COMMANDS[cmd] ? 1 : 0);
  }
  const a = parseArgs(argv.slice(1));
  const args = normalize(cmd, a);

  const needsSymbol = ["history", "info", "financials", "holders", "dividends", "options", "analyst", "news"];
  const needsSymbols = ["quote", "compare", "download"];
  if (needsSymbol.includes(cmd) && !args.symbol) {
    console.error(`ERROR: ${cmd} requires --symbol`);
    process.exit(1);
  }
  if (needsSymbols.includes(cmd) && !args.symbols) {
    console.error(`ERROR: ${cmd} requires --symbols`);
    process.exit(1);
  }
  if (cmd === "search" && !args.query) {
    console.error("ERROR: search requires --query");
    process.exit(1);
  }

  try {
    await COMMANDS[cmd](args);
  } catch (e) {
    const name = e?.name || "Error";
    const msg = e?.message || String(e);
    if (/RateLimit|Too Many Requests|429/i.test(name + msg)) {
      console.error("ERROR: Yahoo Finance rate limit hit. Wait a few minutes and retry.");
    } else if (/HTTPError|ConnectionError|ENOTFOUND|ETIMEDOUT|fetch failed|network/i.test(name + msg)) {
      console.error(`ERROR: Network error - ${msg}`);
    } else {
      console.error(`ERROR: ${name}: ${msg}`);
    }
    process.exit(1);
  }
}

main();
