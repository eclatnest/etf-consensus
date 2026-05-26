#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""最近 N 个交易日逐日回放共识买卖信号（默认 10 天）"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from etf_scanner.config import ScanConfig
from etf_scanner.data import load_etf_universe_cached
from etf_scanner.recent_days_backtest import scan_recent_days, write_recent_report

ROOT = Path(__file__).resolve().parent


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=10)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--sequential", action="store_true")
    ap.add_argument("--out", default="")
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out = Path(args.out) if args.out else ROOT / "mx_data_output" / "etf_daily" / f"backtest_{args.days}d_{ts}"

    cfg = ScanConfig(workers=args.workers)
    print(f"=== ETF 共识策略 · 最近 {args.days} 个交易日回放 ===\n")
    universe = load_etf_universe_cached(cfg)
    print(f"ETF 列表: {len(universe)} 只\n")

    detail, daily = scan_recent_days(cfg, n_days=args.days, universe=universe, sequential=args.sequential)
    if daily.empty:
        print("无数据")
        return

    write_recent_report(detail, daily, out)

    print("\n【逐日统计】信号日=当日收盘，次日开盘执行\n")
    cols = ["signal_date", "valid", "buy", "sell", "hold", "watch", "empty"]
    print(daily[cols].to_string(index=False))

    print("\n【每日共识买入 TOP10】")
    for d in daily["signal_date"]:
        buys = detail[(detail["signal_date"] == d) & (detail["consensus"] == "买入")]
        sells = detail[(detail["signal_date"] == d) & (detail["consensus"] == "卖出")]
        print(f"\n--- {d} 买{len(buys)} / 卖{len(sells)} ---")
        if not buys.empty:
            show = buys.sort_values("vote_hold", ascending=False).head(10)
            print(
                show[["code", "name", "close", "vote_hold", "mom120_5_action", "dc30_10_action", "hi60_action"]].to_string(
                    index=False
                )
            )
        if not sells.empty:
            print("卖出:", ", ".join(f"{r.code} {r.name}" for r in sells.head(8).itertuples()))

    print(f"\n输出: {out}")
    print("  daily_summary.csv / signals_by_day.csv / YYYYMMDD/buy|sell|hold.csv")


if __name__ == "__main__":
    main()
