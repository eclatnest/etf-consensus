# Cursor Automations（本仓库）

在 [cursor.com/automations](https://cursor.com/automations) 绑定仓库 **eclatnest/etf-consensus** 后，按各 `*.workflow.json` 创建或同步定时任务。

| 自动化 | 文件前缀 | 北京时间 | 说明 |
|--------|----------|----------|------|
| ETF每日买卖扫描 | `etf-daily-scan` | 工作日 17:00 | 全市场共识信号扫描 |
| ETF每晚数据更新 | `etf-nightly-data` | 工作日 22:15 | 信号 + 组合回测 + push `published/daily` |
| **ETF每日开盘操作** | **`etf-daily-open-execute`** | **工作日 09:20** | **pull 次日操作清单 → 妙想模拟盘调仓** |

## 推荐执行顺序

1. **22:15** `etf-nightly-data` — 生成 `published/daily/NEXT_OPEN.md`
2. **09:20** `etf-daily-open-execute` — `git pull` 后运行 `scripts/execute_next_open_actions.py`

## 环境变量（开盘操作）

脚本通过 **`os.environ["MX_APIKEY"]`** 读取，必须是**操作系统环境变量**，不是 JavaScript 的 `process.env`。

| 变量名 | 必填 | 说明 |
|--------|------|------|
| `MX_APIKEY` | 是（实盘下单） | 妙想 API Key，形如 `mkt_...` |
| `MX_API_URL` | 否 | 默认 `https://mkapi2.dfcfs.com/finskillshub` |

### Cursor 自动化 / Cloud Agent（推荐）

1. 打开 [cursor.com/dashboard → Cloud Agents → Secrets](https://cursor.com/dashboard/cloud-agents)（或对应 Automation 的环境密钥）。
2. **Name** 填：`MX_APIKEY`（仅变量名，不要写 `process.env.MX_APIKEY`）。
3. **Value** 填：`mkt_xxxxxxxx`（完整密钥，无引号、无 `export`、无分号）。
4. 若自动化绑定了专用 Environment，把密钥挂在**同一 Environment** 下（环境级密钥对该环境内所有 repo 生效）。
5. 保存后**重新跑一次**自动化；新密钥不会对已在跑的 Agent 生效。

### 本机调试

```bash
cp .env.example .env   # 编辑 .env 填入 MX_APIKEY
set -a && source .env && set +a
python3 scripts/execute_next_open_actions.py --pull --dry-run   # 先 dry-run
python3 scripts/execute_next_open_actions.py --pull             # 交易时段再实盘
```

**错误示例**：`process.env.MX_APIKEY=mkt_...`（Node 语法，Python/Shell 读不到）。

## 从仓库导入

每个自动化包含：

- `*.workflow.json` — 名称、cron、prompt 摘要
- `*.prompt.md` — Agent 完整步骤

在 Cursor 新建 Automation → 定时触发 → 复制对应 `workflow.json` 里 `prompts[0].prompt` 与 cron，并绑定本仓库 `master` 分支。
