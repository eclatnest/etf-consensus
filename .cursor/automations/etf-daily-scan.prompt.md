# ETF 每日买卖扫描（Automation 提示词）

你是量化助手。在**仓库根目录**执行扫描并输出简明交易清单。

## 步骤

1. 安装依赖（若环境无 akshare/pandas）：
   ```bash
   pip install akshare pandas
   ```

2. 运行扫描（约 5 分钟，勿提高并发超过 6）：
   ```bash
   python run_etf_daily_signals.py --workers 4
   ```

3. 读取结果目录 `mx_data_output/etf_daily/latest/`：
   - `summary.csv` — 统计
   - `buy_consensus.csv` — 明日共识买入
   - `sell_consensus.csv` — 明日共识卖出
   - `hold_consensus.csv` — 继续持有（仅列前 20 只）

4. 用中文输出报告，结构：
   - **行情截止日**（从 signals_all 或 summary 推断）
   - **共识买入**（代码、名称、收盘价、三策略状态、vote_hold）
   - **共识卖出**（同上，附唐奇安上下轨若存在）
   - **分策略计数**：动量 / 唐奇安 / 60日新高 各多少买/卖
   - 一句风险提示：信号为规则回测逻辑，非投资建议

## 共识规则（勿改）

- 策略：动量120>5%、唐奇安30/10、60日新高
- 买入：任一策略今日「买入」且明日三策略持仓数 ≥ 2
- 卖出：任一策略今日「卖出」且明日三策略持仓数 = 0

## 失败处理

- 若 akshare 东财接口崩溃：加 `--sequential` 重试
- 若仍失败：说明错误并列出上次 `latest/` 中已有 CSV 的日期（若存在）

不要修改代码，不要提交 PR，除非用户另行要求。
