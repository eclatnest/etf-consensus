#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
每晚运行：全市场 ETF 买卖信号

共识规则（实操三策略）:
  - 动量120日>5%  (mom120_5)
  - 唐奇安30/10    (dc30_10)
  - 60日新高       (hi60)

  买入: 至少1个策略今日出「买入」且 vote_hold>=2（三策略中至少2个明日持仓）
  卖出: 至少1个策略今日出「卖出」且 vote_hold==0
  持有: vote_hold>=2 且无卖出信号
  观望: vote_hold==1
  空仓: vote_hold==0

用法:
  python run_etf_daily_signals.py
  python run_etf_daily_signals.py --out mx_data_output/etf_daily/latest

建议: Windows 任务计划程序 每个交易日 17:00 运行（收盘后）
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import pandas as pd

from etf_scanner.config import ScanConfig
from etf_scanner.daily_signals import build_report, scan_daily_signals
from etf_scanner.data import load_etf_universe_cached

ROOT = Path(__file__).resolve().parent

if TYPE_CHECKING:
    pass


def print_list(title: str, sub: pd.DataFrame, cols: list[str], limit: int = 30) -> None:
    print(f"\n{title} ({len(sub)} 只)")
    if sub.empty:
        print("  (无)")
        return
    use_cols = [c for c in cols if c in sub.columns]
    show = sub[use_cols].head(limit)
    print(show.to_string(index=False))
    if len(sub) > limit:
        print(f"  ... 另有 {len(sub)-limit} 只，见 CSV")


def main() -> None:
    ap = argparse.ArgumentParser(description="ETF 每日买卖信号")
    ap.add_argument("--workers", type=int, default=4, help="并发数(建议<=6)")
    ap.add_argument("--sequential", action="store_true", help="单线程拉行情，更稳但更慢")
    ap.add_argument("--refresh-universe", action="store_true", help="强制刷新ETF列表缓存")
    ap.add_argument("--out", default="", help="输出目录")
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y%m%d")
    base = Path(args.out) if args.out else ROOT / "mx_data_output" / "etf_daily" / ts
    latest = ROOT / "mx_data_output" / "etf_daily" / "latest"
    base.mkdir(parents=True, exist_ok=True)

    cfg = ScanConfig(workers=args.workers)

    print("=== ETF 每日信号扫描 ===\n")
    print("策略: 动量120>5% | 唐奇安30/10 | 60日新高")
    print(f"输出: {base}\n")

    print("加载 ETF 列表...")
    universe = load_etf_universe_cached(cfg, refresh=args.refresh_universe)
    print(f"  共 {len(universe)} 只\n")

    df = scan_daily_signals(cfg, universe=universe, sequential=args.sequential)
    if df.empty:
        print("无数据")
        return

    rep = build_report(df, base)
    # 同步 latest
    latest.mkdir(parents=True, exist_ok=True)
    rep2 = build_report(df, latest)

    trade_date = rep["trade_date"]
    print(f"行情截止: {trade_date}（各ETF以自身最后交易日为准，见 CSV）\n")
    print(rep2["all"].groupby("consensus").size().to_string())

    cols = [
        "code",
        "name",
        "close",
        "vote_hold",
        "mom120_5_action",
        "dc30_10_action",
        "hi60_action",
        "consensus",
    ]
    print_list("【共识 · 明日建议买入】", rep["buy"], cols)
    print_list("【共识 · 明日建议卖出】", rep["sell"], cols + ["dc30_hi", "dc30_lo"])
    print_list("【共识 · 继续持有】", rep["hold"], cols, limit=20)

    for pid, label in [("mom120_5", "动量"), ("dc30_10", "唐奇安"), ("hi60", "60日新高")]:
        b = df[df[f"{pid}_action"] == "买入"]
        s = df[df[f"{pid}_action"] == "卖出"]
        print(f"\n--- {label} 单独: 买 {len(b)} / 卖 {len(s)} ---")
        if not b.empty:
            print(b[["code", "name", "close", f"{pid}_action"]].head(15).to_string(index=False))
        if not s.empty:
            print(s[["code", "name", "close", f"{pid}_action"]].head(15).to_string(index=False))

    print(f"\n文件目录: {base}")
    print("  buy_consensus.csv / sell_consensus.csv / hold_consensus.csv")
    print("  buy_mom120_5.csv ... / signals_all.csv")


if __name__ == "__main__":
    main()
