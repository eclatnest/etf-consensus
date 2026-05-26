#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""共识策略：仅新买入等权 + 卖出清仓，最多持仓 10 只"""
from __future__ import annotations

import argparse
import pickle
from datetime import datetime
from pathlib import Path

import pandas as pd

from etf_scanner.config import ScanConfig
from etf_scanner.consensus_backtest import (
    backtest_portfolio_buy_sell_max_n,
    build_signal_detail,
    history_tail_bars,
    load_benchmark_regime,
    trade_calendar_start,
)
from etf_scanner.portfolio_export import write_portfolio_exports
from etf_scanner.portfolio_rules import (
    BASELINE,
    DEFAULT_5Y,
    DEFAULT_ENHANCED,
    PROFILE_5Y_N5_MOM25,
    PortfolioRules,
)
from etf_scanner.daily_signals import load_daily_tail
from etf_scanner.data import load_etf_universe_cached, sina_symbol

ROOT = Path(__file__).resolve().parent


def detail_cache_path(days: int) -> Path:
    return ROOT / "mx_data_output" / "etf_daily" / f"detail_cache_{days}d.pkl"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=252, help="回测交易日数，5年约 1260")
    ap.add_argument("--max-pos", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sequential", action="store_true")
    ap.add_argument("--cost", type=float, default=0.0005)
    ap.add_argument("--cash", type=float, default=100_000.0)
    ap.add_argument("--out", default="")
    ap.add_argument(
        "--profile",
        choices=("baseline", "enhanced", "enhanced5y", "enhanced5y_n5", "mom5"),
        default="enhanced",
        help="enhanced5y_n5=三票+动量25%+5仓+MA200; enhanced5y=5年最优2仓; mom5=动量>5%",
    )
    args = ap.parse_args()

    profiles = {
        "baseline": BASELINE,
        "enhanced": DEFAULT_ENHANCED,
        "enhanced5y": DEFAULT_5Y,
        "enhanced5y_n5": PROFILE_5Y_N5_MOM25,
        "mom5": PortfolioRules(10, "fill_vote2_mom5", "vote_lt2", 5.0, 2),
    }
    rules = profiles[args.profile]

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    suffix = "5y" if args.days >= 1200 else f"{args.days}d"
    out = (
        Path(args.out)
        if args.out
        else ROOT / "mx_data_output" / "etf_daily" / f"backtest_10pos_{suffix}_{ts}"
    )

    cfg = ScanConfig(workers=args.workers, cost=args.cost, init_cash=args.cash)
    start = trade_calendar_start(args.days)
    cache = detail_cache_path(args.days)

    print(f"=== 共识组合回测 · 规则 {rules.label} · 最多 {rules.max_positions} 只 ===\n")
    print(f"回测 {args.days} 个交易日，起始约: {start.date()}\n")

    if cache.is_file():
        print(f"读取信号缓存: {cache}\n")
        detail = pickle.loads(cache.read_bytes())
    else:
        universe = load_etf_universe_cached(cfg)
        detail = build_signal_detail(
            cfg, start, universe, sequential=args.sequential, trade_days=args.days
        )
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(pickle.dumps(detail))
    if detail.empty:
        print("无数据")
        return

    ret_wide = detail.pivot(index="date", columns="code", values="ret")
    cal_df = load_daily_tail(sina_symbol("510300"), tail=history_tail_bars(args.days))
    calendar = pd.DatetimeIndex(cal_df[cal_df["date"] >= start]["date"].unique()).sort_values()

    pnl, trades, m, daily_weights, etf_records = backtest_portfolio_buy_sell_max_n(
        detail,
        ret_wide,
        max_positions=args.max_pos,
        cost=args.cost,
        init_cash=args.cash,
        calendar_dates=calendar,
        rules=rules,
    )

    end = pd.Timestamp(pnl["date"].iloc[-1])
    out.mkdir(parents=True, exist_ok=True)
    names = detail.drop_duplicates("code").set_index("code")["name"].astype(str).to_dict()
    bench = (
        load_benchmark_regime(history_tail_bars(args.days))
        if rules.market_filter != "none" or rules.regime_mode != "none"
        else pd.DataFrame()
    )
    write_portfolio_exports(
        out,
        pnl,
        trades,
        etf_records,
        daily_weights,
        names,
        args.cash,
        start,
        end,
        args.cost,
        detail=detail,
        rules=rules,
        bench_regime=bench,
    )
    summary = {**m, "start": start.strftime("%Y-%m-%d"), "end": end.strftime("%Y-%m-%d"), "init_cash": args.cash, "cost_per_side": args.cost}
    pd.DataFrame([summary]).to_csv(out / "portfolio_summary.csv", index=False, encoding="utf-8-sig")

    trades.to_csv(out / "trades_marked.csv", index=False, encoding="utf-8-sig")

    (out / "README.md").write_text(
        f"""# 共识组合回测

规则: `{rules.label}`

- entry: {rules.entry_mode} | exit: {rules.exit_mode} | max_pos: {rules.max_positions}
- pnl_daily: buy_codes / sell_codes / trade_flag / holdings_display([买][卖][持])
- trades_marked.csv: 全部买卖记录

区间: {start.date()} ~ {end.date()}
""",
        encoding="utf-8",
    )

    print("【组合】")
    print(f"  区间: {start.date()} ~ {end.date()}")
    print(f"  总收益: {m['total_return']}%  |  年化: {m['annual_return']}%")
    print(f"  PnL: {m['pnl_abs']:,.2f}  |  期末: {m['final_equity']:,.2f}")
    print(f"  最大回撤: {m['max_drawdown']}%  |  Sharpe: {m['sharpe']}  |  PF: {m['profit_factor']}")
    print(f"  组合买入: {m['portfolio_buys']}  |  卖出: {m['portfolio_sells']}  |  回合: {m['round_trips']}")
    print(f"  日均持仓: {m['avg_held']}  |  最多: {m['max_held']}")

    if not trades.empty:
        print("\n【最近 10 笔交易】")
        print(trades.tail(10).to_string(index=False))

    print(f"\n输出: {out.resolve()}")
    print("  pnl_daily.csv (holdings_codes|weights|display)")
    print("  pnl_by_etf_all.csv / pnl_by_etf_summary.csv / pnl_by_etf/*.csv")


if __name__ == "__main__":
    main()
