# ETF 每晚数据更新（22:15）

在**仓库根目录**执行，更新 CSV 与 PnL 图。**不要改策略代码，不要开 PR。**

## 一键脚本（优先）

```bash
pip install akshare pandas matplotlib -q
python run_etf_nightly_update.py
```

## 输出目录

| 路径 | 内容 |
|------|------|
| `mx_data_output/etf_daily/latest/` | 当日全市场信号（buy/sell/hold/summary） |
| `mx_data_output/etf_daily/nightly/portfolio_*/` | 当次组合回测（带时间戳） |
| `mx_data_output/etf_daily/latest_portfolio/` | **最新**组合 CSV + `pnl_chart.png` |
| `mx_data_output/etf_daily/nightly/last_run.txt` | 上次成功时间 |

## 组合策略（固定）

`enhanced5y_n5` = fill_vote3 + 沪深300>MA200 才买 + 动量>25% + 最多5只

主要文件：`pnl_daily.csv`、`pnl_by_etf_all.csv`（含次日操作建议列）、`trades_marked.csv`、`pnl_chart.png`

## 失败处理

- akshare 崩溃：`python run_etf_daily_signals.py --workers 4 --sequential`
- 无 `detail_cache_1260d.pkl`：首次会较慢（约 40 分钟），之后读缓存约 1–2 分钟
- 完成后用中文简要汇报：行情截止日、组合净值/年化、买入卖出只数、`latest_portfolio` 路径
