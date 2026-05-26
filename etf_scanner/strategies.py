# -*- coding: utf-8 -*-
"""可注册的策略信号"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import pandas as pd

from backtest_kc50 import sma
from hs300_strategies_extended import donchian


@dataclass(frozen=True)
class StrategyDef:
    id: str
    name: str
    group: str  # momentum | trend | defensive
    description: str
    build: Callable[[pd.DataFrame], pd.Series]


def _mom120_5(df: pd.DataFrame) -> pd.Series:
    return (df["close"].pct_change(120) > 0.05).astype(int)


def _donchian_30_10(df: pd.DataFrame) -> pd.Series:
    return donchian(df["close"], 30, 10)


def _high60(df: pd.DataFrame) -> pd.Series:
    hi = df["close"].rolling(60).max().shift(1)
    return (df["close"] >= hi).astype(int)


def _ma60(df: pd.DataFrame) -> pd.Series:
    return (df["close"] > sma(df["close"], 60)).astype(int)


def _rsi_ma(df: pd.DataFrame) -> pd.Series:
    from backtest_kc50 import rsi

    c = df["close"]
    return ((rsi(c, 10) > 50) & (c > sma(c, 60))).astype(int)


DEFAULT_STRATEGIES: list[StrategyDef] = [
    StrategyDef("mom120_5", "动量120日>5%", "momentum", "120日涨幅>5%持仓", _mom120_5),
    StrategyDef("dc30_10", "唐奇安30/10", "trend", "30日高突破/10日低出场", _donchian_30_10),
    StrategyDef("hi60", "60日新高突破", "defensive", "突破60日前高", _high60),
    StrategyDef("ma60", "收盘>MA60", "benchmark", "对照：纯均线", _ma60),
    StrategyDef("rsi_ma60", "RSI10>50且>MA60", "benchmark", "对照：沪深300常用", _rsi_ma),
]

PRACTICAL_IDS = ("mom120_5", "dc30_10", "hi60")
