---
name: aliyun-cli
description: "将用户请求转换为可执行的原生 `aliyun` CLI 命令并运行，覆盖 OpenAPI 调用、credential/profile 管理，以及 ossutil、otsutil 等子命令。"
---

# Aliyun CLI

以本地已安装的原生 `aliyun` CLI 为唯一工具。先查 help 再拼命令，不猜参数；变更先 preview，再执行并汇总。

## 工作流

1. **判断请求类型**
   - credential / profile 管理 → `aliyun configure ...`
   - OSS object 操作 → `aliyun ossutil ...`
   - TableStore 操作 → `aliyun otsutil ...`
   - `ecs`、`vpc`、`ram`、`sls`、`fc` 等 OpenAPI product → `aliyun <product> <operation>`

2. **确认上下文**
   - 查看已配置 profile：`aliyun configure list`
   - 检查具体 profile：`aliyun configure get --profile <name>`
   - 用户给了 profile / region 时，后续命令显式带上 `--profile` 和 `--region`

3. **查 help 发现写法**
   - `aliyun --help` → `aliyun <product> --help` → `aliyun <product> <operation> --help`
   - 不跳过 help 直接猜参数；对 `configure`、`ossutil`、`otsutil` 同样先查 help

4. **映射用户意图到精确命令**
   - 只读操作优先找 `Describe*`、`List*`、`Get*`、`Query*`、`Check*`
   - 变更操作优先找 `Create*`、`Run*`、`Start*`、`Modify*`、`Attach*`、`Grant*`、`Delete*`、`Remove*`、`Stop*`、`Release*`
   - 参数名必须与 `aliyun ... --help` 显示的一致，不自造或翻译 flag

5. **拼命令并按安全姿态执行**
   - 用户只要命令 → 不执行，展示精确命令
   - 写操作且用户未明确要求立刻执行 → 先展示命令并请求确认
   - 支持时优先先跑 `--dryrun`

6. **汇总结果**
   - 提取 resource ID、region、状态等关键字段
   - 整理成结构化 Markdown，不直接贴原始 JSON
   - 隐藏 secret 或临时 token
   - 给出用户下一步可能用到的 follow-up command

## 命令构造规则

- 优先使用已配置好的 profile，不把 secret 内联到命令里。
- 当用户给了 profile / region，或上下文存在歧义时，显式写出 `--profile` 和 `--region`。
- OpenAPI 参数的大小写必须保持精确，例如 `RegionId`、`InstanceIds`、`VpcId`、`SecurityGroupId`。
- `ossutil` 和 `otsutil` 除 flags 外通常还带 `oss://bucket/prefix` 这类 positional argument。
- 输出给用户的命令必须是可直接复制执行的最终形态；宁可换行排版也不引入额外包装。

### 输出过滤与格式化

需要做 JSON 过滤时优先用 `--cli-query`（JMESPath）；需要表格式摘要时优先用 `--output`：

```bash
# JMESPath 过滤
aliyun ecs DescribeInstances \
  --region cn-hangzhou \
  --cli-query 'Instances.Instance[].{Id:InstanceId,Name:InstanceName,Status:Status}'

# 表格输出
aliyun ecs DescribeInstances \
  --region cn-hangzhou \
  --output cols=InstanceId,InstanceName,Status rows='Instances.Instance[]'
```

### 重复 flag

像 `--header` 这类可重复参数，直接重复写出：

```bash
aliyun sls GetLogs \
  --region cn-hangzhou \
  --header x-log-apiversion=0.6.0 \
  --header x-log-bodyrawsize=0
```

### JSON body

- 小型 body 直接内联单行 JSON：`--body '{"CommandContent":"ZWNobyBoZWxsbw=="}'`
- 大型 body 或多层嵌套时放入文件：`--body "$(cat body.json)"`

### `--force` + `--version` + `--endpoint`

当本地 CLI 没有某个 product 的元数据，但已有可靠依据时：

```bash
aliyun --force swas-open ListInstances \
  --version 2020-06-01 \
  --endpoint swas.cn-hangzhou.aliyuncs.com \
  --region cn-hangzhou
```

只在以下至少满足一项时使用：
- 用户已给出准确的 product / operation
- 当前上下文里已有验证过的工作命令
- 已通过官方文档核对过 product、version 和 endpoint

### 其他全局 flags

- `--dryrun`：写操作优先先做预检
- `--waiter expr=... to=...`：只有在用户明确需要等终态、且 polling 合理时才用
- `--pager`：API 支持分页合并时使用
- `--quiet`：只在用户明确要静默执行时使用

### 特殊产品备注

**轻量应用服务器 (swas-open)** 是插件产品，查询时必须同时指定 `--biz-region-id`（API 参数）和 `--region`（endpoint 参数）：

```bash
aliyun swas-open list-instances --biz-region-id ap-southeast-1 --region ap-southeast-1
```

## Help 与发现策略

- 优先按 `aliyun --help` → `aliyun <product> --help` → `aliyun <product> <operation> --help` 顺序查。
- product 在本地能找到就不跳过 help 直接猜参数。
- product 本地查不到时，只允许再做一次有依据的映射检查：
  - 从 `aliyun --help` 的 products 列表里找近似 product
  - 根据用户原话把资源名映射到最可能的 product
- 如果确认本地 CLI 缺少 product 元数据，但 product / operation / version / endpoint 已有可靠依据，才使用 `--force` 模式。
- 如果缺少可靠依据，不要在多个 product 名、endpoint、version 上盲试。

## 安全规则

- 不要让用户把 `AccessKeySecret` 或长期 secret 直接贴到对话里。
- 修改 authentication 前优先用 `aliyun configure list|get|switch` 检查现有 profile。
- 写操作（create / modify / delete / grant）未经用户确认不得执行；支持时先 `--dryrun`。
- 对 destructive 或可能产生费用的操作，先查询并确认目标 resource ID，再执行。
- 不在多个 region 间盲扫，除非用户明确要求全量枚举。
- 网络 / endpoint 不可达时立即停止，明确说明环境限制，不靠猜测继续。
- `ossutil` / `otsutil` 在拉取远端 metadata 时失败，视为环境/网络问题，不误判为语法错误。

## 失败处理与收敛

核心原则：同一失败类型最多 **1 次**纠正重试；同一目标最多 **2 次**真实尝试；第二次失败后停止。

### 按失败类型处理

| 失败类型 | 处理方式 |
|---|---|
| `unknown product` | 回到 `aliyun --help`；只有 `--force + --version + --endpoint` 均有可靠依据时再试一次 |
| `unknown parameter` | 回到精确的 `aliyun <product> <operation> --help`，复制准确参数名后只再试一次 |
| `authentication/profile` | `aliyun configure list` 或 `configure get --profile <name>` 检查一次；不让用户贴 secret |
| `empty results` | 只核对一次 region / profile / filter 条件；不盲扫多 region |
| `network / DNS / TLS / endpoint 不可达` | 立即停止，说明环境无法访问目标 endpoint |
| `endpoint/version mismatch` | 有可靠依据时显式加 `--endpoint` 和 `--version` 再试一次 |

### 停止时必须输出

- 已尝试的命令
- 当前阻塞点
- 还缺什么信息或前置条件

## 输出与排版规则

### 通用结构

按 `结论 → 范围/条件 → 汇总表 → 明细 → 后续建议` 顺序组织。

### 表格规则

- 列顺序：范围字段（Profile / Region / Zone）→ 资源标识（Name / Id）→ 状态与规格 → IP / 时间 / 计费
- 对 `InstanceId`、`SecurityGroupId`、IP、`RegionId`、`RequestId` 等值用反引号包裹
- 表格超 8 列时拆为汇总表 + 明细表
- 时间转用户时区，给出明确日期时间

### 不同场景的输出模式

**资产清单查询**：先一句结论（如"cn-hangzhou 下共 3 台 ECS"），再给表格。

**单资源详情**：输出单张 Field / Value 两列详情表。

**变更类操作**：输出"执行了什么"（含 bash 命令）与"变更结果"（表格列出关键字段）两部分。

**空结果**：仍然展示查询范围（profile / region / filter），明确写"结果为空"。

**失败结果**：说明已尝试命令、阻塞点、下一步所需条件；不只返回一句泛泛错误。

### 命令展示

- 命令统一放 `bash` code block
- 不把长命令塞进正文句子
- 显式写出 `--profile`、`--region`、`--endpoint`、`--version`，不依赖隐式上下文

## 端到端示例：安全组白名单

当用户要把当前公网 IP 加入 ECS Security Group 时，按以下模式操作：

### 步骤

1. **查调用方 IP**
   ```bash
   curl -fsSL cip.cc
   ```

2. **查目标安全组现有规则**（确认是否已存在等价规则）
   ```bash
   aliyun ecs DescribeSecurityGroupAttribute \
     --profile AkProfile --region cn-hangzhou \
     --SecurityGroupId sg-xxx
   ```

3. **`--dryrun` 预检写请求**
   ```bash
   aliyun ecs AuthorizeSecurityGroup \
     --profile AkProfile --region cn-hangzhou \
     --SecurityGroupId sg-xxx \
     --IpProtocol TCP --PortRange 22/22 \
     --SourceCidrIp <IP>/32 \
     --NicType intranet --Policy Accept --Priority 1 \
     --Description "cip-<date>" \
     --dryrun
   ```

4. **确认后执行真实变更**（去掉 `--dryrun`）

5. **回读验证最终规则**
   ```bash
   aliyun ecs DescribeSecurityGroupAttribute \
     --profile AkProfile --region cn-hangzhou \
     --SecurityGroupId sg-xxx
   ```

### 原则

- 单个公网 IP 优先 `/32`；端口收敛到最小范围
- 除非用户明确要求，不开放 `0.0.0.0/0`
- 顺序：先 query → 再 mutate → 最后 verify
- 全局 `--dryrun` flag 做安全预检（不是 API 参数 `--DryRun`）

### 推荐输出样式

一句结论 + 变更结果表：

```
已把当前公网 IP x.x.x.x 加入目标 Security Group SSH 白名单。
```

| SecurityGroupId | Direction | Protocol | PortRange | SourceCidrIp | Policy | RuleId |
|---|---|---|---|---|---|---|
| `sg-xxx` | `ingress` | `TCP` | `22/22` | `x.x.x.x/32` | `Accept` | `sgr-xxx` |

## 常用模块范例：ECS

### 查询实例列表

```bash
aliyun ecs DescribeInstances \
  --profile AkProfile --region cn-hangzhou \
  --output cols=InstanceId,InstanceName,Status,InstanceType rows='Instances.Instance[]'
```

### 查询单台实例详情

```bash
aliyun ecs DescribeInstances \
  --profile AkProfile --region cn-hangzhou \
  --InstanceIds '["i-bp14nattzmsfndro5mwx"]'
```

注意 `--InstanceIds` 接收 JSON 数组字符串。

### 启动 / 停止实例

```bash
# 启动
aliyun ecs StartInstance \
  --profile AkProfile --region cn-hangzhou \
  --InstanceId i-bp14nattzmsfndro5mwx

# 停止（优雅停机）
aliyun ecs StopInstance \
  --profile AkProfile --region cn-hangzhou \
  --InstanceId i-bp14nattzmsfndro5mwx \
  --StoppedMode KeepCharging
```

### 查询实例关联的安全组

```bash
aliyun ecs DescribeInstanceAttribute \
  --profile AkProfile --region cn-hangzhou \
  --InstanceId i-bp14nattzmsfndro5mwx \
  --cli-query 'SecurityGroupIds.SecurityGroupId[]'
```

## 常用模块范例：轻量应用服务器 (swas-open)

swas-open 是插件产品，关键要点：
- 必须同时带 `--biz-region-id`（API 参数）和 `--region`（endpoint 路由参数），两者通常相同
- 如果本地 CLI 没有 swas-open 元数据，需要 `--force --version 2020-06-01 --endpoint swas.<region>.aliyuncs.com`

### 列出所有轻量服务器

```bash
aliyun swas-open list-instances \
  --profile AkProfile \
  --biz-region-id ap-southeast-1 --region ap-southeast-1
```

### 查询单台轻量服务器详情

```bash
aliyun swas-open list-instances \
  --profile AkProfile \
  --biz-region-id ap-southeast-1 --region ap-southeast-1 \
  --instance-id <instance-id>
```

### 查询轻量服务器防火墙规则

```bash
aliyun swas-open list-instance-firewall-rules \
  --profile AkProfile \
  --biz-region-id ap-southeast-1 --region ap-southeast-1 \
  --instance-id <instance-id>
```

### 使用 --force 模式（本地无元数据时）

```bash
aliyun --force swas-open ListInstances \
  --profile AkProfile \
  --version 2020-06-01 \
  --endpoint swas.ap-southeast-1.aliyuncs.com \
  --region ap-southeast-1 \
  --RegionId ap-southeast-1
```

## 常用模块范例：OSS (ossutil)

OSS 操作使用 `aliyun ossutil` 子命令，参数风格与 OpenAPI 不同：positional argument + flags。

### 列出 bucket

```bash
aliyun ossutil ls --profile AkProfile
```

### 列出 bucket 内对象

```bash
aliyun ossutil ls oss://my-bucket/path/prefix --profile AkProfile
```

### 上传文件

```bash
# 单文件
aliyun ossutil cp ./local-file.txt oss://my-bucket/remote-path/ --profile AkProfile

# 整个目录（递归）
aliyun ossutil cp ./local-dir/ oss://my-bucket/remote-dir/ --recursive --profile AkProfile
```

### 下载文件

```bash
aliyun ossutil cp oss://my-bucket/remote-file.txt ./local-path/ --profile AkProfile
```

### 同步目录

```bash
aliyun ossutil sync ./local-dir/ oss://my-bucket/remote-dir/ --profile AkProfile
```

### 生成签名 URL（临时下载链接）

```bash
aliyun ossutil sign oss://my-bucket/file.zip --timeout 3600 --profile AkProfile
```

### 查看对象元信息

```bash
aliyun ossutil stat oss://my-bucket/file.zip --profile AkProfile
```

## 参考文档

遇到命令细节时，优先 `aliyun <cmd> --help`；需要深入了解时参考官方文档：

- [理解命令结构](https://help.aliyun.com/zh/cli/understanding-command-structure)
- [理解命令行参数](https://help.aliyun.com/zh/cli/understanding-command-line-parameters)
- [生成并调用命令](https://help.aliyun.com/zh/cli/sample-commandsOR_help-T_cn~zh-V_1)
- [过滤且表格化输出结果](https://help.aliyun.com/zh/cli/filter-results-and-tabulate-output)
- [控制 API 调用的执行方式](https://help.aliyun.com/zh/cli/control-how-api-calls-are-executed)
- [安全策略 (Safety Policy)](https://help.aliyun.com/zh/cli/safety-policy)
- [在请求中增加 AI 标识](https://help.aliyun.com/zh/cli/ai-mode)
- [使用 aliyun mcp-proxy 代理 OpenAPI MCP Server](https://help.aliyun.com/zh/cli/use-aliyun-mcp-proxy-agent-openapi-mcp-server)


## 快速使用
> 如果检查到未安装aliyun cli或者需要对应产品插件参考操作

- [安装/更新阿里云 CLI](https://help.aliyun.com/zh/cli/install-update-alibaba-cloud-cli)
- [快速使用阿里云 CLI](https://help.aliyun.com/zh/cli/quickly-start-using-alibaba-cloud-cli)
- [快速安装云产品CLI插件](https://help.aliyun.com/zh/cli/managing-and-using-cli-plugins)