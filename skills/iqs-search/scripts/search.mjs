#!/usr/bin/env node
/**
 * IQS Search Script (联网搜索-搜文)
 * Usage: node search.mjs --query "search terms" [options]
 * API doc: https://help.aliyun.com/zh/document_detail/2883041.html
 */
const API_ENDPOINT = 'https://cloud-iqs.aliyuncs.com/search/unified';

const VALID_ENGINE_TYPES = ['Generic', 'GenericAdvanced', 'LiteAdvanced', 'Deep'];
const VALID_CONTENT_TYPES = ['mainText', 'markdownText', 'richMainBody', 'summary'];
const VALID_CATEGORIES = ['finance', 'law', 'medical', 'internet', 'tax', 'news_province', 'news_center'];
const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

function parseArgs(args) {
  const options = {};
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg.startsWith('--')) {
      const key = arg.slice(2);
      const nextArg = args[i + 1];
      if (nextArg && !nextArg.startsWith('--')) {
        options[key] = nextArg;
        i++;
      } else {
        options[key] = true;
      }
    }
  }
  return options;
}

async function loadApiKey() {
  if (process.env.ALIYUN_IQS_API_KEY) {
    return process.env.ALIYUN_IQS_API_KEY;
  }

  try {
    const fs = await import('fs');
    const path = await import('path');
    const os = await import('os');
    const configPath = path.join(os.homedir(), '.alibabacloud', 'iqs', 'env');

    if (fs.existsSync(configPath)) {
      const content = fs.readFileSync(configPath, 'utf-8');
      const match = content.match(/ALIYUN_IQS_API_KEY=(.+)/);
      if (match) {
        return match[1].trim();
      }
    }
  } catch {
    // Config file not found or unreadable
  }

  return null;
}

function parseContents(contentsOpt) {
  const flags = { mainText: false, markdownText: false, richMainBody: false, summary: false };
  if (!contentsOpt || contentsOpt === true) {
    return flags;
  }
  const requested = String(contentsOpt).split(',').map(s => s.trim()).filter(Boolean);
  for (const name of requested) {
    if (!VALID_CONTENT_TYPES.includes(name)) {
      throw new Error(`Invalid contents "${name}". Valid values: ${VALID_CONTENT_TYPES.join(', ')}`);
    }
    flags[name] = true;
  }
  return flags;
}

async function search(options) {
  const apiKey = await loadApiKey();
  if (!apiKey) {
    throw new Error('ALIYUN_IQS_API_KEY environment variable not set');
  }

  if (!options.query || typeof options.query !== 'string') {
    throw new Error('Query is required. Use --query "search terms"');
  }
  if (options.query.length < 1 || options.query.length > 500) {
    throw new Error('Query length must be between 1 and 500 characters');
  }

  if (options.engineType && !VALID_ENGINE_TYPES.includes(options.engineType)) {
    throw new Error(`Invalid engineType "${options.engineType}". Valid values: ${VALID_ENGINE_TYPES.join(', ')}`);
  }

  if (options.category) {
    const cats = String(options.category).split(',').map(s => s.trim()).filter(Boolean);
    for (const c of cats) {
      if (!VALID_CATEGORIES.includes(c)) {
        throw new Error(`Invalid category "${c}". Valid values: ${VALID_CATEGORIES.join(', ')}`);
      }
    }
  }

  const advancedParams = {};
  if (options.numResults !== undefined) {
    const numResults = parseInt(options.numResults, 10);
    if (isNaN(numResults) || numResults < 1 || numResults > 50) {
      throw new Error('numResults must be a number between 1 and 50');
    }
    advancedParams.numResults = String(numResults);
  }
  if (options.startDate) {
    if (!DATE_RE.test(options.startDate)) {
      throw new Error('startDate must be in YYYY-MM-DD format');
    }
    advancedParams.startPublishedDate = options.startDate;
  }
  if (options.endDate) {
    if (!DATE_RE.test(options.endDate)) {
      throw new Error('endDate must be in YYYY-MM-DD format');
    }
    advancedParams.endPublishedDate = options.endDate;
  }

  // 天气等垂类场景需要 locationInfo，且仅 engineType=Generic 时 sceneItems 才会返回，
  // 故提供 --city/--ip 且未显式指定 engineType 时默认切换为 Generic
  const hasLocation = Boolean(options.city || options.ip);
  const engineType = options.engineType || (hasLocation ? 'Generic' : 'LiteAdvanced');

  const body = {
    query: options.query,
    engineType,
    timeRange: options.timeRange || 'NoLimit',
    contents: {
      ...parseContents(options.contents),
      rerankScore: true
    }
  };

  if (Object.keys(advancedParams).length > 0) {
    body.advancedParams = advancedParams;
  }

  if (hasLocation) {
    body.locationInfo = {};
    if (options.city) {
      body.locationInfo.city = options.city;
    }
    if (options.ip) {
      body.locationInfo.ip = options.ip;
    }
  }

  if (options.category) {
    body.category = options.category;
  }

  const timeout = parseInt(options.timeout, 10) || 10000;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
        'User-Agent': 'AlibabaCloud-Agent-Skills/iqs-search',
        'x-iqs-source': 'skill.iqs-search',
      },
      body: JSON.stringify(body),
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    const data = await response.json();

    if (data.errorCode) {
      throw new Error(`${data.errorCode}: ${data.errorMessage}`);
    }

    const pageItems = formatResults(data.pageItems || []);
    const sceneItems = formatSceneItems(data.sceneItems || []);

    return {
      sceneItems,
      pageItems,
      meta: {
        requestId: data.requestId,
        searchTime: data.searchInformation?.searchTime,
        engineType: data.queryContext?.engineType || engineType,
        originalQuery: data.queryContext?.originalQuery?.query,
        rewrite: data.queryContext?.rewrite,
        costCredits: data.costCredits
      }
    };
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error(`Request timeout after ${timeout}ms`);
    }
    throw error;
  }
}

function formatResults(items) {
  return items.map((item, index) => {
    const formattedItem = {
      rank: index + 1,
      title: item.title,
      url: item.link,
      snippet: item.snippet,
      source: item.hostname,
      publishedTime: item.publishedTime,
      relevance: item.rerankScore
    };

    if (item.images?.length) {
      formattedItem.images = item.images;
    }
    if (item.summary) {
      formattedItem.summary = item.summary;
    }
    if (item.mainText) {
      formattedItem.mainText = item.mainText;
    }
    if (item.markdownText) {
      formattedItem.markdownText = item.markdownText;
    }
    if (item.richMainBody) {
      formattedItem.richMainBody = item.richMainBody;
    }

    return formattedItem;
  });
}

function formatSceneItems(items) {
  return items.map(item => {
    let detail = item.detail;
    if (typeof detail === 'string') {
      try {
        detail = JSON.parse(detail);
      } catch {
        // detail 不是合法 JSON 时保留原始字符串
      }
    }
    return { type: item.type, detail };
  });
}

const args = parseArgs(process.argv.slice(2));
search(args).then(results => {
  console.log(JSON.stringify(results, null, 2));
}).catch(err => {
  console.error(JSON.stringify({ error: err.message }, null, 2));
  process.exit(1);
});
