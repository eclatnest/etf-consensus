#!/usr/bin/env python
# -*- coding: utf-8 -*-
import pickle
import sys
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
from etf_scanner.portfolio_rules import PortfolioRules

detail = pickle.loads((ROOT / "mx_data_output/etf_daily/detail_cache_1260d.pkl").read_bytes())
start = trade_calendar_start(1260)
ret_wide = detail.pivot(index="date", columns="code", values="ret")
cal = load_daily_tail(sina_symbol("510300"), tail=history_tail_bars(1260))
calendar = pd.DatetimeIndex(cal[cal["date"] >= start]["date"].unique()).sort_values()

tests = []
for mp in [3, 5, 8, 10]:
    for mom in [10, 15, 20, 25, 30]:
        for mk, rg in [
            ("ma200", "force_cash"),
            ("ma200", "no_buy"),
            ("ma60", "force_cash"),
            ("mom120_pos", "force_cash"),
        ]:
            for em, xm in [
                ("fill_vote2", "vote_lt2"),
                ("fill_vote2", "sell_only"),
                ("fill_vote3", "vote_lt2"),
                ("buy_only", "sell_only"),
            ]:
                if em == "buy_only" and mom > 0:
                    continue
                tests.append(PortfolioRules(mp, em, xm, mom, 2, mk, rg))

rows = []
for r in tests:
    _, _, m, _, _ = backtest_portfolio_buy_sell_max_n(
        detail, ret_wide, calendar_dates=calendar, rules=r
    )
    rows.append(
        (m["annual_return"], m["max_drawdown"], m["avg_held"], m["portfolio_buys"], r.label)
    )

rows.sort(reverse=True)
for x in rows[:20]:
    print(f"ann={x[0]:6.2f} dd={x[1]:6.2f} held={x[2]:4.2f} buys={x[3]:4d} {x[4]}")
print("--- hit20", sum(1 for x in rows if x[0] >= 20))
