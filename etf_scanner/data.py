# -*- coding: utf-8 -*-
"""ETF 列表与行情"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import akshare as ak
import pandas as pd

from etf_scanner.config import ScanConfig

UNIVERSE_CACHE = Path(__file__).resolve().parent.parent / "mx_data_output" / "etf_daily" / "universe.csv"


def sina_symbol(code: str) -> str:
    c = str(code).strip().zfill(6)
    if c.startswith(("159", "16", "15", "18")):
        return f"sz{c}"
    return f"sh{c}"


def load_etf_universe(cfg: ScanConfig) -> pd.DataFrame:
    df = ak.fund_etf_spot_em()
    df = df.rename(columns={"代码": "code", "名称": "name"})
    df["code"] = df["code"].astype(str).str.zfill(6)
    mask = df["name"].str.contains(cfg.name_must_contain, na=False)
    for kw in cfg.exclude_keywords:
        mask &= ~df["name"].str.contains(kw, na=False)
    out = df[mask][["code", "name"]].drop_duplicates("code").reset_index(drop=True)
    out["sina"] = out["code"].map(sina_symbol)
    return out


def load_etf_universe_cached(cfg: ScanConfig, refresh: bool = False) -> pd.DataFrame:
    """主线程拉取列表并缓存，避免并发调用 akshare 东财接口崩溃。"""
    today = datetime.now().strftime("%Y%m%d")
    UNIVERSE_CACHE.parent.mkdir(parents=True, exist_ok=True)
    if not refresh and UNIVERSE_CACHE.is_file():
        cached = pd.read_csv(UNIVERSE_CACHE, dtype={"code": str})
        if not cached.empty and str(cached.get("cache_date", [""]).iloc[0]) == today:
            cached["code"] = cached["code"].astype(str).str.zfill(6)
            if "sina" not in cached.columns:
                cached["sina"] = cached["code"].map(sina_symbol)
            return cached[["code", "name", "sina"]].reset_index(drop=True)
    out = load_etf_universe(cfg)
    out.assign(cache_date=today).to_csv(UNIVERSE_CACHE, index=False, encoding="utf-8-sig")
    return out


def load_daily(sina: str, cfg: ScanConfig) -> pd.DataFrame | None:
    start = pd.Timestamp(cfg.start)
    end = pd.Timestamp(cfg.end)
    try:
        df = ak.fund_etf_hist_sina(symbol=sina)
        df["date"] = pd.to_datetime(df["date"])
        for c in ("open", "high", "low", "close"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.sort_values("date").dropna(subset=["close"])
        df = df[(df["date"] >= start) & (df["date"] <= end)]
        if len(df) < cfg.min_bars:
            return None
        return df.reset_index(drop=True)
    except Exception:
        return None
