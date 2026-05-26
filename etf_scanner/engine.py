# -*- coding: utf-8 -*-
"""单只 ETF 评估与全市场扫描"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from backtest_kc50 import backtest
from etf_scanner.config import ScanConfig
from etf_scanner.data import load_daily
from etf_scanner.strategies import DEFAULT_STRATEGIES, PRACTICAL_IDS, StrategyDef


def cagr(total_pct: float, days: int) -> float:
    if days <= 0:
        return 0.0
    return round(((1 + total_pct / 100) ** (365.25 / days) - 1) * 100, 2)


def eval_one(
    code: str,
    name: str,
    sina: str,
    cfg: ScanConfig,
    strategies: list[StrategyDef],
) -> dict | None:
    df = load_daily(sina, cfg)
    if df is None:
        return None
    days = (df["date"].iloc[-1] - df["date"].iloc[0]).days
    row: dict = {
        "code": code,
        "name": name,
        "sina": sina,
        "bars": len(df),
        "start": str(df["date"].iloc[0].date()),
        "end": str(df["date"].iloc[-1].date()),
    }
    _, bh = backtest(df, pd.Series(1, index=df.index), "持有")
    row["bh_return"] = bh["total_return"]
    row["bh_cagr"] = cagr(bh["total_return"], days)
    row["bh_sharpe"] = bh["sharpe"]
    row["bh_dd"] = bh["max_drawdown"]

    beats = 0
    practical_cagrs = []
    for sd in strategies:
        sig = sd.build(df)
        _, m = backtest(df, sig.astype(int), sd.name)
        p = sd.id
        row[f"{p}_ret"] = m["total_return"]
        row[f"{p}_cagr"] = cagr(m["total_return"], days)
        row[f"{p}_sharpe"] = m["sharpe"]
        row[f"{p}_dd"] = m["max_drawdown"]
        row[f"{p}_trades"] = m["trades"]
        if m["total_return"] > bh["total_return"] and m["sharpe"] > bh["sharpe"]:
            beats += 1
        if p in PRACTICAL_IDS:
            practical_cagrs.append(row[f"{p}_cagr"])

    row["beats_bh"] = beats
    row["beats_all"] = beats == len(strategies)
    row["beats_practical"] = sum(
        1
        for sd in strategies
        if sd.id in PRACTICAL_IDS
        and row.get(f"{sd.id}_ret", 0) > bh["total_return"]
        and row.get(f"{sd.id}_sharpe", 0) > bh["sharpe"]
    )
    row["practical_cagr_avg"] = (
        round(sum(practical_cagrs) / len(practical_cagrs), 2) if practical_cagrs else None
    )
    row["score"] = round(
        (row["practical_cagr_avg"] or 0) * 0.5
        + row["beats_practical"] * 3
        + max(row.get("hi60_sharpe") or 0, 0) * 2,
        2,
    )
    return row


def scan_market(
    universe: pd.DataFrame,
    cfg: ScanConfig,
    strategies: list[StrategyDef] | None = None,
    on_progress: callable | None = None,
) -> pd.DataFrame:
    strategies = strategies or DEFAULT_STRATEGIES
    rows: list[dict] = []
    total = len(universe)
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=cfg.workers) as ex:
        futs = {
            ex.submit(eval_one, r.code, r.name, r.sina, cfg, strategies): r
            for r in universe.itertuples()
        }
        done = 0
        for fut in as_completed(futs):
            done += 1
            try:
                r = fut.result()
                if r:
                    rows.append(r)
            except Exception:
                pass
            if on_progress:
                on_progress(done, total, len(rows), time.time() - t0)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    return df.sort_values("score", ascending=False).reset_index(drop=True)
