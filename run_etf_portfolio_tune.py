#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""扫描组合规则，目标年化 ~20%"""
from __future__ import annotations

import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from etf_scanner.config import ScanConfig
from etf_scanner.consensus_backtest import (
    backtest_portfolio_buy_sell_max_n,
    build_signal_detail,
    trade_calendar_start,
)
from etf_scanner.daily_signals import load_daily_tail
from etf_scanner.data import load_etf_universe_cached, sina_symbol
from etf_scanner.portfolio_rules import BASELINE, DEFAULT_ENHANCED, PortfolioRules

CACHE = ROOT / "mx_data_output" / "etf_daily" / "detail_cache_252d.pkl"

PROFILES = [
    BASELINE,
    DEFAULT_ENHANCED,
    PortfolioRules(10, "fill_vote3", "sell_only", 0, 3),
    PortfolioRules(10, "fill_vote2_mom5", "vote_lt2", 5.0, 2),
    PortfolioRules(8, "fill_vote3", "vote_lt2", 0, 3),
    PortfolioRules(10, "fill_vote2", "vote_lt2", 0, 2),
    PortfolioRules(10, "buy_only", "vote_lt2", 0, 2),
]


def main() -> None:
    cfg = ScanConfig(workers=4)
    start = trade_calendar_start(252)

    if CACHE.is_file():
        print(f"读取缓存 {CACHE}")
        detail = pickle.loads(CACHE.read_bytes())
    else:
        print("构建信号明细（首次较慢）...")
        universe = load_etf_universe_cached(cfg)
        detail = build_signal_detail(cfg, start, universe)
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_bytes(pickle.dumps(detail))

    ret_wide = detail.pivot(index="date", columns="code", values="ret")
    cal_df = load_daily_tail(sina_symbol("510300"), tail=300)
    calendar = pd.DatetimeIndex(cal_df[cal_df["date"] >= start]["date"].unique()).sort_values()

    rows = []
    best = None
    for rules in PROFILES:
        pnl, trades, m, _, _ = backtest_portfolio_buy_sell_max_n(
            detail, ret_wide, calendar_dates=calendar, rules=rules
        )
        row = {
            "profile": rules.label,
            "annual_return": m["annual_return"],
            "total_return": m["total_return"],
            "max_drawdown": m["max_drawdown"],
            "sharpe": m["sharpe"],
            "profit_factor": m["profit_factor"],
            "avg_held": m["avg_held"],
            "buys": m["portfolio_buys"],
            "sells": m["portfolio_sells"],
        }
        rows.append(row)
        if best is None or m["annual_return"] > best[1]:
            best = (rules, m["annual_return"], pnl, trades, m)

    df = pd.DataFrame(rows).sort_values("annual_return", ascending=False)
    out = ROOT / "mx_data_output" / "etf_daily" / "portfolio_tune_results.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(df.to_string(index=False))
    print(f"\n最优: {best[0].label} 年化 {best[1]}%")
    print(f"结果: {out}")


if __name__ == "__main__":
    main()
