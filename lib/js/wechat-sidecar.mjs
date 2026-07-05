#!/usr/bin/env node
import crypto from "node:crypto";
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { fileURLToPath } from "node:url";

const FIXED_BASE_URL = "https://ilinkai.weixin.qq.com";
const BOT_TYPE = process.env.WECHAT_BOT_TYPE || "3";
const CHANNEL_VERSION = process.env.WECHAT_CHANNEL_VERSION || "2.4.3";
const ILINK_APP_ID = process.env.WECHAT_ILINK_APP_ID || "bot";
const CLIENT_VERSION = String(buildClientVersion(CHANNEL_VERSION));

const ROOT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ACCOUNT_PATH = path.resolve(process.env.WECHAT_ACCOUNT_PATH || path.join(ROOT_DIR, "conf/wechat/account.json"));
const SYNC_BUF_PATH = path.resolve(
  process.env.WECHAT_SYNC_BUF_PATH || path.join(ROOT_DIR, "runtime/wechat/get_updates_buf.txt"),
);
const CODEXCLAW_BASE_URL = (process.env.CODEXCLAW_BASE_URL || "http://127.0.0.1:8080").replace(/\/+$/, "");
const CODEXCLAW_WEBHOOK_PATH = process.env.CODEXCLAW_WECHAT_WEBHOOK_PATH || "/webhook/wechat";
const WEBHOOK_TOKEN = process.env.WECHAT_WEBHOOK_TOKEN || "";
const SIDECAR_HOST = process.env.WECHAT_SIDECAR_HOST || "127.0.0.1";
const SIDECAR_PORT = Number(process.env.WECHAT_SIDECAR_PORT || "8787");
const BOT_AGENT = process.env.WECHAT_BOT_AGENT || "CodexClaw/0.1";
const LONG_POLL_TIMEOUT_MS = Number(process.env.WECHAT_LONG_POLL_TIMEOUT_MS || "35000");
const CODEXCLAW_TIMEOUT_MS = Number(process.env.CODEXCLAW_WECHAT_TIMEOUT_MS || "300000");

const contextTokens = new Map();
const activeInbound = new Set();

function setContextToken(key, token) {
  if (contextTokens.size > 1000) {
    const firstKey = contextTokens.keys().next().value;
    contextTokens.delete(firstKey);
  }
  contextTokens.set(key, token);
}

process.on("unhandledRejection", (error) => {
  console.error(`unhandledRejection: ${String(error)}`);
});
process.on("uncaughtException", (error) => {
  console.error(`uncaughtException: ${String(error)}`);
  process.exit(1);
});

function usage() {
  console.log(`Usage:
  node lib/js/wechat-sidecar.mjs login
  node lib/js/wechat-sidecar.mjs run

Environment:
  CODEXCLAW_BASE_URL=http://127.0.0.1:8080
  WECHAT_WEBHOOK_TOKEN=<same as CodexClaw conf/.env>
  WECHAT_ACCOUNT_PATH=./conf/wechat/account.json
  WECHAT_SIDECAR_HOST=127.0.0.1
  WECHAT_SIDECAR_PORT=8787`);
}

function buildClientVersion(version) {
  const parts = String(version).split(".").map((p) => Number.parseInt(p, 10) || 0);
  return ((parts[0] & 0xff) << 16) | ((parts[1] & 0xff) << 8) | (parts[2] & 0xff);
}

function ensureTrailingSlash(rawUrl) {
  return rawUrl.endsWith("/") ? rawUrl : `${rawUrl}/`;
}

function commonHeaders() {
  return {
    "iLink-App-Id": ILINK_APP_ID,
    "iLink-App-ClientVersion": CLIENT_VERSION,
  };
}

function randomWechatUin() {
  const uint32 = crypto.randomBytes(4).readUInt32BE(0);
  return Buffer.from(String(uint32), "utf8").toString("base64");
}

function jsonHeaders(token = "") {
  const headers = {
    "Content-Type": "application/json",
    AuthorizationType: "ilink_bot_token",
    "X-WECHAT-UIN": randomWechatUin(),
    ...commonHeaders(),
  };
  if (token) headers.Authorization = `Bearer ${token}`;
  return headers;
}

async function fetchJson(method, baseUrl, endpoint, body, opts = {}) {
  const url = new URL(endpoint, ensureTrailingSlash(baseUrl));
  const timeoutMs = opts.timeoutMs ?? 15000;
  const controller = timeoutMs > 0 ? new AbortController() : undefined;
  const timer = controller ? setTimeout(() => controller.abort(), timeoutMs) : undefined;
  try {
    const response = await fetch(url, {
      method,
      headers: method === "GET" ? commonHeaders() : jsonHeaders(opts.token || ""),
      body: method === "GET" ? undefined : JSON.stringify(body || {}),
      signal: controller?.signal,
    });
    const text = await response.text();
    if (!response.ok) {
      throw new Error(`${method} ${endpoint} ${response.status}: ${text.slice(0, 300)}`);
    }
    return text ? JSON.parse(text) : {};
  } finally {
    if (timer) clearTimeout(timer);
  }
}

function baseInfo() {
  return {
    channel_version: CHANNEL_VERSION,
    bot_agent: BOT_AGENT,
  };
}

function ensureParentDir(filePath) {
  fs.mkdirSync(path.dirname(filePath), { recursive: true });
}

function readAccount() {
  if (!fs.existsSync(ACCOUNT_PATH)) {
    throw new Error(`missing account file: ${ACCOUNT_PATH}; run login first`);
  }
  const account = JSON.parse(fs.readFileSync(ACCOUNT_PATH, "utf8"));
  if (!account.token || !account.accountId || !account.baseUrl) {
    throw new Error(`invalid account file: ${ACCOUNT_PATH}`);
  }
  return account;
}

function saveAccount(account) {
  ensureParentDir(ACCOUNT_PATH);
  fs.writeFileSync(ACCOUNT_PATH, JSON.stringify(account, null, 2), { mode: 0o600 });
}

function readSyncBuf() {
  try {
    return fs.existsSync(SYNC_BUF_PATH) ? fs.readFileSync(SYNC_BUF_PATH, "utf8") : "";
  } catch {
    return "";
  }
}

function saveSyncBuf(value) {
  ensureParentDir(SYNC_BUF_PATH);
  fs.writeFileSync(SYNC_BUF_PATH, value || "", { mode: 0o600 });
}

function redact(value) {
  const text = String(value || "");
  if (text.length <= 14) return text ? "***" : "";
  return `${text.slice(0, 8)}...${text.slice(-6)}`;
}

async function login() {
  console.log("requesting QR code...");
  const qr = await fetchJson(
    "POST",
    FIXED_BASE_URL,
    `ilink/bot/get_bot_qrcode?bot_type=${encodeURIComponent(BOT_TYPE)}`,
    { local_token_list: [] },
    { timeoutMs: 35000 },
  );
  if (!qr.qrcode || !qr.qrcode_img_content) {
    throw new Error(`unexpected QR response: ${JSON.stringify(qr).slice(0, 300)}`);
  }

  console.log("\nQR URL:");
  console.log(qr.qrcode_img_content);
  console.log("\nUse WeChat to scan the QR code. This waits up to 8 minutes.");
  await tryPrintQr(qr.qrcode_img_content);

  let currentBaseUrl = FIXED_BASE_URL;
  let lastStatus = "";
  const deadline = Date.now() + 8 * 60_000;
  while (Date.now() < deadline) {
    try {
      const endpoint = `ilink/bot/get_qrcode_status?qrcode=${encodeURIComponent(qr.qrcode)}`;
      const status = await fetchJson("GET", currentBaseUrl, endpoint, undefined, { timeoutMs: 35000 });
      if (status.status !== lastStatus) {
        console.log(`status=${status.status}`);
        lastStatus = status.status;
      }
      if (status.status === "scaned_but_redirect" && status.redirect_host) {
        currentBaseUrl = `https://${status.redirect_host}`;
        console.log(`redirected_poll_host=${currentBaseUrl}`);
      }
      if (status.status === "confirmed") {
        if (!status.bot_token || !status.ilink_bot_id) {
          throw new Error(`confirmed but missing token/id: ${JSON.stringify(status)}`);
        }
        const account = {
          token: status.bot_token,
          accountId: status.ilink_bot_id,
          baseUrl: status.baseurl || currentBaseUrl,
          userId: status.ilink_user_id || "",
          savedAt: new Date().toISOString(),
        };
        saveAccount(account);
        console.log("confirmed");
        console.log(`accountId=${redact(account.accountId)}`);
        console.log(`baseUrl=${account.baseUrl}`);
        console.log(`userId=${redact(account.userId)}`);
        console.log(`saved=${ACCOUNT_PATH}`);
        return;
      }
      if (status.status === "expired") throw new Error("QR expired");
      if (status.status === "need_verifycode") {
        console.log("This account requires a verification code. Use the official OpenClaw login flow for now.");
      }
    } catch (error) {
      if (error?.name !== "AbortError") {
        console.log(`poll warning: ${String(error).slice(0, 300)}`);
      }
    }
    await sleep(1000);
  }
  throw new Error("login timed out");
}

async function tryPrintQr(qrUrl) {
  try {
    const qrterm = await import("qrcode-terminal");
    qrterm.default.generate(qrUrl, { small: true });
  } catch {
    console.log("(qrcode-terminal is not installed; open the QR URL above or convert it to a QR code.)");
  }
}

function firstText(msg) {
  for (const item of msg.item_list || []) {
    if (item.type === 1 && item.text_item?.text != null) return String(item.text_item.text);
    if (item.type === 3 && item.voice_item?.text) return String(item.voice_item.text);
  }
  return "";
}

function messageIdentity(msg) {
  return String(msg.message_id || msg.client_id || `${msg.from_user_id || "unknown"}-${msg.create_time_ms || Date.now()}`);
}

async function getUpdates(account, getUpdatesBuf) {
  return fetchJson(
    "POST",
    account.baseUrl,
    "ilink/bot/getupdates",
    {
      get_updates_buf: getUpdatesBuf || "",
      base_info: baseInfo(),
    },
    {
      token: account.token,
      timeoutMs: LONG_POLL_TIMEOUT_MS,
    },
  );
}

async function sendText(account, toUserId, text, contextToken = "") {
  if (!text) return;
  const clientId = `codexclaw-${Date.now()}-${crypto.randomBytes(4).toString("hex")}`;
  const resp = await fetchJson(
    "POST",
    account.baseUrl,
    "ilink/bot/sendmessage",
    {
      msg: {
        from_user_id: "",
        to_user_id: toUserId,
        client_id: clientId,
        message_type: 2,
        message_state: 2,
        item_list: [{ type: 1, text_item: { text } }],
        context_token: contextToken || undefined,
      },
      base_info: baseInfo(),
    },
    {
      token: account.token,
      timeoutMs: 15000,
    },
  );
  const ret = resp.ret ?? resp.errcode ?? 0;
  if (ret !== 0) {
    throw new Error(`sendmessage failed ret=${resp.ret} errcode=${resp.errcode} errmsg=${resp.errmsg || ""}`);
  }
  console.log(`sent to=${redact(toUserId)} clientId=${clientId} chars=${text.length}`);
}

async function postToCodexClaw(account, msg, text) {
  const contextToken = msg.context_token || "";
  if (contextToken) {
    setContextToken(`${account.accountId}:${msg.from_user_id}`, contextToken);
  }

  const headers = { "Content-Type": "application/json" };
  if (WEBHOOK_TOKEN) headers.Authorization = `Bearer ${WEBHOOK_TOKEN}`;

  const body = {
    message_id: messageIdentity(msg),
    account_id: account.accountId,
    user_id: msg.from_user_id,
    text,
    context_token: contextToken,
    timestamp: msg.create_time_ms || Date.now(),
  };

  const controller = CODEXCLAW_TIMEOUT_MS > 0 ? new AbortController() : undefined;
  const timer = controller ? setTimeout(() => controller.abort(), CODEXCLAW_TIMEOUT_MS) : undefined;
  try {
    const response = await fetch(`${CODEXCLAW_BASE_URL}${CODEXCLAW_WEBHOOK_PATH}`, {
      method: "POST",
      headers,
      body: JSON.stringify(body),
      signal: controller?.signal,
    });
    const raw = await response.text();
    if (!response.ok) {
      throw new Error(`CodexClaw webhook ${response.status}: ${raw.slice(0, 300)}`);
    }
    const data = raw ? JSON.parse(raw) : {};
    const replies = Array.isArray(data.replies) ? data.replies : [];
    console.log(`codexclaw replied message_id=${body.message_id} chunks=${replies.length}`);
    for (const reply of replies) {
      const replyText = String(reply || "").trim();
      if (!replyText) continue;
      await sendText(account, msg.from_user_id, replyText, contextToken);
    }
  } finally {
    if (timer) clearTimeout(timer);
  }
}

async function handleInbound(account, msg) {
  const text = firstText(msg).trim();
  if (!text) return;
  const id = messageIdentity(msg);
  if (activeInbound.has(id)) return;
  activeInbound.add(id);
  console.log(`inbound from=${redact(msg.from_user_id)} id=${id} text=${JSON.stringify(text)}`);
  try {
    await postToCodexClaw(account, msg, text);
  } catch (error) {
    console.error(`failed to process inbound id=${id}: ${String(error)}`);
    try {
      await sendText(account, msg.from_user_id, "服务繁忙，请稍后重试。", msg.context_token || "");
    } catch (sendError) {
      console.error(`failed to send fallback reply id=${id}: ${String(sendError)}`);
    }
  } finally {
    activeInbound.delete(id);
  }
}

async function monitor(account) {
  let getUpdatesBuf = readSyncBuf();
  console.log(`wechat monitor started account=${redact(account.accountId)} baseUrl=${account.baseUrl}`);
  while (true) {
    try {
      const resp = await getUpdates(account, getUpdatesBuf);
      if (resp.get_updates_buf) {
        getUpdatesBuf = resp.get_updates_buf;
        saveSyncBuf(getUpdatesBuf);
      }
      const ret = resp.ret ?? 0;
      const errcode = resp.errcode ?? 0;
      if (ret !== 0 || errcode !== 0) {
        console.error(`getupdates api error ret=${ret} errcode=${errcode} errmsg=${resp.errmsg || ""}`);
        await sleep(2000);
        continue;
      }
      for (const msg of resp.msgs || []) {
        void handleInbound(account, msg);
      }
    } catch (error) {
      if (error?.name !== "AbortError") {
        console.error(`getupdates error: ${String(error)}`);
      }
      await sleep(2000);
    }
  }
}

function startHttpServer(account) {
  const server = http.createServer(async (req, res) => {
    try {
      if (req.method === "GET" && req.url === "/healthz") {
        respondJson(res, 200, { status: "ok" });
        return;
      }
      if (req.method === "POST" && req.url === "/send") {
        const body = await readJsonBody(req);
        const to = String(body.to || body.user_id || "").trim();
        const text = String(body.text || "").trim();
        const contextToken = String(body.context_token || contextTokens.get(`${account.accountId}:${to}`) || "");
        if (!to || !text) {
          respondJson(res, 400, { code: 400, msg: "missing to/text" });
          return;
        }
        await sendText(account, to, text, contextToken);
        respondJson(res, 200, { code: 0 });
        return;
      }
      respondJson(res, 404, { code: 404, msg: "not found" });
    } catch (error) {
      respondJson(res, 500, { code: 500, msg: String(error) });
    }
  });
  server.listen(SIDECAR_PORT, SIDECAR_HOST, () => {
    console.log(`wechat sidecar HTTP listening on http://${SIDECAR_HOST}:${SIDECAR_PORT}`);
  });
}

function readJsonBody(req) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    req.on("data", (chunk) => chunks.push(chunk));
    req.on("end", () => {
      try {
        const raw = Buffer.concat(chunks).toString("utf8");
        resolve(raw ? JSON.parse(raw) : {});
      } catch (error) {
        reject(error);
      }
    });
    req.on("error", reject);
  });
}

function respondJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, {
    "Content-Type": "application/json; charset=utf-8",
    "Content-Length": Buffer.byteLength(body),
  });
  res.end(body);
}

async function run() {
  const account = readAccount();
  startHttpServer(account);
  await monitor(account);
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

const command = process.argv[2] || "help";
try {
  if (command === "login") {
    await login();
  } else if (command === "run") {
    await run();
  } else {
    usage();
    process.exit(command === "help" || command === "-h" || command === "--help" ? 0 : 1);
  }
} catch (error) {
  console.error(String(error));
  process.exit(1);
}
