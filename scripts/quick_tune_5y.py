#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""5年规则快速扫描（精选组合，约 2–4 分钟）"""
from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from etf_scanner.consensus_backtest import (
    backtest_portfolio_buy_sell_max_n,
    history_tail_bars,
    trade_calendar_start,
)
from etf_scanner.daily_signals import load_daily_tail
from etf_scanner.data import sina_symbol
from etf_scanner.portfolio_rules import DEFAULT_ENHANCED, PortfolioRules

CACHE = ROOT / "mx_data_output" / "etf_daily" / "detail_cache_1260d.pkl"
DAYS = 1260


def candidates() -> list[PortfolioRules]:
    out: list[PortfolioRules] = [DEFAULT_ENHANCED]
    for mp in (3, 5, 8):
        for mom in (10, 15, 20, 25):
            for mk, rg in (
                ("ma200", "force_cash"),
                ("ma200", "no_buy"),
                ("ma60", "force_cash"),
            ):
                for em, xm in (
                    ("fill_vote2", "vote_lt2"),
                    ("fill_vote2", "sell_only"),
                    ("fill_vote3", "vote_lt2"),
                ):
                    out.append(PortfolioRules(mp, em, xm, float(mom), 2, mk, rg))
    for br in (0.05, 0.10, 0.15):
        out.append(PortfolioRules(5, "fill_vote3", "vote_lt2", 15.0, 2, "ma200", "no_buy", None, br))
        out.append(PortfolioRules(3, "fill_vote2", "sell_only", 20.0, 2, "ma200", "force_cash", None, br))
    return out


def main() -> None:
    t0 = time.time()
    detail = pickle.loads(CACHE.read_bytes())
    start = trade_calendar_start(DAYS)
    ret_wide = detail.pivot(index="date", columns="code", values="ret")
    cal = load_daily_tail(sina_symbol("510300"), tail=history_tail_bars(DAYS))
    calendar = pd.DatetimeIndex(cal[cal["date"] >= start]["date"].unique()).sort_values()

    rows = []
    for rules in candidates():
        _, _, m, _, _ = backtest_portfolio_buy_sell_max_n(
            detail, ret_wide, calendar_dates=calendar, rules=rules
        )
        rows.append(
            {
                "profile": rules.label,
                "annual_return": m["annual_return"],
                "total_return": m["total_return"],
                "max_drawdown": m["max_drawdown"],
                "sharpe": m["sharpe"],
                "avg_held": m["avg_held"],
                "buys": m["portfolio_buys"],
            }
        )

    df = pd.DataFrame(rows).sort_values("annual_return", ascending=False)
    out = ROOT / "mx_data_output" / "etf_daily" / "portfolio_tune_5y_results.csv"
    df.to_csv(out, index=False, encoding="utf-8-sig")
    print(f"完成 {len(df)} 套，耗时 {time.time()-t0:.0f}s\n")
    print("=== Top 15 ===")
    print(df.head(15).to_string(index=False))
    hit = df[df["annual_return"] >= 20]
    print(f"\n年化>=20%: {len(hit)} 套")
    if not hit.empty:
        print(hit.to_string(index=False))
    print(f"\n结果: {out}")


if __name__ == "__main__":
    main()
