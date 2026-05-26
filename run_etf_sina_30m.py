# -*- coding: utf-8 -*-
"""新浪 30 分钟 + 唐奇安 55/20(440/160) 回测，用法: python run_etf_sina_30m.py 513050"""
from __future__ import annotations

import sys
from pathlib import Path

import akshare as ak
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

from backtest_kc50 import COST, INIT_CASH, backtest
from hs300_strategies_extended import donchian

BASE = Path(r"C:\Users\25739\.cursor\projects\empty-window\mx_data_output")
STRAT = "唐奇安55/20(日等价440/160根)"


def fetch_sina_30m(sina_sym: str) -> pd.DataFrame:
    df = ak.stock_zh_a_minute(symbol=sina_sym, period="30", adjust="qfq")
    df = df.rename(columns={"day": "dt"})
    df["dt"] = pd.to_datetime(df["dt"])
    for c in ("open", "high", "low", "close"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("dt").dropna(subset=["close"]).reset_index(drop=True)


def fetch_sina_daily(sina_sym: str) -> pd.DataFrame:
    df = ak.fund_etf_hist_sina(symbol=sina_sym)
    df = df.rename(columns={"date": "dt"})
    df["dt"] = pd.to_datetime(df["dt"])
    for c in ("open", "high", "low", "close"):
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("dt").dropna(subset=["close"]).reset_index(drop=True)


def run_backtest(df: pd.DataFrame, label: str) -> tuple[pd.DataFrame, dict, dict]:
    work = df.rename(columns={"dt": "date"})
    sig = donchian(work["close"], 440, 160)
    res, m = backtest(work, sig, STRAT)
    _, m_bh = backtest(work, pd.Series(1, index=work.index), "买入持有")
    d = res.copy()
    d["pnl_pct"] = (d["equity"] / INIT_CASH - 1) * 100
    chg = d["signal"].diff()
    d["trade"] = ""
    d.loc[chg == 1, "trade"] = "buy"
    d.loc[chg == -1, "trade"] = "sell"
    m["标签"] = label
    m_bh["标签"] = label + "/持有"
    return d, m, m_bh


def plot_pnl(d: pd.DataFrame, m: dict, title: str, path: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(14, 8), sharex=True)
    ax1.plot(d["date"], d["close"], lw=0.8, color="#333")
    for side, mk, c in (("buy", "^", "#e74c3c"), ("sell", "v", "#2ecc71")):
        sub = d[d["trade"] == side]
        ax1.scatter(sub["date"], sub["close"], marker=mk, c=c, s=45, label=side)
    ax1.set_title(title)
    ax1.legend(fontsize=8)
    ax1.grid(True, alpha=0.3)
    bh = (1 + d["ret_mkt"].fillna(0)).cumprod()
    ax2.plot(d["date"], d["pnl_pct"], label="策略%")
    ax2.plot(d["date"], (bh - 1) * 100, ls="--", color="#999", label="持有%")
    ax2.set_title(f"收益{m['total_return']:.1f}% Sharpe{m['sharpe']:.2f} 回撤{m['max_drawdown']:.1f}%")
    ax2.legend(fontsize=8)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.tight_layout()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close()


def main() -> None:
    code = sys.argv[1] if len(sys.argv) > 1 else "513050"
    sina_sym = f"sh{code}" if not code.startswith(("sh", "sz")) else code
    out = BASE / f"{code}_sina_30m"
    out.mkdir(parents=True, exist_ok=True)

    raw30 = fetch_sina_30m(sina_sym)
    raw30.to_csv(out / f"{code}_30m_raw.csv", index=False, encoding="utf-8-sig")

    d30, m30, bh30 = run_backtest(raw30, "新浪30分钟")
    tr30 = d30[d30["trade"] != ""][["date", "trade", "close", "equity", "pnl_pct"]]
    tr30.to_csv(out / f"{code}_30m_trades.csv", index=False, encoding="utf-8-sig")
    plot_pnl(d30, m30, f"{code} {STRAT} 新浪30m", out / f"{code}_30m_pnl.png")

    # 日线对照（历史更长）
    raw_d = fetch_sina_daily(sina_sym)
    raw_d = raw_d[raw_d["dt"] >= raw30["dt"].iloc[0]]
    d_d, m_d, bh_d = run_backtest(raw_d, "新浪日线(同起点)")
    tr_d = d_d[d_d["trade"] != ""][["date", "trade", "close", "equity", "pnl_pct"]]

    summary = pd.DataFrame([m30, bh30, m_d, bh_d])
    summary.to_csv(out / f"{code}_summary.csv", index=False, encoding="utf-8-sig")

    print(f"=== {code} ({sina_sym}) 唐奇安 55/20 日等价440/160 ===\n")
    print(f"【30分钟】 {raw30['dt'].iloc[0]} ~ {raw30['dt'].iloc[-1]} | {len(raw30)} 根")
    print(f"  策略: 收益{m30['total_return']:.2f}% Sharpe{m30['sharpe']:.2f} 回撤{m30['max_drawdown']:.2f}% "
          f"买卖{int((d30['trade']=='buy').sum())}/{int((d30['trade']=='sell').sum())}")
    print(f"  持有: 收益{bh30['total_return']:.2f}%")
    print(f"【日线同区间】 {len(raw_d)} 根")
    print(f"  策略: 收益{m_d['total_return']:.2f}% Sharpe{m_d['sharpe']:.2f} 回撤{m_d['max_drawdown']:.2f}%")
    print(f"  持有: 收益{bh_d['total_return']:.2f}%")
    if not tr30.empty:
        print("\n30m 买卖点:")
        print(tr30.to_string(index=False))
    print(f"\n数据: {out / f'{code}_30m_raw.csv'}")
    print(f"成交: {out / f'{code}_30m_trades.csv'}")
    print(f"图表: {out / f'{code}_30m_pnl.png'}")
    print(f"汇总: {out / f'{code}_summary.csv'}")


if __name__ == "__main__":
    main()
