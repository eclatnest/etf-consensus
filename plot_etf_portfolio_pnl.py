#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""ETF 组合回测 PnL 图：净值 / 盈亏 / 回撤 / 持仓数"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from etf_scanner.daily_signals import load_daily_tail
from etf_scanner.data import sina_symbol

ROOT = Path(__file__).resolve().parent


def find_latest_backtest_dir(base: Path) -> Path:
    dirs = sorted(base.glob("backtest_10pos_5y_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dirs:
        dirs = sorted(base.glob("backtest_10pos_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not dirs:
        raise FileNotFoundError(f"未找到回测目录: {base}")
    return dirs[0]


def load_benchmark_equity(start: pd.Timestamp, end: pd.Timestamp, init_cash: float) -> pd.DataFrame:
    df = load_daily_tail(sina_symbol("510300"), tail=4000)
    if df is None or df.empty:
        return pd.DataFrame()
    df = df[(df["date"] >= start) & (df["date"] <= end)].copy()
    df["bench_ret"] = df["close"].pct_change().fillna(0)
    df["bench_equity"] = init_cash * (1 + df["bench_ret"]).cumprod()
    return df[["date", "bench_equity", "close"]]


def plot_pnl(pnl: pd.DataFrame, bench: pd.DataFrame, summary: dict, out_png: Path) -> None:
    plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
    plt.rcParams["axes.unicode_minus"] = False

    pnl = pnl.copy()
    pnl["date"] = pd.to_datetime(pnl["date"])
    init = float(summary.get("init_cash", 100_000))
    pnl["pnl_yuan"] = pnl["equity"] - init
    pnl["pnl_pct"] = (pnl["equity"] / init - 1) * 100
    peak = pnl["equity"].cummax()
    pnl["drawdown_pct"] = (pnl["equity"] / peak - 1) * 100

    if not bench.empty:
        bench = bench.copy()
        bench["date"] = pd.to_datetime(bench["date"])
        m = pnl[["date", "equity"]].merge(bench[["date", "bench_equity"]], on="date", how="left")
        m["bench_equity"] = m["bench_equity"].ffill()
        pnl = pnl.merge(m[["date", "bench_equity"]], on="date", how="left")
        pnl["bench_pct"] = (pnl["bench_equity"] / init - 1) * 100
    else:
        pnl["bench_pct"] = np.nan

    title_rule = str(summary.get("rules", ""))[:60]
    ann = summary.get("annual_return", "")
    tot = summary.get("total_return", "")
    dd = summary.get("max_drawdown", "")
    sh = summary.get("sharpe", "")

    fig, axes = plt.subplots(3, 1, figsize=(14, 10), sharex=True, gridspec_kw={"height_ratios": [2, 1.2, 0.8]})

    ax0 = axes[0]
    ax0.plot(pnl["date"], pnl["equity"], color="#c0392b", lw=1.5, label=f"组合净值 {pnl['equity'].iloc[-1]:,.0f}")
    if pnl["bench_equity"].notna().any():
        ax0.plot(
            pnl["date"],
            pnl["bench_equity"],
            ls="--",
            color="#7f8c8d",
            lw=1.0,
            label=f"沪深300买入持有 {pnl['bench_equity'].iloc[-1]:,.0f}",
        )
    ax0.axhline(init, color="#999", ls=":", lw=0.6)
    ax0.set_ylabel("权益 (元)")
    ax0.set_title(
        f"ETF 共识组合 PnL | {summary.get('start', '')} ~ {summary.get('end', '')}\n"
        f"年化 {ann}% | 总收益 {tot}% | 回撤 {dd}% | Sharpe {sh}\n{title_rule}",
        fontsize=11,
    )
    ax0.legend(loc="upper left", fontsize=9)
    ax0.grid(True, alpha=0.3)

    ax1 = axes[1]
    ax1.fill_between(
        pnl["date"],
        0,
        pnl["pnl_yuan"],
        where=pnl["pnl_yuan"] >= 0,
        alpha=0.25,
        color="#e74c3c",
    )
    ax1.fill_between(
        pnl["date"],
        0,
        pnl["pnl_yuan"],
        where=pnl["pnl_yuan"] < 0,
        alpha=0.25,
        color="#2ecc71",
    )
    ax1.plot(
        pnl["date"],
        pnl["pnl_yuan"],
        color="#c0392b",
        lw=1.2,
        label=f"策略盈亏 {pnl['pnl_yuan'].iloc[-1]:+,.0f} 元",
    )
    if pnl["bench_pct"].notna().any():
        bench_yuan = init * pnl["bench_pct"] / 100
        ax1.plot(pnl["date"], bench_yuan, ls="--", color="#7f8c8d", lw=1.0, label="沪深300盈亏")
    ax1.axhline(0, color="#999", lw=0.5)
    ax1.set_ylabel("盈亏 (元)")
    ax1.legend(loc="upper left", fontsize=8)
    ax1.grid(True, alpha=0.3)

    ax2 = axes[2]
    ax2.fill_between(pnl["date"], pnl["drawdown_pct"], 0, color="#3498db", alpha=0.35)
    ax2.plot(pnl["date"], pnl["drawdown_pct"], color="#2980b9", lw=0.9)
    if "n_held" in pnl.columns:
        ax2b = ax2.twinx()
        ax2b.bar(pnl["date"], pnl["n_held"], width=1.5, alpha=0.15, color="#f39c12", label="持仓数")
        ax2b.set_ylabel("持仓只数", fontsize=8)
        ax2b.set_ylim(0, max(12, pnl["n_held"].max() + 1))
    ax2.set_ylabel("回撤 (%)")
    ax2.set_xlabel("日期")
    ax2.grid(True, alpha=0.3)

    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=6))
    fig.autofmt_xdate()
    fig.tight_layout()
    fig.savefig(out_png, dpi=150, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="", help="回测输出目录，默认取 etf_daily 下最新 5y")
    args = ap.parse_args()

    if args.dir:
        bt_dir = Path(args.dir)
    else:
        bt_dir = find_latest_backtest_dir(ROOT / "mx_data_output" / "etf_daily")

    pnl_path = bt_dir / "pnl_daily.csv"
    sum_path = bt_dir / "portfolio_summary.csv"
    if not pnl_path.is_file():
        raise FileNotFoundError(pnl_path)

    pnl = pd.read_csv(pnl_path)
    summary = pd.read_csv(sum_path).iloc[0].to_dict() if sum_path.is_file() else {}
    start = pd.Timestamp(summary.get("start", pnl["date"].iloc[0]))
    end = pd.Timestamp(summary.get("end", pnl["date"].iloc[-1]))
    init = float(summary.get("init_cash", 100_000))

    bench = load_benchmark_equity(start, end, init)
    out_png = bt_dir / "pnl_chart.png"
    plot_pnl(pnl, bench, summary, out_png)

    # 收益率对比图
    pnl2 = pnl.copy()
    pnl2["date"] = pd.to_datetime(pnl2["date"])
    pnl2["ret_pct"] = (pnl2["equity"] / init - 1) * 100
    if not bench.empty:
        b = bench.copy()
        b["date"] = pd.to_datetime(b["date"])
        b["ret_pct"] = (b["bench_equity"] / init - 1) * 100
        fig, ax = plt.subplots(figsize=(14, 5))
        plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei", "DejaVu Sans"]
        plt.rcParams["axes.unicode_minus"] = False
        ax.plot(pnl2["date"], pnl2["ret_pct"], color="#c0392b", lw=1.5, label="组合累计收益%")
        ax.plot(b["date"], b["ret_pct"], ls="--", color="#7f8c8d", lw=1.0, label="沪深300累计收益%")
        ax.axhline(0, color="#999", lw=0.5)
        ax.set_ylabel("累计收益率 (%)")
        ax.set_title("累计收益率对比")
        ax.legend()
        ax.grid(True, alpha=0.3)
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
        fig.autofmt_xdate()
        fig.tight_layout()
        ret_png = bt_dir / "pnl_return_pct.png"
        fig.savefig(ret_png, dpi=150, bbox_inches="tight")
        plt.close(fig)
        print(f"  {ret_png}")

    print(f"回测目录: {bt_dir.resolve()}")
    print(f"  {out_png}")


if __name__ == "__main__":
    main()
