# ETF 每日开盘操作（依据昨晚更新）

在**仓库根目录**执行。依赖前一晚 **ETF每晚数据更新** 已生成并 push 的 `published/daily/`（或本机已跑完 `run_etf_nightly_update.py`）。

**不要改策略代码，不要开 PR。**

## 流程

### 1. 拉取最新操作清单（优先）

```bash
git pull --ff-only origin HEAD
```

若 pull 失败且本地已有 `published/daily/NEXT_OPEN.md`，可继续；否则中止并说明原因。

### 2. 核对数据是否新鲜

读 `published/daily/LAST_UPDATED.txt`、`NEXT_OPEN.md` 概要表：

- **信号日**、**执行日（开盘）** 是否为「今日或上一交易日 → 今日开盘」
- 若明显过期（例如执行日早于今天且非周末），在汇报中标注**未执行下单**

### 3. 阅读操作内容

必读：

| 文件 | 用途 |
|------|------|
| `published/daily/NEXT_OPEN.md` | 开盘买入 / 卖出 / 持有（人读） |
| `published/daily/next_open_actions.csv` | 脚本执行用 |
| `published/daily/portfolio_snapshot.csv` | 目标组合与权益 |

### 4. 执行模拟交易（妙想 mx-moni）

需已配置 `MX_APIKEY`（及可选 `MX_API_URL`）。

```bash
pip install akshare pandas requests -q
python scripts/execute_next_open_actions.py --pull
```

脚本逻辑（勿手改顺序）：

1. 一键撤单  
2. **卖出**：`开盘卖出` + 不在目标组合内的持仓  
3. **买入**：`开盘买入` + 目标组合中尚无持仓的标的（按快照权重或等权估算股数，100 股整数倍）  
4. **`开盘持有`**：不下单  

仅**交易日 9:15–15:00（北京时间）**可成交；非交易时段加 `--dry-run` 只出计划：

```bash
python scripts/execute_next_open_actions.py --pull --dry-run
```

执行日志：`mx_data_output/etf_daily/executions/run_*.json`

### 5. 失败处理

| 情况 | 处理 |
|------|------|
| 缺少 `published/daily` | 提示先跑每晚更新或 `publish_daily_to_github.py --push` |
| 无 `MX_APIKEY` | 只 `--dry-run`，汇报计划 |
| 妙想 404 未绑定账户 | 提示 https://dl.dfcfs.com/m/itc4 绑定模拟组合 |
| 非交易时间下单失败 | 用 `--dry-run` 汇报拟下单，注明收盘后再试 |

## 完成汇报（Automation 用中文）

1. **git pull** 是否成功、信号日 / 执行日  
2. **开盘买入 / 卖出 / 持有**（来自 `NEXT_OPEN.md`）  
3. **实际下单结果**（成功 / 失败 / 仅 dry-run）及委托编号（若有）  
4. **执行后持仓**（脚本日志或 `mx-moni`「我的持仓」）  
5. 一句风险提示：模拟盘按规则执行，非投资建议  
