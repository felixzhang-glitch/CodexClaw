#!/usr/bin/env node
/**
 * IQS Multimodal Search Script (多模态搜索-搜图)
 * Usage: node imagesearch.mjs --query "成都大熊猫" [options]
 * API doc: https://help.aliyun.com/zh/document_detail/3020713.html
 */
const API_ENDPOINT = 'https://cloud-iqs.aliyuncs.com/search/multimodal';

const VALID_ENGINE_TYPES = ['MultimodalSpeed', 'MultimodalSpeedAdvanced'];

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

async function imageSearch(options) {
  const apiKey = await loadApiKey();
  if (!apiKey) {
    throw new Error('ALIYUN_IQS_API_KEY environment variable not set');
  }

  if (!options.query || typeof options.query !== 'string') {
    throw new Error('Query is required. Use --query "搜索词"');
  }
  if (options.query.length < 1 || options.query.length > 50) {
    throw new Error('Query length must be between 1 and 50 characters');
  }

  if (options.engineType && !VALID_ENGINE_TYPES.includes(options.engineType)) {
    throw new Error(`Invalid engineType "${options.engineType}". Valid values: ${VALID_ENGINE_TYPES.join(', ')}`);
  }

  const advancedParams = {};
  if (options.numResults !== undefined) {
    const numResults = parseInt(options.numResults, 10);
    if (isNaN(numResults) || numResults < 1 || numResults > 30) {
      throw new Error('numResults must be a number between 1 and 30');
    }
    advancedParams.numResults = String(numResults);
  }
  if (options.excludeSites) {
    advancedParams.excludeSites = String(options.excludeSites);
  }

  const body = {
    query: options.query,
    engineType: options.engineType || 'MultimodalSpeed'
  };
  if (Object.keys(advancedParams).length > 0) {
    body.advancedParams = advancedParams;
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

    return {
      imageItems: formatResults(data.imageItems || []),
      meta: {
        requestId: data.requestId,
        searchTime: data.searchInformation?.searchTime,
        engineType: data.queryContext?.engineType || body.engineType,
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
  return items.map((item, index) => ({
    rank: index + 1,
    title: item.title,
    imageUrl: item.imageUrl,
    hostPageUrl: item.hostPageUrl,
    width: item.width,
    height: item.height,
    publishedTime: item.publishedTime
  }));
}

const args = parseArgs(process.argv.slice(2));
imageSearch(args).then(results => {
  console.log(JSON.stringify(results, null, 2));
}).catch(err => {
  console.error(JSON.stringify({ error: err.message }, null, 2));
  process.exit(1);
});
