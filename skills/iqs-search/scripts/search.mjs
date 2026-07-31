#!/usr/bin/env node
/**
 * IQS Search Script
 * Usage: node search.mjs --query "search terms" [options]
 */
const API_ENDPOINT = 'https://cloud-iqs.aliyuncs.com/search/unified';

/**
 * Parse command line arguments
 * @param {string[]} args - Process arguments
 * @returns {Object} Parsed options
 */
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

/**
 * Load API key from environment or config file
 * @returns {string|null} API key
 */
async function loadApiKey() {
  // First check environment variable
  if (process.env.ALIYUN_IQS_API_KEY) {
    return process.env.ALIYUN_IQS_API_KEY;
  }

  // Try loading from config file
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

/**
 * Execute search query
 * @param {Object} options - Search options
 * @returns {Promise<Array>} Formatted search results
 */
async function search(options) {
  const apiKey = await loadApiKey();
  if (!apiKey) {
    throw new Error('ALIYUN_IQS_API_KEY environment variable not set');
  }

  if (!options.query) {
    throw new Error('Query is required. Use --query "search terms"');
  }

  // Validate query length
  if (typeof options.query === 'string' && (options.query.length < 1 || options.query.length > 500)) {
    throw new Error('Query length must be between 1 and 500 characters');
  }

  // Validate numResults range
  if (options.numResults !== undefined) {
    const numResults = parseInt(options.numResults, 10);
    if (isNaN(numResults) || numResults < 1 || numResults > 10) {
      throw new Error('numResults must be a number between 1 and 10');
    }
  }

  // 天气等垂类场景需要 locationInfo，且仅 engineType=Generic 时 sceneItems 才会返回（参考阿里云文档 2883041），
  // 故提供 --city/--ip 且未显式指定 engineType 时默认切换为 Generic
  const hasLocation = Boolean(options.city || options.ip);
  const body = {
    query: options.query,
    engineType: options.engineType || (hasLocation ? 'Generic' : 'LiteAdvanced'),
    timeRange: options.timeRange || 'NoLimit',
    contents: {
      mainText: options.contents !== 'summary',  // 默认为 true，除非显式指定为 'summary'
      summary: options.contents == 'summary'
    }
  };

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

  // Set the number of results if specified
  if (options.numResults) {
    body.numResults = parseInt(options.numResults, 10);
  }

  // Set timeout (default 10 seconds)
  const timeout = parseInt(options.timeout, 10) || 10000;

  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(API_ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-API-Key': apiKey,
        'User-Agent': 'AlibabaCloud-Agent-Skills/alibabacloud-iqs-search',
        'x-iqs-source': 'skill.alibabacloud-iqs-search',
      },
      body: JSON.stringify(body),
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    const data = await response.json();

    if (data.errorCode) {
      throw new Error(`${data.errorCode}: ${data.errorMessage}`);
    }

    // Format results and apply numResults limit if specified
    let formattedResults = formatResults(data.pageItems || []);

    if (options.numResults) {
      const limit = parseInt(options.numResults, 10);
      formattedResults = formattedResults.slice(0, limit);
    }

    // 垂类场景结果（天气/时间等）比网页召回更准确，有召回时优先输出；
    // 无 sceneItems 时保持纯数组输出，避免破坏既有用法
    const sceneItems = formatSceneItems(data.sceneItems || []);
    if (sceneItems.length > 0) {
      return { sceneItems, pageItems: formattedResults };
    }

    return formattedResults;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error(`Request timeout after ${timeout}ms`);
    }
    throw error;
  }
}

/**
 * Format search results
 * @param {Array} items - Raw search results
 * @returns {Array} Formatted results
 */
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

    // Include summary if it exists in the item
    if (item.summary) {
      formattedItem.summary = item.summary;
    }

    if (item.mainText) {
      formattedItem.mainText = item.mainText;
    }

    return formattedItem;
  });
}

/**
 * Format scene items (structured vertical results, e.g. weather/time)
 * @param {Array} items - Raw scene items
 * @returns {Array} Scene items with detail parsed as JSON when possible
 */
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

// Parse CLI arguments and execute
const args = parseArgs(process.argv.slice(2));
search(args).then(results => {
  console.log(JSON.stringify(results, null, 2));
}).catch(err => {
  console.error(JSON.stringify({ error: err.message }, null, 2));
  process.exit(1);
});
