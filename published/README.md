# GitHub 每日可读数据

每晚 Automation 跑完后，本目录会更新并 **push 到 GitHub**。

## 第二天开盘前请看

**[daily/NEXT_OPEN.md](./daily/NEXT_OPEN.md)** — 次日开盘买入 / 卖出 / 持有清单（Markdown，手机也能看）

## 同目录 CSV

| 文件 | 说明 |
|------|------|
| `daily/next_open_actions.csv` | 组合层面次日开盘操作 |
| `daily/portfolio_snapshot.csv` | 信号日收盘后持仓快照 |
| `daily/portfolio_summary.csv` | 近5年回测汇总 |
| `daily/signals_buy.csv` | 全市场共识买入（参考） |
| `daily/signals_sell.csv` | 全市场共识卖出（参考） |
| `daily/LAST_UPDATED.txt` | 上次更新时间 |

完整回测与 PnL 图在本地 `mx_data_output/`（体积大，不入库）。

## 开盘自动执行

工作日 **09:20（北京）** Automation `etf-daily-open-execute` 会 `git pull` 本目录并运行：

```bash
python scripts/execute_next_open_actions.py --pull
```

需配置环境变量 `MX_APIKEY`（妙想模拟交易）。

## 手动发布

```bash
python run_etf_nightly_update.py
python scripts/publish_daily_to_github.py --push
```

手动执行开盘操作：

```bash
python scripts/execute_next_open_actions.py --pull
python scripts/execute_next_open_actions.py --pull --dry-run   # 仅看计划
```
