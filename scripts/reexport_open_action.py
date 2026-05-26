#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从已有回测目录 + detail 缓存，重导出带「次日开盘操作」列的 pnl_by_etf_all.csv"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etf_scanner.consensus_backtest import load_benchmark_regime, history_tail_bars
from etf_scanner.portfolio_export import enrich_pnl_by_etf_next_action, mark_etf_actions
from etf_scanner.portfolio_rules import PROFILE_5Y_N5_MOM25


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--dir",
        default=str(ROOT / "mx_data_output" / "etf_daily" / "backtest_10pos_5y_20260526_2159"),
    )
    ap.add_argument("--days", type=int, default=1260)
    args = ap.parse_args()

    out = Path(args.dir)
    all_path = out / "pnl_by_etf_all.csv"
    trades_path = out / "trades_marked.csv"
    if not all_path.is_file():
        raise FileNotFoundError(all_path)

    cache = ROOT / "mx_data_output" / "etf_daily" / f"detail_cache_{args.days}d.pkl"
    if not cache.is_file():
        raise FileNotFoundError(f"缺少 {cache}")

    detail = pickle.loads(cache.read_bytes())
    all_etf = pd.read_csv(all_path, encoding="utf-8-sig")
    trades = pd.read_csv(trades_path, encoding="utf-8-sig") if trades_path.is_file() else pd.DataFrame()
    all_etf = mark_etf_actions(all_etf, trades)
    bench = load_benchmark_regime(history_tail_bars(args.days))
    all_etf = enrich_pnl_by_etf_next_action(all_etf, detail, PROFILE_5Y_N5_MOM25, bench)
    all_etf.to_csv(all_path, index=False, encoding="utf-8-sig")
    print(f"已更新 {all_path}")
    print(all_etf[["date", "code", "next_open_action", "next_open_brief"]].tail(8).to_string(index=False))


if __name__ == "__main__":
    main()
