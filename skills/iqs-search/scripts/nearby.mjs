#!/usr/bin/env node
/**
 * IQS Nearby POI Search Script (CommonQueryByScene)
 * Usage: node nearby.mjs --query "杭州灵隐寺附近5km的高档酒店" [options]
 *
 * 调用阿里云 IQS 周边查询增强版 API（自然语言 POI 查询），
 * 该 API 为阿里云 OpenAPI（ROA 风格），使用 AK/SK ACS3-HMAC-SHA256 签名，
 * 不支持 IQS API-Key。参考文档：https://help.aliyun.com/zh/document_detail/2858275.html
 */
import crypto from 'crypto';

const HOST = 'iqs.cn-zhangjiakou.aliyuncs.com';
const PATHNAME = '/amap-function-call-agent/iqs-agent-service/v2/nl/common';
const API_ACTION = 'CommonQueryByScene';
const API_VERSION = '2024-07-12';

const VALID_SCENES = ['hotels', 'attractions', 'restaurants', 'entertainment'];

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
 * Load Aliyun AK/SK from environment or config file
 * 优先级：环境变量 > ~/.alibabacloud/iqs/env（与 API-Key 配置文件共用）
 * @returns {Promise<{accessKeyId: string, accessKeySecret: string}|null>} Credentials
 */
async function loadCredentials() {
  let accessKeyId = process.env.ALIBABA_CLOUD_ACCESS_KEY_ID;
  let accessKeySecret = process.env.ALIBABA_CLOUD_ACCESS_KEY_SECRET;

  if (accessKeyId && accessKeySecret) {
    return { accessKeyId, accessKeySecret };
  }

  try {
    const fs = await import('fs');
    const path = await import('path');
    const os = await import('os');
    const configPath = path.join(os.homedir(), '.alibabacloud', 'iqs', 'env');

    if (fs.existsSync(configPath)) {
      const content = fs.readFileSync(configPath, 'utf-8');
      const idMatch = content.match(/ALIBABA_CLOUD_ACCESS_KEY_ID=(.+)/);
      const secretMatch = content.match(/ALIBABA_CLOUD_ACCESS_KEY_SECRET=(.+)/);
      if (idMatch && secretMatch) {
        return {
          accessKeyId: idMatch[1].trim(),
          accessKeySecret: secretMatch[1].trim()
        };
      }
    }
  } catch {
    // Config file not found or unreadable
  }

  return null;
}

/**
 * Build ACS3-HMAC-SHA256 signed headers for a ROA-style POST request
 * 签名规范参考：https://help.aliyun.com/zh/sdk/product-overview/v3-request-structure-and-signature
 * @param {Object} credentials - { accessKeyId, accessKeySecret }
 * @param {string} bodyStr - JSON request body string
 * @returns {Object} HTTP headers including Authorization
 */
function buildSignedHeaders(credentials, bodyStr) {
  const hashedPayload = crypto.createHash('sha256').update(bodyStr, 'utf-8').digest('hex');
  const headers = {
    'host': HOST,
    'x-acs-action': API_ACTION,
    'x-acs-version': API_VERSION,
    'x-acs-date': new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
    'x-acs-signature-nonce': crypto.randomUUID(),
    'x-acs-content-sha256': hashedPayload
  };

  // CanonicalHeaders/SignedHeaders：header 名小写并按字典序排序
  const sortedKeys = Object.keys(headers).sort();
  const canonicalHeaders = sortedKeys.map(k => `${k}:${String(headers[k]).trim()}\n`).join('');
  const signedHeaders = sortedKeys.join(';');

  const canonicalRequest = [
    'POST',
    PATHNAME,
    '',  // CanonicalQueryString：本接口无 query 参数
    canonicalHeaders,
    signedHeaders,
    hashedPayload
  ].join('\n');

  const hashedCanonicalRequest = crypto.createHash('sha256').update(canonicalRequest, 'utf-8').digest('hex');
  const stringToSign = `ACS3-HMAC-SHA256\n${hashedCanonicalRequest}`;
  const signature = crypto.createHmac('sha256', credentials.accessKeySecret)
    .update(stringToSign, 'utf-8')
    .digest('hex');

  headers['Authorization'] =
    `ACS3-HMAC-SHA256 Credential=${credentials.accessKeyId},SignedHeaders=${signedHeaders},Signature=${signature}`;
  headers['Content-Type'] = 'application/json';
  return headers;
}

/**
 * Execute nearby POI query
 * @param {Object} options - Query options
 * @returns {Promise<Array>} Formatted POI results
 */
async function nearbySearch(options) {
  const credentials = await loadCredentials();
  if (!credentials) {
    throw new Error(
      'Aliyun AK/SK not configured. Set ALIBABA_CLOUD_ACCESS_KEY_ID and ALIBABA_CLOUD_ACCESS_KEY_SECRET ' +
      'via environment variables or ~/.alibabacloud/iqs/env'
    );
  }

  if (!options.query || typeof options.query !== 'string') {
    throw new Error('Query is required. Use --query "自然语言周边查询，如：杭州灵隐寺附近5km的高档酒店"');
  }

  if (options.scene && !VALID_SCENES.includes(options.scene)) {
    throw new Error(`Invalid scene "${options.scene}". Valid values: ${VALID_SCENES.join(', ')}`);
  }

  if (options.searchModel && !['single', 'normal'].includes(options.searchModel)) {
    throw new Error('searchModel must be "single" or "normal"');
  }

  const body = {
    query: options.query
  };
  if (options.scene) {
    body.querySceneEnumCode = options.scene;
  }
  if (options.limit) {
    const limit = parseInt(options.limit, 10);
    if (isNaN(limit) || limit < 1) {
      throw new Error('limit must be a positive number');
    }
    body.limit = limit;
  }
  if (options.searchModel) {
    body.searchModel = options.searchModel;
  }

  const bodyStr = JSON.stringify(body);
  const headers = buildSignedHeaders(credentials, bodyStr);

  const timeout = parseInt(options.timeout, 10) || 10000;
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const response = await fetch(`https://${HOST}${PATHNAME}`, {
      method: 'POST',
      headers,
      body: bodyStr,
      signal: controller.signal
    });

    clearTimeout(timeoutId);

    const data = await response.json();

    // OpenAPI 错误返回结构为 { Code, Message, RequestId }
    if (!response.ok || data.Code) {
      const code = data.Code || response.status;
      const message = data.Message || JSON.stringify(data);
      throw new Error(`${code}: ${message}`);
    }

    return formatResults(data.data || []);
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error(`Request timeout after ${timeout}ms`);
    }
    throw error;
  }
}

/**
 * Format POI results
 * single 模式服务端仅返回部分字段，缺失字段过滤后原样精简输出
 * @param {Array} items - Raw POI list
 * @returns {Array} Formatted results
 */
function formatResults(items) {
  return items.map((item, index) => {
    const formattedItem = {
      rank: index + 1,
      name: item.name,
      types: item.types,
      address: item.address,
      cityName: item.cityName,
      districtName: item.districtName,
      distanceMeter: item.distanceMeter,
      latitude: item.latitude,
      longitude: item.longitude
    };

    if (item.metadata) {
      const { phone, score, mainTag, businessArea, averageSpend, dailyOpeningHours, weeklyOpeningDays } = item.metadata;
      formattedItem.metadata = { phone, score, mainTag, businessArea, averageSpend, dailyOpeningHours, weeklyOpeningDays };
    }

    if (Array.isArray(item.images) && item.images.length > 0) {
      formattedItem.images = item.images
        .filter(img => img && img.url)
        .map(img => ({ title: img.title, url: img.url }));
    }

    // 过滤空值字段，保持输出精简
    for (const key of Object.keys(formattedItem)) {
      if (formattedItem[key] === null || formattedItem[key] === undefined) {
        delete formattedItem[key];
      }
    }
    return formattedItem;
  });
}

// Parse CLI arguments and execute
const args = parseArgs(process.argv.slice(2));
nearbySearch(args).then(results => {
  console.log(JSON.stringify(results, null, 2));
}).catch(err => {
  console.error(JSON.stringify({ error: err.message }, null, 2));
  process.exit(1);
});
