#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""5年组合规则网格扫描，目标年化 20%+"""
from __future__ import annotations

import itertools
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from etf_scanner.config import ScanConfig
from etf_scanner.consensus_backtest import (
    backtest_portfolio_buy_sell_max_n,
    history_tail_bars,
    trade_calendar_start,
)
from etf_scanner.daily_signals import load_daily_tail
from etf_scanner.data import sina_symbol
from etf_scanner.portfolio_rules import BASELINE, DEFAULT_ENHANCED, DEFAULT_5Y, PortfolioRules

DAYS = 1260
CACHE = ROOT / "mx_data_output" / "etf_daily" / f"detail_cache_{DAYS}d.pkl"


def grid_profiles() -> list[PortfolioRules]:
    profiles: list[PortfolioRules] = [DEFAULT_ENHANCED, BASELINE, DEFAULT_5Y]
    entry_modes = ("fill_vote2", "fill_vote3", "fill_vote2_mom5", "buy_only")
    exit_modes = ("vote_lt2", "vote_lt3", "sell_only")
    moms = (0.0, 5.0, 10.0, 15.0, 20.0)
    max_pos = (5, 8, 10)
    market_filters = ("none", "ma200", "ma60", "mom120_pos")
    regime_modes = ("none", "no_buy", "force_cash")
    weak_caps = (None, 3, 5)
    breadths = (0.0, 0.05, 0.10)

    for em, xm, mom, mp, mk, rg, wk, br in itertools.product(
        entry_modes, exit_modes, moms, max_pos, market_filters, regime_modes, weak_caps, breadths
    ):
        if mom > 0 and em == "buy_only":
            continue
        if em == "fill_vote2_mom5" and mom < 5:
            continue
        if mk == "none" and rg != "none":
            continue
        if rg == "none" and wk is not None:
            continue
        if br > 0 and em == "buy_only":
            continue
        profiles.append(
            PortfolioRules(
                max_positions=mp,
                entry_mode=em,
                exit_mode=xm,
                min_mom120_pct=mom,
                min_vote_entry=2,
                market_filter=mk,
                regime_mode=rg,
                weak_max_positions=wk,
                min_breadth=br,
            )
        )
    return profiles


def main() -> None:
    if not CACHE.is_file():
        print(f"缺少缓存 {CACHE}，请先跑 5 年回测生成 detail_cache_{DAYS}d.pkl")
        sys.exit(1)

    print(f"读取 {CACHE}")
    detail = pickle.loads(CACHE.read_bytes())
    start = trade_calendar_start(DAYS)
    ret_wide = detail.pivot(index="date", columns="code", values="ret")
    cal_df = load_daily_tail(sina_symbol("510300"), tail=history_tail_bars(DAYS))
    calendar = pd.DatetimeIndex(cal_df[cal_df["date"] >= start]["date"].unique()).sort_values()

    profiles = grid_profiles()
    print(f"扫描 {len(profiles)} 套规则...\n")
    rows = []
    best = None
    for i, rules in enumerate(profiles, 1):
        try:
            _pnl, _tr, m, _, _ = backtest_portfolio_buy_sell_max_n(
                detail, ret_wide, calendar_dates=calendar, rules=rules
            )
        except Exception as exc:
            print(f"  skip {rules.label}: {exc}")
            continue
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
            best = (rules, m["annual_return"], m)
        if i % 200 == 0:
            print(f"  ... {i}/{len(profiles)}  当前最优年化 {best[1]}%")

    df = pd.DataFrame(rows).sort_values("annual_return", ascending=False)
    out = ROOT / "mx_data_output" / "etf_daily" / "portfolio_tune_5y_results.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out, index=False, encoding="utf-8-sig")

    top = df.head(20)
    print("\n=== Top 20 (5年) ===")
    print(top.to_string(index=False))
    hit20 = df[df["annual_return"] >= 20]
    print(f"\n年化>=20%: {len(hit20)} 套")
    if not hit20.empty:
        print(hit20.head(10).to_string(index=False))
    print(f"\n最优: {best[0].label}  年化 {best[1]}%  回撤 {best[2]['max_drawdown']}%")
    print(f"结果: {out}")


if __name__ == "__main__":
    main()
