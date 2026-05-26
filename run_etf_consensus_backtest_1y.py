#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""共识三策略 · 近一年组合回测（等权持仓）"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pandas as pd

from etf_scanner.config import ScanConfig
from etf_scanner.consensus_backtest import (
    backtest_equal_weight_portfolio,
    build_panels,
    trade_calendar_start,
    write_backtest_report,
)
from etf_scanner.data import load_etf_universe_cached

ROOT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=252, help="回测交易日数量")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sequential", action="store_true")
    ap.add_argument("--cost", type=float, default=0.0005)
    ap.add_argument("--cash", type=float, default=100_000.0)
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out = Path(args.out) if args.out else ROOT / "mx_data_output" / "etf_daily" / f"backtest_1y_{ts}"

    cfg = ScanConfig(workers=args.workers, cost=args.cost, init_cash=args.cash)
    start = trade_calendar_start(args.days)

    print(f"=== 共识策略 · 近 {args.days} 个交易日回测 ===\n")
    print(f"起始日(约): {start.date()}\n")

    universe = load_etf_universe_cached(cfg)
    pos_wide, ret_wide, per_etf = build_panels(cfg, start, universe, sequential=args.sequential)
    if pos_wide.empty:
        print("无数据")
        return

    end = pd.Timestamp(pos_wide.index.max())
    pnl, port_m = backtest_equal_weight_portfolio(pos_wide, ret_wide, args.cost, args.cash)
    write_backtest_report(out, pnl, port_m, per_etf, start, end, args.cost, args.cash)

    print("【等权组合】")
    print(f"  区间: {start.date()} ~ {end.date()}")
    print(f"  总收益: {port_m['total_return']}%")
    print(f"  年化: {port_m['annual_return']}%")
    print(f"  最大回撤: {port_m['max_drawdown']}%")
    print(f"  Sharpe: {port_m['sharpe']}")
    print(f"  期末净值: {port_m['final_equity']:,.2f}")
    print(f"  日均持仓数: {port_m['avg_held']} (最多 {port_m['max_held']})")
    print(f"  累计换手(权重变动): {port_m['total_turnover']:.2f}")

    per_df = pd.DataFrame(per_etf)
    if not per_df.empty:
        print("\n【单标的汇总】")
        print(f"  有效回测: {len(per_df)} 只")
        print(f"  收益中位数: {per_df['total_return'].median():.2f}%")
        print(f"  收益均值: {per_df['total_return'].mean():.2f}%")
        print(f"  全市场买入边沿合计: {int(per_df['buy_trades'].sum())}")
        print(f"  全市场卖出边沿合计: {int(per_df['sell_trades'].sum())}")
        print(f"  组合换手次数(权重变动/2 近似): {int(pnl['turnover'].sum() / 2)}")

        top = per_df.nlargest(5, "total_return")[["code", "name", "total_return", "round_trips"]]
        bot = per_df.nsmallest(5, "total_return")[["code", "name", "total_return", "round_trips"]]
        print("\n  收益 TOP5:")
        print(top.to_string(index=False))
        print("\n  收益 BOTTOM5:")
        print(bot.to_string(index=False))

    print(f"\n输出目录: {out.resolve()}")


if __name__ == "__main__":
    main()
