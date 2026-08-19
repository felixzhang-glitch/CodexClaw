#!/usr/bin/env python3
"""推送前密钥扫描器（Python 3 标准库，无第三方依赖）。

用法：
    secret_scan.py --range <base>..<head>   仅扫描该区间新增行（pre-push 主路径）
    secret_scan.py --staged                 仅扫描已 staged 的新增行
    secret_scan.py --all                    全量扫描所有 git 跟踪文件
    secret_scan.py --files a.py b.md        扫描指定文件
    secret_scan.py --print-fingerprints     附带输出可粘贴进 allowlist 的指纹行

退出码：0 = 干净；1 = 发现疑似密钥；2 = 扫描器自身错误（钩子按阻断处理）。
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
HOOK_DIR = os.path.dirname(os.path.abspath(__file__))
ALLOWLIST_FILES = ("secret-allowlist.txt", "secret-allowlist.local.txt")

MAX_FILE_BYTES = 1024 * 1024
MAX_LINE_CHARS = 2000
MAX_ADDED_LINES_PER_FILE = 20000

INLINE_IGNORE_RE = re.compile(r"secret-scan:\s*ignore|pragma:\s*allowlist\s+secret")


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: "re.Pattern[str]"
    # 需要熵/形态二次确认（用于关键字类弱规则）
    entropy: bool = False
    # 命中后取哪个分组作为密钥值；0 表示整个匹配
    group: int = 0


def _r(name: str, pattern: str, *, entropy: bool = False, group: int = 1) -> Rule:
    return Rule(name=name, pattern=re.compile(pattern), entropy=entropy, group=group)


# ---------------------------------------------------------------------------
# 规则集：厂商前缀高置信规则优先，关键字类弱规则最后且受熵门控
# ---------------------------------------------------------------------------

RULES: tuple[Rule, ...] = (
    # --- 项目专属环境变量（命中即报，不做熵门控；置顶以便报告里优先给出项目语义）---
    _r(
        "codeclaw-env-secret",
        r"\b(?:FEISHU_APP_SECRET|FEISHU_VERIFICATION_TOKEN|FEISHU_ENCRYPT_KEY|DASHSCOPE_API_KEY"
        r"|CODEX_API_KEY|WECHAT_WEBHOOK_TOKEN)\s*[:=]\s*['\"]?([^\s'\"#]{8,})",
    ),
    # --- AWS ---
    _r("aws-access-key-id", r"\b((?:AKIA|ASIA|ABIA|ACCA|A3T[A-Z0-9])[A-Z0-9]{16})\b"),
    _r(
        "aws-secret-access-key",
        r"(?i)aws[_\-.]?secret[_\-.]?access[_\-.]?key\w*\s*[:=]\s*['\"]?([A-Za-z0-9/+=]{40})",
    ),
    _r("azure-storage-account-key", r"AccountKey=([A-Za-z0-9+/=]{60,})"),
    _r("azure-sas-token", r"(sv=\d{4}-\d{2}-\d{2}&s[a-z]{1,3}=[^&\s'\"]{1,40}&sig=[A-Za-z0-9%/+=]{20,})"),
    # --- 阿里云 / 腾讯云 / 火山 ---
    _r("alibaba-access-key-id", r"\b(LTAI[A-Za-z0-9]{12,24})\b"),
    _r(
        "alibaba-access-key-secret",
        r"(?i)(?:access[_\-]?key[_\-]?secret|accesskeysecret|ali(?:yun|baba)[_\-]?secret)"
        r"\w*\s*[:=]\s*['\"]?([A-Za-z0-9]{30})\b",
    ),
    _r("alibaba-cli-inline-secret", r"--access-key-secret[=\s]+['\"]?([A-Za-z0-9]{20,})"),
    _r("tencent-secret-id", r"\b(AKID[A-Za-z0-9]{13,32})\b"),
    _r("volcengine-access-key", r"\b(AKLT[A-Za-z0-9_\-]{16,})"),
    # --- 模型服务商 ---
    _r("anthropic-api-key", r"\b(sk-ant-(?:api|admin)\d{2}-[A-Za-z0-9_\-]{80,})"),
    _r(
        "openai-style-prefixed-key",
        r"\b(sk-(?:proj|or|svcacct|admin|live|test)[A-Za-z0-9]*-[A-Za-z0-9_\-]{20,})",
    ),
    # 覆盖 OpenAI / DashScope(sk-+32hex) / DeepSeek / Moonshot / 百炼 等
    _r("openai-style-api-key", r"\b(sk-[A-Za-z0-9]{20,})\b"),
    _r("zhipu-api-key", r"\b([0-9a-f]{32}\.[A-Za-z0-9]{16})\b"),
    _r("google-api-key", r"\b(AIza[0-9A-Za-z_\-]{35})\b"),
    _r("gcp-service-account-json", r"(\"type\"\s*:\s*\"service_account\")"),
    _r("huggingface-token", r"\b(hf_[A-Za-z0-9]{34,})\b"),
    # --- 代码托管 / 包仓库 ---
    _r("github-token", r"\b(gh[pousr]_[A-Za-z0-9]{36,})\b"),
    _r("github-fine-grained-pat", r"\b(github_pat_[A-Za-z0-9_]{60,})\b"),
    _r("gitlab-pat", r"\b(glpat-[A-Za-z0-9_\-]{20,})\b"),
    _r("npm-token", r"\b(npm_[A-Za-z0-9]{36})\b"),
    _r("pypi-token", r"\b(pypi-AgEIcHlwaS5vcmc[A-Za-z0-9_\-]{50,})"),
    _r("docker-registry-auth", r"\"auth\"\s*:\s*\"([A-Za-z0-9+/=]{24,})\""),
    # --- 飞书 / 微信 / 钉钉 ---
    _r("feishu-app-id", r"\b(cli_[a-z0-9]{16})\b"),
    _r("feishu-access-token", r"\b([tu]-g10[A-Za-z0-9_\-]{20,})\b"),
    _r("feishu-bot-webhook", r"open\.feishu\.cn/open-apis/bot/v2/hook/([0-9a-fA-F\-]{20,})"),
    _r("wechat-appid", r"\b(wx[0-9a-f]{16})\b"),
    _r("dingtalk-robot-token", r"dingtalk\.com/robot/send\?access_token=([A-Za-z0-9]{32,})"),
    # --- 其他 SaaS ---
    _r("notion-internal-token", r"\b(secret_[A-Za-z0-9]{43})\b"),
    _r("notion-token-v2", r"\b(ntn_[A-Za-z0-9]{40,})\b"),
    _r("slack-token", r"\b(xox[abprs]-[A-Za-z0-9\-]{10,})\b"),
    _r("slack-webhook", r"hooks\.slack\.com/services/(T[A-Za-z0-9_\-]{6,}/B[A-Za-z0-9_\-]{6,}/[A-Za-z0-9_\-]{20,})"),
    _r("stripe-key", r"\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,})\b"),
    _r("sendgrid-api-key", r"\b(SG\.[A-Za-z0-9_\-]{20,}\.[A-Za-z0-9_\-]{35,})\b"),
    _r("twilio-api-key", r"\b(SK[0-9a-f]{32})\b"),
    _r("telegram-bot-token", r"\b(\d{8,10}:AA[A-Za-z0-9_\-]{33})\b"),
    # --- 私钥 / 令牌 / 连接串 ---
    _r("private-key-block", r"(-----BEGIN (?:[A-Z0-9 ]+ )?PRIVATE KEY(?: BLOCK)?-----)"),
    _r("putty-private-key", r"(PuTTY-User-Key-File)"),  # secret-scan: ignore
    _r("jwt-token", r"\b(eyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,})"),
    _r(
        "uri-with-password",
        r"\b((?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|rediss?|amqps?|ftp|https?|clickhouse|mssql)"
        r"://[^:@/\s'\"]{1,64}:[^@/\s'\"]{3,64}@[^\s'\"<>]{1,128})",
    ),
    _r(
        "authorization-header",
        r"(?i)authorization\s*[:=]\s*['\"]?(?:bearer|basic|token)\s+([A-Za-z0-9._\-+/=]{16,})",
        entropy=True,
    ),
    # --- 关键字类弱规则（熵门控）---
    _r(
        "generic-secret-assignment",
        r"(?i)[A-Za-z0-9_.\-]{0,32}?"
        r"(?:api[_\-]?key|apikey|api[_\-]?secret|secret[_\-]?key|access[_\-]?key[_\-]?secret"
        r"|secret[_\-]?access[_\-]?key|client[_\-]?secret|app[_\-]?secret|encrypt[_\-]?key"
        r"|webhook[_\-]?token|verification[_\-]?token|auth[_\-]?token|access[_\-]?token"
        r"|refresh[_\-]?token|private[_\-]?token|session[_\-]?token|secret|token|password"
        r"|passwd|pwd|credentials?|passphrase)"
        r"[A-Za-z0-9_.\-]{0,32}?\s*(?:=>|:=|[:=])\s*"
        r"['\"]([A-Za-z0-9/+_\-.=~]{16,512})['\"]",
        entropy=True,
    ),
    _r(
        "generic-secret-env-assignment",
        r"(?im)^[+\s]*(?:export\s+)?[A-Z0-9_]{0,32}"
        r"(?:API_KEY|API_SECRET|SECRET_KEY|ACCESS_KEY|ACCESS_KEY_SECRET|SECRET_ACCESS_KEY"
        r"|CLIENT_SECRET|APP_SECRET|ENCRYPT_KEY|WEBHOOK_TOKEN|AUTH_TOKEN|ACCESS_TOKEN"
        r"|REFRESH_TOKEN|SECRET|TOKEN|PASSWORD|PASSWD|CREDENTIAL)"
        r"[A-Z0-9_]{0,32}\s*=\s*['\"]?([A-Za-z0-9/+_\-.=~]{16,512})",
        entropy=True,
    ),
    _r(
        "short-ak-sk-assignment",
        r"(?i)\b(?:ak|sk|as)\s*[:=]\s*['\"]([A-Za-z0-9/+=]{16,})['\"]",
        entropy=True,
    ),
)


# ---------------------------------------------------------------------------
# 危险文件名：新增此类文件直接阻断
# ---------------------------------------------------------------------------

DANGEROUS_PATHS: tuple[tuple[str, str], ...] = (
    (".env", "环境变量文件"),
    (".env.*", "环境变量文件"),
    ("*.pem", "证书/私钥"),
    ("*.key", "私钥"),
    ("*.p12", "PKCS#12 密钥库"),
    ("*.pfx", "PKCS#12 密钥库"),
    ("*.jks", "Java 密钥库"),
    ("*.keystore", "密钥库"),
    ("*.ppk", "PuTTY 私钥"),
    ("id_rsa", "SSH 私钥"),
    ("id_dsa", "SSH 私钥"),
    ("id_ecdsa", "SSH 私钥"),
    ("id_ed25519", "SSH 私钥"),
    ("*.kdbx", "密码库"),
    ("credentials", "凭证文件"),
    ("credentials.json", "凭证文件"),
    ("service-account*.json", "GCP 服务账号密钥"),
    (".npmrc", "含 npm token 风险"),
    (".pypirc", "含 PyPI token 风险"),
    (".netrc", "含明文口令风险"),
    ("conf/wechat/account.json", "微信账号配置（应保持 gitignored）"),
    ("rules/admin.md", "私有规则文件（应保持 gitignored）"),
)

DANGEROUS_PATH_ALLOW = ("*.env.example", ".env.example", "*.example", "*.sample", "*.template")

SKIP_PATH_PATTERNS = (
    "*.lock",
    "package-lock.json",
    "bun.lock",
    "bun.lockb",
    "yarn.lock",
    "poetry.lock",
    "uv.lock",
    "*.min.js",
    "*.min.css",
    "*.map",
    "*.png",
    "*.jpg",
    "*.jpeg",
    "*.gif",
    "*.webp",
    "*.ico",
    "*.svg",
    "*.pdf",
    "*.zip",
    "*.gz",
    "*.tar",
    "*.whl",
    "*.woff",
    "*.woff2",
    "*.ttf",
    "*.pyc",
    ".venv/*",
    "*/.venv/*",
    "node_modules/*",
    "*/node_modules/*",
    "runtime/*",
    "logs/*",
    "*/__pycache__/*",
)

PLACEHOLDER_TOKENS = (
    "your",
    "yours",
    "xxxx",
    "changeme",
    "change_me",
    "change-me",
    "placeholder",
    "example",
    "sample",
    "dummy",
    "fake",
    "mock",
    "redacted",
    "masked",
    "hidden",
    "todo",
    "tbd",
    "insert_",
    "insert-",
    "replace_",
    "replace-",
    "fill_in",
    "notasecret",
    "no_secret",
    "none",
    "null",
    "undefined",
    "lorem",
    "foobar",
    "test_key",
    "testkey",
    "test-token",
    "my_secret",
    "mysecret",
    "s3cret",
    "abc123",
)

DUMMY_HINTS = ("123456", "abcdef", "qwerty", "0000", "1111", "aaaa", "deadbeef", "cafebabe")

SEQUENCES = (
    "abcdefghijklmnopqrstuvwxyz",
    "zyxwvutsrqponmlkjihgfedcba",
    "0123456789",
    "9876543210",
)

IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*)+$")
SNAKE_RE = re.compile(r"^[a-z][a-z0-9_]*$")
SCREAM_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
KEBAB_WORDS_RE = re.compile(r"^[a-z]+(?:[-_][a-z]+){1,}$")
PATHLIKE_RE = re.compile(r"^[.~/]|/(?:[A-Za-z0-9_.\-]+/)+")
VERSIONLIKE_RE = re.compile(r"^v?\d+(?:\.\d+){1,}")
HEX_RE = re.compile(r"^[0-9a-fA-F]+$")


@dataclass(frozen=True)
class Finding:
    path: str
    line_no: int
    rule: str
    secret: str

    @property
    def fingerprint(self) -> str:
        raw = f"{self.path}|{self.rule}|{self.secret}".encode("utf-8", "replace")
        return hashlib.sha1(raw).hexdigest()

    @property
    def masked(self) -> str:
        value = self.secret.strip()
        if len(value) <= 12:
            return value[:2] + "*" * max(len(value) - 2, 3)
        return f"{value[:4]}...{value[-4:]} (len={len(value)})"


class Allowlist:
    """白名单：path/regex/fingerprint 三种条目。"""

    def __init__(self) -> None:
        self.paths: list[str] = []
        self.regexes: list["re.Pattern[str]"] = []
        self.fingerprints: set[str] = set()

    @classmethod
    def load(cls, hook_dir: str = HOOK_DIR) -> "Allowlist":
        allow = cls()
        for name in ALLOWLIST_FILES:
            path = os.path.join(hook_dir, name)
            if os.path.isfile(path):
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    allow.parse(handle.read())
        return allow

    def parse(self, text: str) -> None:
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            kind, _, value = line.partition(":")
            kind, value = kind.strip().lower(), value.strip()
            if not value:
                continue
            if kind == "path":
                self.paths.append(value)
            elif kind == "regex":
                try:
                    self.regexes.append(re.compile(value))
                except re.error as exc:
                    _warn(f"allowlist 正则无效已忽略: {value} ({exc})")
            elif kind == "fingerprint":
                self.fingerprints.add(value.lower())

    def allows_path(self, path: str) -> bool:
        return any(fnmatch.fnmatch(path, pattern) for pattern in self.paths)

    def allows(self, finding: Finding) -> bool:
        if finding.fingerprint.lower() in self.fingerprints:
            return True
        if self.allows_path(finding.path):
            return True
        return any(pattern.search(finding.secret) for pattern in self.regexes)


def _warn(message: str) -> None:
    print(f"[secret-scan] warning: {message}", file=sys.stderr)


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    total = len(value)
    entropy = 0.0
    for char in set(value):
        probability = value.count(char) / total
        entropy -= probability * math.log2(probability)
    return entropy


def is_placeholder(value: str) -> bool:
    """明显的占位符/示例值。"""
    text = value.strip().strip("'\"")
    if not text:
        return True
    lowered = text.lower()
    # 真实密钥不含非 ASCII 字符，含中文等字符的一律视为说明性占位符
    if any(ord(char) > 127 for char in text):
        return True
    if lowered.startswith("${") or lowered.startswith("$(") or text.startswith("$"):
        return True
    if "<" in text or ">" in text or "{{" in text:
        return True
    if any(token in lowered for token in PLACEHOLDER_TOKENS):
        return True
    if len(set(lowered)) <= 3:
        return True
    stripped = lowered.strip("x*.-_0")
    if not stripped:
        return True
    if re.fullmatch(r"[x*\u2026.]{4,}", lowered):
        return True
    return False


def looks_random(value: str) -> bool:
    """弱规则的二次确认：排除标识符/路径/低熵串。"""
    text = value.strip().strip("'\"")
    if len(text) < 16:
        return False
    if IDENTIFIER_RE.match(text) or SNAKE_RE.match(text) or SCREAM_RE.match(text):
        return False
    if KEBAB_WORDS_RE.match(text) or PATHLIKE_RE.match(text) or VERSIONLIKE_RE.match(text):
        return False
    lowered = text.lower()
    if any(hint in lowered for hint in DUMMY_HINTS):
        return False
    if any(lowered in sequence or sequence.startswith(lowered) for sequence in SEQUENCES):
        return False
    for sequence in SEQUENCES:
        if len(lowered) >= 6 and lowered[:6] in sequence and lowered[:8] in sequence + sequence:
            return False
    entropy = shannon_entropy(text)
    alphabet = 16 if HEX_RE.match(text) else 64
    ceiling = math.log2(min(len(text), alphabet))
    if ceiling <= 0:
        return False
    return (entropy / ceiling) >= 0.78


def normalize_path(path: str) -> str:
    """去掉开头的 ./ 前缀（不能用 lstrip，否则 .env 会被削成 env）。"""
    normalized = path.replace("\\", "/").strip()
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return normalized


def path_is_skipped(path: str) -> bool:
    normalized = normalize_path(path)
    return any(fnmatch.fnmatch(normalized, pattern) for pattern in SKIP_PATH_PATTERNS)


def dangerous_path_reason(path: str) -> str | None:
    normalized = normalize_path(path)
    base = os.path.basename(normalized)
    if any(fnmatch.fnmatch(base, ok) or fnmatch.fnmatch(normalized, ok) for ok in DANGEROUS_PATH_ALLOW):
        return None
    for pattern, reason in DANGEROUS_PATHS:
        if fnmatch.fnmatch(base, pattern) or fnmatch.fnmatch(normalized, pattern):
            return reason
    return None


def scan_line(path: str, line_no: int, line: str) -> list[Finding]:
    """扫描单行，返回命中列表。"""
    if INLINE_IGNORE_RE.search(line):
        return []
    text = line[:MAX_LINE_CHARS]
    findings: list[Finding] = []
    # 同一行内同一个值只报一次，由排在前面的高置信规则胜出
    seen: set[str] = set()
    for rule in RULES:
        for match in rule.pattern.finditer(text):
            try:
                value = match.group(rule.group) or match.group(0)
            except (IndexError, re.error):
                value = match.group(0)
            value = value.strip()
            if not value or is_placeholder(value):
                continue
            if rule.entropy and not looks_random(value):
                continue
            if value in seen:
                continue
            seen.add(value)
            findings.append(Finding(path=path, line_no=line_no, rule=rule.name, secret=value))
    return findings


def scan_text(path: str, text: str, start_line: int = 1) -> list[Finding]:
    findings: list[Finding] = []
    for offset, line in enumerate(text.splitlines()):
        findings.extend(scan_line(path, start_line + offset, line))
    return findings


# ---------------------------------------------------------------------------
# git 交互
# ---------------------------------------------------------------------------


def git(*args: str, check: bool = True) -> str:
    result = subprocess.run(
        ["git", *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        errors="replace",
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败: {result.stderr.strip()}")
    return result.stdout


DIFF_FILE_RE = re.compile(r"^\+\+\+ (?:b/)?(.+)$")
HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def parse_diff(diff: str) -> list[Finding]:
    """解析 unified=0 的 diff，仅扫描新增行。"""
    findings: list[Finding] = []
    path: str | None = None
    line_no = 0
    added_count = 0
    skipped_paths: set[str] = set()

    for raw in diff.splitlines():
        if raw.startswith("diff --git"):
            path, line_no, added_count = None, 0, 0
            continue
        if raw.startswith("+++ "):
            target = DIFF_FILE_RE.match(raw)
            candidate = target.group(1).strip() if target else "/dev/null"
            if candidate == "/dev/null":
                path = None
                continue
            path = candidate
            reason = dangerous_path_reason(path)
            if reason:
                findings.append(Finding(path=path, line_no=0, rule="dangerous-file", secret=reason))
            if path_is_skipped(path):
                skipped_paths.add(path)
                path = None
            continue
        if raw.startswith("@@"):
            hunk = HUNK_RE.match(raw)
            line_no = int(hunk.group(1)) if hunk else 0
            continue
        if path is None:
            continue
        if raw.startswith("+") and not raw.startswith("+++"):
            added_count += 1
            if added_count > MAX_ADDED_LINES_PER_FILE:
                _warn(f"{path} 新增行超过 {MAX_ADDED_LINES_PER_FILE} 行，剩余部分跳过")
                path = None
                continue
            findings.extend(scan_line(path, line_no, raw[1:]))
            line_no += 1
    return findings


def diff_findings(args: list[str]) -> list[Finding]:
    diff = git(
        "diff",
        "--no-color",
        "--no-ext-diff",
        "--unified=0",
        "--diff-filter=ACMR",
        "-M",
        *args,
    )
    return parse_diff(diff)


def scan_range(rev_range: str) -> list[Finding]:
    base, _, head = rev_range.partition("..")
    base = base or EMPTY_TREE
    head = head or "HEAD"
    return diff_findings([base, head])


def scan_staged() -> list[Finding]:
    return diff_findings(["--cached"])


def scan_files(paths: list[str]) -> list[Finding]:
    findings: list[Finding] = []
    for path in paths:
        if path_is_skipped(path):
            continue
        reason = dangerous_path_reason(path)
        if reason:
            findings.append(Finding(path=path, line_no=0, rule="dangerous-file", secret=reason))
        if not os.path.isfile(path):
            continue
        try:
            if os.path.getsize(path) > MAX_FILE_BYTES:
                _warn(f"{path} 超过 1MB，跳过")
                continue
            with open(path, "rb") as handle:
                blob = handle.read()
            if b"\0" in blob:
                continue
            findings.extend(scan_text(path, blob.decode("utf-8", "replace")))
        except OSError as exc:
            _warn(f"读取 {path} 失败: {exc}")
    return findings


def scan_all() -> list[Finding]:
    tracked = [line for line in git("ls-files").splitlines() if line.strip()]
    return scan_files(tracked)


# ---------------------------------------------------------------------------
# 输出
# ---------------------------------------------------------------------------

REMEDIATION = """
处置步骤（按顺序）：
  1. 立即轮换该密钥。一旦写入 commit 就应视为已泄露，删除代码不等于撤销泄露。
  2. 清理历史：最近一次提交用 `git commit --amend`；更早的用 `git rebase -i` 或
     `git filter-repo --replace-text`（勿直接 push 覆盖公共分支前先确认协作影响）。
  3. 确认是误报时，把下面的 fingerprint 行追加到
     .qoder/hooks/secret-allowlist.txt（团队共享）或 secret-allowlist.local.txt（仅本机），
     或在该行尾加注释 `secret-scan: ignore`。

紧急放行（仅在完全确认无风险时使用）：
  SKIP_SECRET_SCAN=1 git push ...
"""


def report(findings: list[Finding], *, print_fingerprints: bool) -> None:
    if print_fingerprints:
        for finding in findings:
            print(f"fingerprint:{finding.fingerprint}")
        return
    print("=" * 72, file=sys.stderr)
    print(f"[secret-scan] 发现 {len(findings)} 处疑似敏感信息，已阻断推送：", file=sys.stderr)
    print("=" * 72, file=sys.stderr)
    for finding in findings:
        location = f"{finding.path}:{finding.line_no}" if finding.line_no else finding.path
        print(f"  {location}", file=sys.stderr)
        print(f"    规则: {finding.rule}", file=sys.stderr)
        print(f"    内容: {finding.masked}", file=sys.stderr)
    print(REMEDIATION, file=sys.stderr)
    print("可用的白名单指纹行：", file=sys.stderr)
    for finding in findings:
        print(f"  fingerprint:{finding.fingerprint}", file=sys.stderr)
    print("", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="secret_scan.py",
        description="推送前密钥扫描（仅标准库）",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--range", dest="rev_range", help="扫描 <base>..<head> 区间的新增行")
    group.add_argument("--staged", action="store_true", help="扫描已 staged 的新增行")
    group.add_argument("--all", action="store_true", help="全量扫描所有 git 跟踪文件")
    group.add_argument("--files", nargs="+", help="扫描指定文件")
    parser.add_argument(
        "--print-fingerprints",
        action="store_true",
        help="输出可粘贴进 allowlist 的指纹行",
    )
    parser.add_argument("--quiet", action="store_true", help="无命中时不输出")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    allowlist = Allowlist.load()

    try:
        if args.rev_range:
            findings = scan_range(args.rev_range)
            scope = f"区间 {args.rev_range} 的新增行"
        elif args.staged:
            findings = scan_staged()
            scope = "staged 新增行"
        elif args.files:
            findings = scan_files(args.files)
            scope = f"{len(args.files)} 个指定文件"
        else:
            findings = scan_all()
            scope = "全部 git 跟踪文件"
    except RuntimeError as exc:
        print(f"[secret-scan] 扫描失败: {exc}", file=sys.stderr)
        return 2

    kept: list[Finding] = []
    seen: set[str] = set()
    for finding in findings:
        if allowlist.allows(finding):
            continue
        if finding.fingerprint in seen:
            continue
        seen.add(finding.fingerprint)
        kept.append(finding)

    if kept:
        report(kept, print_fingerprints=args.print_fingerprints)
        return 1

    if not args.quiet:
        print(f"[secret-scan] 未发现敏感信息（扫描范围：{scope}）")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # noqa: BLE001 - fail-closed：扫描器异常也阻断
        print(f"[secret-scan] 内部错误，按阻断处理: {exc!r}", file=sys.stderr)
        sys.exit(2)
