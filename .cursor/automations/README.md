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

- `MX_APIKEY` — 妙想模拟交易（必填方可下单）
- `MX_API_URL` — 可选，默认 `https://mkapi2.dfcfs.com/finskillshub`

## 从仓库导入

每个自动化包含：

- `*.workflow.json` — 名称、cron、prompt 摘要
- `*.prompt.md` — Agent 完整步骤

在 Cursor 新建 Automation → 定时触发 → 复制对应 `workflow.json` 里 `prompts[0].prompt` 与 cron，并绑定本仓库 `master` 分支。
