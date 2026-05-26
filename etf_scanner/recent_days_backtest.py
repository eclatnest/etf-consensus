# -*- coding: utf-8 -*-
"""最近 N 个交易日：逐日全市场共识信号回放"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

from etf_scanner.config import ScanConfig
from etf_scanner.daily_signals import (
    LOOKBACK_BARS,
    consensus_label,
    load_daily_tail,
    signal_action_at,
)
from etf_scanner.data import load_etf_universe_cached, sina_symbol
from etf_scanner.strategies import PRACTICAL_IDS, DEFAULT_STRATEGIES, StrategyDef


def _trade_dates_from_df(df: pd.DataFrame, n_days: int) -> list[pd.Timestamp]:
    dates = df["date"].drop_duplicates().sort_values()
    if len(dates) < n_days + 1:
        return list(dates)
    return list(dates.iloc[-n_days:])


def eval_etf_history(
    code: str,
    name: str,
    trade_dates: list[pd.Timestamp],
    strategies: list[StrategyDef],
) -> list[dict]:
    sina = sina_symbol(code)
    df = load_daily_tail(sina, tail=LOOKBACK_BARS + len(trade_dates) + 5)
    if df is None:
        return []
    date_to_idx = {d.normalize(): i for i, d in enumerate(pd.to_datetime(df["date"]))}
    rows: list[dict] = []
    for td in trade_dates:
        key = pd.Timestamp(td).normalize()
        idx = date_to_idx.get(key)
        if idx is None or idx < 200:
            continue
        close = float(df["close"].iloc[idx])
        row: dict = {
            "code": code,
            "name": name,
            "signal_date": key.strftime("%Y-%m-%d"),
            "close": round(close, 4),
        }
        votes = 0
        for sd in strategies:
            if sd.id not in PRACTICAL_IDS:
                continue
            sig = sd.build(df)
            label, pos, _ = signal_action_at(sig, idx)
            row[f"{sd.id}_action"] = label
            row[f"{sd.id}_pos"] = pos
            if pos == 1:
                votes += 1
        row["vote_hold"] = votes
        row["consensus"] = consensus_label(row)
        rows.append(row)
    return rows


def scan_recent_days(
    cfg: ScanConfig,
    n_days: int = 10,
    universe: pd.DataFrame | None = None,
    sequential: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    strategies = [s for s in DEFAULT_STRATEGIES if s.id in PRACTICAL_IDS]
    universe = universe if universe is not None else load_etf_universe_cached(cfg)

    # 用流动性好的 ETF 取最近交易日历
    cal_df = load_daily_tail(sina_symbol("510300"), tail=LOOKBACK_BARS + n_days + 10)
    if cal_df is None:
        cal_df = load_daily_tail(sina_symbol("159915"), tail=LOOKBACK_BARS + n_days + 10)
    if cal_df is None:
        raise RuntimeError("无法加载基准 ETF 交易日历")
    trade_dates = _trade_dates_from_df(cal_df, n_days)
    print(f"回放交易日 ({len(trade_dates)} 天): {[d.strftime('%Y-%m-%d') for d in trade_dates]}\n")

    all_rows: list[dict] = []
    total = len(universe)
    t0 = time.time()
    workers = 1 if sequential else min(cfg.workers, 6)

    def _one(r) -> list[dict]:
        return eval_etf_history(r.code, r.name, trade_dates, strategies)

    if sequential:
        done = 0
        for r in universe.itertuples():
            done += 1
            try:
                all_rows.extend(_one(r))
            except Exception:
                pass
            if done % 100 == 0 or done == total:
                print(f"  进度 {done}/{total}  记录 {len(all_rows)}  {time.time()-t0:.0f}s")
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one, r): r for r in universe.itertuples()}
            done = 0
            for fut in as_completed(futs):
                done += 1
                try:
                    all_rows.extend(fut.result())
                except Exception:
                    pass
                if done % 100 == 0 or done == total:
                    print(f"  进度 {done}/{total}  记录 {len(all_rows)}  {time.time()-t0:.0f}s")

    detail = pd.DataFrame(all_rows)
    if detail.empty:
        return detail, pd.DataFrame()

    daily = (
        detail.groupby("signal_date", as_index=False)
        .agg(
            valid=("code", "count"),
            buy=("consensus", lambda s: (s == "买入").sum()),
            sell=("consensus", lambda s: (s == "卖出").sum()),
            hold=("consensus", lambda s: (s == "持有").sum()),
            watch=("consensus", lambda s: (s == "观望").sum()),
            empty=("consensus", lambda s: (s == "空仓").sum()),
        )
        .sort_values("signal_date")
    )
    return detail, daily


def write_recent_report(detail: pd.DataFrame, daily: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    daily.to_csv(out_dir / "daily_summary.csv", index=False, encoding="utf-8-sig")
    detail.to_csv(out_dir / "signals_by_day.csv", index=False, encoding="utf-8-sig")

    for d in daily["signal_date"]:
        sub = detail[detail["signal_date"] == d]
        day_dir = out_dir / d.replace("-", "")
        day_dir.mkdir(exist_ok=True)
        sub[sub["consensus"] == "买入"].to_csv(day_dir / "buy.csv", index=False, encoding="utf-8-sig")
        sub[sub["consensus"] == "卖出"].to_csv(day_dir / "sell.csv", index=False, encoding="utf-8-sig")
        sub[sub["consensus"] == "持有"].to_csv(day_dir / "hold.csv", index=False, encoding="utf-8-sig")

    lines = ["# 最近交易日 ETF 共识信号回放\n", "| 信号日(收盘) | 有效ETF | 买入 | 卖出 | 持有 | 观望 | 空仓 |\n", "|---|---:|---:|---:|---:|---:|---:|\n"]
    for _, r in daily.iterrows():
        lines.append(
            f"| {r['signal_date']} | {int(r['valid'])} | {int(r['buy'])} | {int(r['sell'])} | "
            f"{int(r['hold'])} | {int(r['watch'])} | {int(r['empty'])} |\n"
        )
    (out_dir / "README.md").write_text("".join(lines), encoding="utf-8")
