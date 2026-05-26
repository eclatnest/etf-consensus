# -*- coding: utf-8 -*-
"""科创50 日线回测 — 多策略对比（ETF 588000 / 指数 000688）"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

OUT = Path(__file__).resolve().parent / "mx_data_output"
SYMBOL_ETF = "588000"
SYMBOL_INDEX = "000688"
FETCH_START = "20190101"
END = "20260525"
BARS = 2000  # 目标交易日；科创50约2020年起，实际可用约1500根
DATA_SOURCE = ""
COST = 0.0005  # 单边佣金+滑点 5bp
INIT_CASH = 100_000.0


def fetch_daily_em(secid: str) -> pd.DataFrame:
    import json
    import urllib.request

    url = (
        "https://push2his.eastmoney.com/api/qt/stock/kline/get?"
        f"secid={secid}&klt=101&fqt=1&lmt=12000"
        "&fields1=f1,f2,f3,f4,f5,f6"
        "&fields2=f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61"
        f"&beg={FETCH_START}&end={END}"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://quote.eastmoney.com/"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read().decode())
    klines = data.get("data", {}).get("klines") or []
    rows = [k.split(",") for k in klines]
    df = pd.DataFrame(
        rows,
        columns=["date", "open", "close", "high", "low", "vol", "amt", "amp", "pct", "chg", "turn"],
    )
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("date").dropna(subset=["close"]).reset_index(drop=True)


def fetch_index_ak() -> pd.DataFrame:
    import akshare as ak

    global DATA_SOURCE
    df = ak.stock_zh_index_daily(symbol="sh000688")
    df["date"] = pd.to_datetime(df["date"])
    df = df[df["date"] <= pd.Timestamp(END)]
    for c in ("open", "high", "low"):
        if c not in df.columns:
            df[c] = df["close"]
    DATA_SOURCE = f"科创50指数 {SYMBOL_INDEX}"
    return df.sort_values("date").dropna(subset=["close"]).reset_index(drop=True)


def fetch_etf_ak() -> pd.DataFrame:
    import akshare as ak

    global DATA_SOURCE
    df = ak.fund_etf_hist_em(
        symbol=SYMBOL_ETF, period="daily", start_date=FETCH_START, end_date=END, adjust="qfq"
    )
    df = df.rename(columns={"日期": "date", "收盘": "close", "开盘": "open", "最高": "high", "最低": "low"})
    df["date"] = pd.to_datetime(df["date"])
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    DATA_SOURCE = f"科创50ETF {SYMBOL_ETF}"
    return df.sort_values("date").dropna(subset=["close"]).reset_index(drop=True)


def fetch_daily() -> pd.DataFrame:
    global DATA_SOURCE
    candidates: list[tuple[str, pd.DataFrame]] = []
    for label, fn in (
        (f"科创50指数 {SYMBOL_INDEX}", fetch_index_ak),
        (f"科创50ETF {SYMBOL_ETF}", fetch_etf_ak),
    ):
        try:
            candidates.append((label, fn()))
        except Exception:
            pass
    try:
        candidates.append((f"科创50ETF {SYMBOL_ETF}(东财)", fetch_daily_em(f"1.{SYMBOL_ETF}")))
    except Exception:
        pass
    if not candidates:
        raise RuntimeError("无法获取行情数据")
    label, df = max(candidates, key=lambda x: len(x[1]))
    DATA_SOURCE = label
    return df.reset_index(drop=True)


def trim_bars(df: pd.DataFrame) -> pd.DataFrame:
    df = df.sort_values("date").dropna(subset=["close"]).reset_index(drop=True)
    if len(df) > BARS:
        df = df.tail(BARS).reset_index(drop=True)
    return df


def metrics(equity: pd.Series, ret: pd.Series, dates: pd.Series) -> dict:
    total = equity.iloc[-1] / equity.iloc[0] - 1
    cal_days = max((dates.iloc[-1] - dates.iloc[0]).days, 1)
    trade_days = len(dates)
    ann = (1 + total) ** (365 / cal_days) - 1
    dd = (equity / equity.cummax() - 1).min()
    sharpe = 0.0
    if ret.std() > 0:
        sharpe = ret.mean() / ret.std() * np.sqrt(252)
    win = (ret > 0).sum() / max(len(ret), 1)
    return {
        "total_return": round(total * 100, 2),
        "annual_return": round(ann * 100, 2),
        "max_drawdown": round(dd * 100, 2),
        "sharpe": round(sharpe, 2),
        "win_rate": round(win * 100, 2),
        "final_equity": round(equity.iloc[-1], 2),
        "trade_days": trade_days,
    }


def rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(n).mean()
    loss = (-delta.clip(upper=0)).rolling(n).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def sma(close: pd.Series, n: int) -> pd.Series:
    return close.rolling(n).mean()


def build_strategies(df: pd.DataFrame) -> list[tuple[str, pd.Series]]:
    """候选策略：侧重降波动、减无效换手以抬高 Sharpe"""
    close = df["close"]
    ret = close.pct_change()
    vol20 = ret.rolling(20).std() * np.sqrt(252)
    vol_med = vol20.rolling(120).median()
    out: list[tuple[str, pd.Series]] = [
        ("买入持有", pd.Series(1, index=df.index)),
        ("跌破20日均线空仓", (close > sma(close, 20)).astype(int)),
        ("MA5/20金叉", (sma(close, 5) > sma(close, 20)).astype(int)),
    ]

    for f, s in ((5, 20), (10, 30), (10, 50), (20, 60), (5, 60), (10, 60), (20, 120)):
        out.append((f"MA{f}/{s}金叉", (sma(close, f) > sma(close, s)).astype(int)))
        out.append((f"收盘>{s}日均线", (close > sma(close, s)).astype(int)))

    for n in (20, 40, 60, 120):
        out.append((f"动量{n}日>0", (close.pct_change(n) > 0).astype(int)))

    r = rsi(close)
    for th in (45, 50, 55):
        out.append((f"RSI14>{th}持有", (r > th).astype(int)))
    # 网格优选：RSI10>45 在科创50全样本 Sharpe 最高
    out.insert(3, ("RSI10>45持有(优选)", (rsi(close, 10) > 45).astype(int)))

    ma5, ma20, ma60 = sma(close, 5), sma(close, 20), sma(close, 60)
    out.append(
        ("MA5>20且收盘>MA60", ((ma5 > ma20) & (close > ma60)).astype(int)),
    )
    out.append(
        ("MA5>20且动量60>0", ((ma5 > ma20) & (close.pct_change(60) > 0)).astype(int)),
    )
    out.append(
        ("收盘>MA20且低波动", ((close > ma20) & (vol20 < vol_med)).astype(int)),
    )
    out.append(
        ("收盘>MA60且低波动", ((close > ma60) & (vol20 < vol_med)).astype(int)),
    )

    # 金叉确认 2 日，减少假突破
    cross = (ma5 > ma20).astype(int)
    confirm = ((ma5 > ma20) & (ma5.shift(1) > ma20.shift(1))).astype(int)
    out.append(("MA5/20金叉(确认2日)", confirm))

    # 唐奇安简化：突破 20 日高持有，跌破 10 日低空仓（状态近似）
    hi20 = close.rolling(20).max().shift(1)
    lo10 = close.rolling(10).min().shift(1)
    turtle = np.where(close >= hi20, 1, np.where(close <= lo10, 0, np.nan))
    turtle = pd.Series(turtle, index=df.index).ffill().fillna(0).astype(int)
    out.append(("唐奇安20/10", turtle))

    # 20 日高点回撤 8% 止损 + 价格在 MA60 上方才开仓
    peak = close.rolling(20).max()
    trail = (close > peak.shift(1) * 0.92).astype(int)
    out.append(("20日高点-8%追踪", trail))
    out.append(("MA60+20日-8%追踪", (trail & (close > ma60)).astype(int)))

    for pct in (0.06, 0.08, 0.10):
        pk = close.rolling(40).max()
        out.append((f"40日高点-{int(pct*100)}%追踪", (close > pk.shift(1) * (1 - pct)).astype(int)))

    return out


def backtest_vol_scaled(df: pd.DataFrame, base_signal: pd.Series, name: str, target_vol: float = 0.18) -> tuple[pd.DataFrame, dict]:
    """在趋势信号基础上做波动率缩放仓位，目标年化波动 target_vol"""
    d = df.copy()
    ret = d["close"].pct_change()
    realized = ret.rolling(20).std() * np.sqrt(252)
    weight = (base_signal * (target_vol / realized.replace(0, np.nan))).clip(0, 1)
    weight = weight.shift(1).fillna(0)
    d["pos_change"] = weight.diff().abs().fillna(weight.iloc[0])
    d["cost"] = d["pos_change"] * COST
    d["strat_ret"] = weight * ret - d["cost"]
    d["equity"] = INIT_CASH * (1 + d["strat_ret"]).fillna(1).cumprod()
    m = metrics(d["equity"], d["strat_ret"].dropna(), d["date"])
    m["strategy"] = name
    m["trades"] = int((weight.diff().abs() > 0.05).sum())
    return d, m


def backtest(df: pd.DataFrame, signal: pd.Series, name: str) -> tuple[pd.DataFrame, dict]:
    """signal: 1=持仓, 0=空仓；T日信号 T+1开盘换仓"""
    d = df.copy()
    d["signal"] = signal.shift(1).fillna(0).astype(int)
    d["ret_mkt"] = d["close"].pct_change()
    d["pos_change"] = d["signal"].diff().abs().fillna(0)
    d["cost"] = d["pos_change"] * COST
    d["strat_ret"] = d["signal"] * d["ret_mkt"] - d["cost"]
    d["equity"] = INIT_CASH * (1 + d["strat_ret"]).fillna(1).cumprod()
    m = metrics(d["equity"], d["strat_ret"].dropna(), d["date"])
    m["strategy"] = name
    m["trades"] = int(d["pos_change"].sum() / 2)
    return d, m


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    df = trim_bars(fetch_daily())
    if len(df) < BARS:
        print(
            f"说明: 科创50自2020年才有连续行情，全历史约 {len(df)} 根，"
            f"不足目标 {BARS} 根，已用**全部可用日线**回测。"
        )
    close = df["close"]
    ret = close.pct_change()
    vol20 = ret.rolling(20).std() * np.sqrt(252)
    vol_med = vol20.rolling(120).median()
    strategies = build_strategies(df)

    rows = []
    detail = df[["date", "open", "high", "low", "close"]].copy()
    for name, sig in strategies:
        res, m = backtest(df, sig, name)
        rows.append(m)

    vol_bases = [
        ("跌破20日均线空仓", (close > sma(close, 20)).astype(int)),
        ("MA5/20金叉", (sma(close, 5) > sma(close, 20)).astype(int)),
        (
            "收盘>MA60且低波动",
            ((close > sma(close, 60)) & (vol20 < vol_med)).astype(int),
        ),
    ]
    for bname, bsig in vol_bases:
        for tv in (0.12, 0.15, 0.18):
            vname = f"{bname}+波动目标{int(tv * 100)}%"
            res, m = backtest_vol_scaled(df, bsig, vname, target_vol=tv)
            rows.append(m)

    bench_ret = (close.iloc[-1] / close.iloc[0] - 1) * 100
    summary = pd.DataFrame(rows)
    top_sharpe = summary.sort_values("sharpe", ascending=False).head(15)
    top_return = summary.sort_values("total_return", ascending=False).head(10)
    summary = summary.sort_values("sharpe", ascending=False)
    summary["benchmark_bh_pct"] = round(bench_ret, 2)
    summary["data_source"] = DATA_SOURCE
    summary["bars_target"] = BARS
    summary["bars_actual"] = len(df)

    out_csv = OUT / "kc50_backtest_results.csv"
    out_sum = OUT / "kc50_backtest_summary.csv"
    detail.to_csv(out_csv, index=False, encoding="utf-8-sig")
    summary.to_csv(out_sum, index=False, encoding="utf-8-sig")

    print(
        f"数据源: {DATA_SOURCE} | {df['date'].iloc[0].date()} ~ {df['date'].iloc[-1].date()} "
        f"| {len(df)} 根K线 (目标 {BARS})"
    )
    print(f"买入持有基准收益: {bench_ret:.2f}%")
    bh_sharpe = summary.loc[summary["strategy"] == "买入持有", "sharpe"].iloc[0]
    print(f"买入持有 Sharpe: {bh_sharpe}")
    print("\n=== Sharpe Top 15 ===")
    print(top_sharpe.to_string(index=False))
    print("\n=== 总收益 Top 10 ===")
    print(top_return.to_string(index=False))
    out_top = OUT / "kc50_backtest_top_sharpe.csv"
    top_sharpe.to_csv(out_top, index=False, encoding="utf-8-sig")
    print(f"\nSharpe排行: {out_top}")
    print(f"\n明细: {out_csv}")
    print(f"汇总: {out_sum}")


if __name__ == "__main__":
    main()
