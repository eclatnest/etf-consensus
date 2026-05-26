# ETF 共识策略 · 每日扫描与组合回测

三策略共识（动量120>5%、唐奇安30/10、60日新高）+ 组合规则 `enhanced5y_n5`（三票 + MA200 择时 + 动量>25% + 最多5只）。

## 快速开始

```bash
pip install -r requirements-etf.txt
python run_etf_daily_signals.py --workers 4
python run_etf_nightly_update.py
```

## Cursor Automations

在 [cursor.com/automations](https://cursor.com/automations) 绑定**本仓库**后：

| 自动化 | 时间 | 说明 |
|--------|------|------|
| ETF每日买卖扫描 | 工作日 17:00 北京 | `etf-daily-scan.prompt.md` |
| ETF每晚数据更新 | 工作日 22:15 北京 | `run_etf_nightly_update.py` |

## 主要脚本

- `run_etf_daily_signals.py` — 全市场信号 → `mx_data_output/etf_daily/latest/`
- `run_etf_consensus_portfolio_10.py` — 组合回测（`--profile enhanced5y_n5`）
- `run_etf_nightly_update.py` — 每晚更新 CSV + PnL 图
- `plot_etf_portfolio_pnl.py` — 净值/回撤图

输出目录（运行后生成）：`mx_data_output/etf_daily/latest/`、`latest_portfolio/`。
