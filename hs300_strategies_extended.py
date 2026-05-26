# -*- coding: utf-8 -*-
"""沪深300 扩展策略库"""
from __future__ import annotations

import numpy as np
import pandas as pd

from backtest_kc50 import build_strategies, rsi, sma


def ema(close: pd.Series, n: int) -> pd.Series:
    return close.ewm(span=n, adjust=False).mean()


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> tuple[pd.Series, pd.Series, pd.Series]:
    ef = ema(close, fast)
    es = ema(close, slow)
    line = ef - es
    sig = ema(line, signal)
    hist = line - sig
    return line, sig, hist


def atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev = close.shift(1)
    tr = pd.concat([(high - low), (high - prev).abs(), (low - prev).abs()], axis=1).max(axis=1)
    return tr.rolling(n).mean()


def donchian(close: pd.Series, entry: int, exit_n: int) -> pd.Series:
    hi = close.rolling(entry).max().shift(1)
    lo = close.rolling(exit_n).min().shift(1)
    raw = np.where(close >= hi, 1, np.where(close <= lo, 0, np.nan))
    return pd.Series(raw, index=close.index).ffill().fillna(0).astype(int)


def build_hs300_extended(df: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    close = df["close"]
    ret = close.pct_change()
    vol20 = ret.rolling(20).std() * np.sqrt(252)
    vol60 = ret.rolling(60).std() * np.sqrt(252)
    vol_med = vol20.rolling(120).median()

    out: list[tuple[str, pd.Series]] = []
    seen: set[str] = set()

    def add(name: str, sig: pd.Series) -> None:
        if name in seen:
            return
        seen.add(name)
        out.append((name, sig.astype(int)))

    # 原有策略
    for name, sig in build_strategies(df):
        add(name, sig)

    ma20, ma60, ma120 = sma(close, 20), sma(close, 60), sma(close, 120)

    # --- 均线网格 ---
    for n in (40, 70, 80, 90, 100, 150, 200):
        add(f"收盘>{n}日均线", (close > sma(close, n)).astype(int))

    for f, s in ((12, 26), (15, 40), (20, 80), (30, 90)):
        add(f"EMA{f}/{s}金叉", (ema(close, f) > ema(close, s)).astype(int))

    # MA 斜率：60日均线向上
    add("MA60上行且收盘>MA60", ((ma60 > ma60.shift(10)) & (close > ma60)).astype(int))
    add("MA60上行且收盘>MA50", ((ma60 > ma60.shift(10)) & (close > sma(close, 50))).astype(int))

    # --- MACD ---
    line, sig_l, hist = macd(close)
    add("MACD金叉", (line > sig_l).astype(int))
    add("MACD柱>0", (hist > 0).astype(int))
    add("MACD>0且收盘>MA60", ((line > 0) & (close > ma60)).astype(int))

    # --- 布林带 ---
    mid = sma(close, 20)
    std = close.rolling(20).std()
    upper, lower = mid + 2 * std, mid - 2 * std
    add("布林中轨上方", (close > mid).astype(int))
    add("布林突破上轨", (close > upper).astype(int))
    add("布林中轨且RSI>50", ((close > mid) & (rsi(close) > 50)).astype(int))

    # --- 唐奇安变体 ---
    for ent, ex in ((55, 20), (40, 15), (30, 10)):
        add(f"唐奇安{ent}/{ex}", donchian(close, ent, ex))

    # --- 新高突破 ---
    for n in (60, 120, 252):
        hi = close.rolling(n).max().shift(1)
        add(f"{n}日新高突破", (close >= hi).astype(int))

    # 252 日新高 + 趋势过滤
    hi252 = close.rolling(252).max().shift(1)
    add("252日新高且>MA60", ((close >= hi252) & (close > ma60)).astype(int))

    # --- Keltner ---
    e20 = ema(close, 20)
    a = atr(df, 14)
    add("Keltner上方", (close > e20 + a).astype(int))
    add("Keltner中轨上方", (close > e20).astype(int))

    # --- 复合趋势 ---
    add("三重趋势(>MA60,MA20>MA60,动量60)", ((close > ma60) & (ma20 > ma60) & (close.pct_change(60) > 0)).astype(int))
    add("收盘>MA50且低波动", ((close > sma(close, 50)) & (vol20 < vol_med)).astype(int))
    add("收盘>MA90且低波动", ((close > sma(close, 90)) & (vol20 < vol_med)).astype(int))
    add("收盘>MA60且波动<60日", ((close > ma60) & (vol20 < vol60)).astype(int))

    # --- 回撤过滤 ---
    peak60 = close.rolling(60).max()
    add("60日内回撤<10%持有", (close > peak60.shift(1) * 0.90).astype(int))
    add("60日回撤<10%且>MA60", ((close > peak60.shift(1) * 0.90) & (close > ma60)).astype(int))

    # --- 动量排名风格 ---
    for n in (60, 90, 120):
        add(f"动量{n}日>5%", (close.pct_change(n) > 0.05).astype(int))

    # --- 低波环境做多 ---
    add("低波环境全多", (vol20 < vol_med).astype(int))

    # --- RSI 组合 ---
    for n, th in ((10, 50), (14, 48), (14, 52)):
        add(f"RSI{n}>{th}且>MA60", ((rsi(close, n) > th) & (close > ma60)).astype(int))

    return out
