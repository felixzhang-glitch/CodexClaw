#!/usr/bin/env node
/**
 * IQS ReadPage Script (网页解析)
 * Usage: node readpage.mjs --url "https://example.com" [options]
 * API docs:
 *   标准版: https://help.aliyun.com/zh/document_detail/2983380.html
 *   增强版: https://help.aliyun.com/zh/document_detail/2990240.html
 */

const ENDPOINTS = {
  basic: 'https://cloud-iqs.aliyuncs.com/readpage/basic',
  scrape: 'https://cloud-iqs.aliyuncs.com/readpage/scrape'
};

const VALID_FORMATS = ['markdown', 'text', 'html', 'rawHtml', 'screenshot'];
const VALID_READABILITY_MODES = ['none', 'normal', 'article'];
// IQS 定制失败码（成功时 statusCode 为目标站 HttpCode）
const IQS_FAILURE_CODES = new Set([4030, 4080, 4290, 5010]);
const IQS_FAILURE_MESSAGES = {
  4030: 'Security restrictions on the target site (robots.txt etc.)',
  4080: 'Request target url timeout',
  4290: 'The domain has reached the rate limit',
  5010: 'Unknown error'
};

function parseArgs(args) {
  const options = {};
  for (let i = 0; i < args.length; i++) {
    const arg = args[i];
    if (arg.startsWith('--')) {
      const key = arg.slice(2);
      const nextArg = args[i + 1];
      if (nextArg && !nextArg.startsWith('--')) {
        if (nextArg === 'true') {
          options[key] = true;
        } else if (nextArg === 'false') {
          options[key] = false;
        } else {
          options[key] = nextArg;
        }
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

function parseFormats(formatsOpt) {
  if (!formatsOpt || formatsOpt === true) {
    return ['markdown'];
  }
  const formats = String(formatsOpt).split(',').map(s => s.trim()).filter(Boolean);
  for (const f of formats) {
    if (!VALID_FORMATS.includes(f)) {
      throw new Error(`Invalid format "${f}". Valid values: ${VALID_FORMATS.join(', ')}`);
    }
  }
  return [...new Set(formats)];
}

function parseActions(actionsOpt) {
  if (!actionsOpt || actionsOpt === true) {
    return null;
  }
  let actions;
  try {
    actions = JSON.parse(actionsOpt);
  } catch {
    throw new Error('--actions must be a valid JSON array, e.g. \'[{"type":"wait","duration":800}]\'');
  }
  if (!Array.isArray(actions) || actions.length === 0) {
    throw new Error('--actions must be a non-empty JSON array');
  }
  if (actions.length > 20) {
    throw new Error('--actions supports at most 20 steps');
  }
  for (const step of actions) {
    if (!step || (step.type !== 'wait' && step.type !== 'eval')) {
      throw new Error('Each action step must have type "wait" or "eval"');
    }
  }
  return actions;
}

async function readPage(options) {
  const apiKey = await loadApiKey();
  if (!apiKey) {
    throw new Error('ALIYUN_IQS_API_KEY environment variable not set');
  }

  if (!options.url) {
    throw new Error('URL is required. Use --url "https://example.com"');
  }
  if (!String(options.url).startsWith('http://') && !String(options.url).startsWith('https://')) {
    throw new Error('URL must start with http:// or https://');
  }

  const mode = options.mode || 'scrape';
  if (!ENDPOINTS[mode]) {
    throw new Error(`Invalid mode "${mode}". Valid values: basic, scrape`);
  }

  if (options.pageTimeout !== undefined) {
    const pageTimeout = parseInt(options.pageTimeout, 10);
    if (isNaN(pageTimeout) || pageTimeout < 0 || pageTimeout > 100000) {
      throw new Error('pageTimeout must be a number between 0ms and 100000ms (100s)');
    }
  }

  const actions = parseActions(options.actions);
  if (actions && mode === 'basic') {
    throw new Error('--actions is only supported in scrape mode');
  }

  let maxAge;
  if (options.maxAge !== undefined) {
    maxAge = parseInt(options.maxAge, 10);
    if (isNaN(maxAge) || maxAge < 0) {
      throw new Error('maxAge must be a non-negative integer (seconds)');
    }
  }

  const formats = parseFormats(options.formats || options.format);

  let readabilityMode = options.readabilityMode;
  if (readabilityMode && !VALID_READABILITY_MODES.includes(readabilityMode)) {
    throw new Error(`Invalid readabilityMode "${readabilityMode}". Valid values: ${VALID_READABILITY_MODES.join(', ')}`);
  }
  if (!readabilityMode) {
    readabilityMode = options.extractArticle ? 'article' : 'none';
  }

  const readability = { readabilityMode };
  if (options.excludeImages) {
    readability.excludeAllImages = true;
  }
  if (options.excludeLinks) {
    readability.excludeAllLinks = true;
  }
  if (options.excludedTags && options.excludedTags !== true) {
    readability.excludedTags = String(options.excludedTags).split(',').map(s => s.trim()).filter(Boolean);
  }

  const pageTimeout = parseInt(options.pageTimeout, 10) || 10000;
  const body = {
    url: options.url,
    formats,
    pageTimeout,
    readability
  };
  if (maxAge !== undefined) {
    body.maxAge = maxAge;
  }
  if (actions) {
    body.actions = actions;
  }

  // 接口在 pageTimeout + 6000ms 内完成；客户端超时默认再多给余量，可用 --timeout 覆盖
  const timeoutDuration = parseInt(options.timeout, 10) || (pageTimeout + 15000);
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutDuration);

  try {
    const response = await fetch(ENDPOINTS[mode], {
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

    const pageData = data.data;
    if (pageData && IQS_FAILURE_CODES.has(pageData.statusCode)) {
      throw new Error(
        `ReadPage failed (statusCode ${pageData.statusCode}): ${IQS_FAILURE_MESSAGES[pageData.statusCode]}`
      );
    }

    return formatContent(pageData, formats, {
      includeLinks: Boolean(options.includeLinks),
      requestId: data.requestId
    });
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error(`Request timed out after ${timeoutDuration}ms`);
    }
    throw error;
  }
}

function formatContent(data, formats, { includeLinks, requestId }) {
  if (!data) {
    return { title: null, url: null, statusCode: null, contents: {}, requestId };
  }

  const result = {
    title: data.metadata?.title,
    url: data.metadata?.url,
    statusCode: data.statusCode,
    metadata: {
      redirectedUrl: data.metadata?.redirectedUrl,
      publishedDate: data.metadata?.publishedDate,
      lastModified: data.metadata?.lastModified,
      author: data.metadata?.author,
      siteName: data.metadata?.siteName,
      description: data.metadata?.description,
      contentType: data.metadata?.contentType,
      language: data.metadata?.language,
      schemaType: data.metadata?.schemaType,
      pageType: data.metadata?.pageType,
      pdfParse: data.metadata?.pdfParse
    },
    contents: {},
    requestId
  };

  for (const format of formats) {
    if (data[format] != null) {
      result.contents[format] = data[format];
    }
  }

  if (includeLinks && data.links) {
    result.links = data.links;
  }

  for (const key of Object.keys(result.metadata)) {
    if (result.metadata[key] === null || result.metadata[key] === undefined) {
      delete result.metadata[key];
    }
  }

  return result;
}

const args = parseArgs(process.argv.slice(2));
readPage(args).then(result => {
  console.log(JSON.stringify(result, null, 2));
}).catch(err => {
  console.error(JSON.stringify({ error: err.message }, null, 2));
  process.exit(1);
});
