# 推送前密钥扫描（pre-push secret scan）

仓库是 public repo，本目录提供一道 `git push` 前的自动闸门：扫描本次待推送 commit 的**新增行**，
发现疑似 AK/SK、API Key、Token、私钥、带口令的连接串等敏感信息就**阻断推送**。

主要用途是兜住"模型/人手快"导致的误提交——它只做检测与阻断，不会自动改写任何已提交内容。

## 文件

| 文件 | 作用 |
| --- | --- |
| `secret_scan.py` | 扫描器主体，Python 3 标准库实现，无第三方依赖 |
| `pre-push` | 钩子实现：解析 git 传入的 ref 信息，计算待推送区间后调用扫描器 |
| `install.sh` | 把钩子挂到 `.git/hooks/pre-push`（薄封装转发） |
| `secret-allowlist.txt` | 共享白名单 |
| `secret-allowlist.local.txt` | 个人白名单（gitignored，按需自建） |

## 安装 / 卸载

```bash
bash .qoder/hooks/install.sh              # 安装
bash .qoder/hooks/install.sh --uninstall  # 卸载（有备份则还原）
```

`.git/hooks/` 不随仓库分发，所以**克隆仓库后需要各自执行一次安装**。

安装脚本刻意不修改 `git config core.hooksPath`：
- 现有的 `.git/hooks/post-commit`（Qoder AI tracker）完全不受影响
- 生成的 `.git/hooks/pre-push` 只是一个转发脚本，真实逻辑随仓库版本化在本目录

## 手动使用

```bash
python3 .qoder/hooks/secret_scan.py --all                 # 全量自查所有跟踪文件
python3 .qoder/hooks/secret_scan.py --staged              # 只查已 staged 的新增行
python3 .qoder/hooks/secret_scan.py --range HEAD~3..HEAD  # 查指定区间新增行
python3 .qoder/hooks/secret_scan.py --files a.py b.md     # 查指定文件
python3 .qoder/hooks/secret_scan.py --all --print-fingerprints  # 只输出白名单指纹行
```

退出码：`0` 干净 / `1` 有命中 / `2` 扫描器自身错误。钩子对 `1` 和 `2` 都阻断（fail-closed）。

## 覆盖范围

- **云厂商**：AWS AKIA/ASIA 系、Azure Storage Key 与 SAS、阿里云 `LTAI` + AccessKeySecret（含 `--access-key-secret` 命令行内联）、腾讯云 `AKID`、火山 `AKLT`
- **模型服务**：OpenAI `sk-` / `sk-proj-`、Anthropic `sk-ant-`、DashScope/DeepSeek/Moonshot/百炼、智谱、Google `AIza`、HuggingFace `hf_`
- **代码托管与包仓库**：GitHub `ghp_`/`github_pat_`、GitLab `glpat-`、npm `npm_`、PyPI token、Docker registry auth
- **IM/办公**：飞书 `cli_` app id、飞书 tenant/user token、飞书机器人 webhook、微信 `wx` appid、钉钉机器人 token、Slack token/webhook
- **其他 SaaS**：Notion `secret_`/`ntn_`、Stripe、SendGrid、Twilio、Telegram bot token
- **通用形态**：各类 `PRIVATE KEY` 块、PuTTY 私钥、JWT、带口令的 `postgres://`/`mysql://`/`redis://`/`mongodb://` 等连接串、`Authorization: Bearer xxx`
- **项目专属**：`FEISHU_APP_SECRET`、`FEISHU_VERIFICATION_TOKEN`、`FEISHU_ENCRYPT_KEY`、`DASHSCOPE_API_KEY`、`CODEX_API_KEY`、`WECHAT_WEBHOOK_TOKEN` 赋值非空即报
- **危险文件名**：`.env`、`.env.local`、`*.pem`、`*.key`、`*.p12`、`id_rsa*`、`credentials.json`、`service-account*.json`、`conf/wechat/account.json`、`rules/admin.md` 等新增即报（`*.example` / `*.sample` / `*.template` 例外）
- **关键字兜底**：`api_key=`、`token=`、`password=`、`client_secret=` 等赋值

## 降噪设计

- 熵检测**不作为独立规则**，只用于关键字类弱规则命中后的二次确认，避免 lockfile 哈希、UUID 之类大面积误报
- 占位符值直接放行：`your_xxx`、`<...>`、`${VAR}`、`changeme`、`example`、`placeholder`、`redacted`、重复单字符等
- 标识符形态放行：`settings.api_key`、`SNAKE_CASE`、路径、版本号
- 跳过路径：`*.lock`、`package-lock.json`、`*.min.js`、图片/二进制、`.venv/`、`node_modules/`、`runtime/`、`logs/`
- 单文件 > 1MB 跳过；单行超 2000 字符先截断

## 命中之后怎么办

报告会给出 `文件:行号`、规则名、掩码后的片段。处置顺序：

1. **先轮换密钥**。已经写进 commit 就当作已泄露，删代码不等于撤销泄露。
2. 清理历史：最近一次提交 `git commit --amend`；更早的用 `git rebase -i` 或 `git filter-repo --replace-text`。
3. 确认是误报：把报告尾部给出的 `fingerprint:` 行贴进 `secret-allowlist.txt`（共享）或
   `secret-allowlist.local.txt`（仅本机），也可以在该行尾加注释 `secret-scan: ignore`。

紧急放行（仅在完全确认无风险时）：

```bash
SKIP_SECRET_SCAN=1 git push
```

## 测试

```bash
.venv/bin/python -m pytest tests/test_secret_scan.py -q
```

注意：测试里的假密钥必须用运行时拼接构造（如 `"AKIA" + "B" * 16`），
写成完整字面量会被本钩子拦下自己的测试文件。
