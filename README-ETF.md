# ETF 共识策略 · 每日扫描与组合回测

三策略共识（动量120>5%、唐奇安30/10、60日新高）+ 组合规则 `enhanced5y_n5`（三票 + MA200 择时 + 动量>25% + 最多5只）。

## 快速开始

```bash
pip install -r requirements-etf.txt
python run_etf_daily_signals.py --workers 4
python run_etf_nightly_update.py
```

## Cursor Automations

| 自动化 | 时间 | 说明 |
|--------|------|------|
| ETF每日买卖扫描 | 工作日 17:00 北京 | `etf-daily-scan.prompt.md` |
| ETF每晚数据更新 | 工作日 22:15 北京 | `run_etf_nightly_update.py` |
| ETF每日开盘操作 | 工作日 09:20 北京 | `etf-daily-open-execute.prompt.md` → `scripts/execute_next_open_actions.py` |

在 [cursor.com/automations](https://cursor.com/automations) 绑定**本 GitHub 仓库**后生效。

## 主要脚本

- `run_etf_daily_signals.py` — 全市场信号 → `mx_data_output/etf_daily/latest/`
- `run_etf_consensus_portfolio_10.py` — 组合回测（`--profile enhanced5y_n5`）
- `run_etf_nightly_update.py` — 每晚一键更新 CSV + PnL 图
- `scripts/execute_next_open_actions.py` — 按 `published/daily` 在妙想模拟盘执行开盘买卖
- `plot_etf_portfolio_pnl.py` — 净值/回撤图

## 输出

- `mx_data_output/etf_daily/latest/` — 当日买卖清单
- `mx_data_output/etf_daily/latest_portfolio/` — 最新组合 CSV 与 `pnl_chart.png`
- `published/daily/NEXT_OPEN.md` — 次日开盘操作（GitHub 可读）
- `mx_data_output/etf_daily/executions/` — 开盘执行日志
