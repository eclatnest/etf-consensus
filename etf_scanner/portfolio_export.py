# -*- coding: utf-8 -*-
"""组合回测导出：持仓可读格式 + 分 ETF PnL"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from backtest_kc50 import backtest, metrics
from etf_scanner.consensus_backtest import _market_risk_on, _should_exit_row
from etf_scanner.data import sina_symbol
from etf_scanner.daily_signals import load_daily_tail
from etf_scanner.portfolio_rules import PortfolioRules


def zcode(code: str) -> str:
    return str(code).strip().zfill(6)


def format_holdings_row(
    weights: dict[str, float],
    names: dict[str, str] | None = None,
    buy_codes: set[str] | None = None,
    sell_codes: set[str] | None = None,
) -> dict[str, str]:
    names = names or {}
    buy_codes = buy_codes or set()
    sell_codes = sell_codes or set()
    if not weights:
        return {"holdings_codes": "", "holdings_weights": "", "holdings_display": ""}
    codes = sorted(weights.keys(), key=lambda c: zcode(c))
    parts = []
    for c in codes:
        zc = zcode(c)
        nm = names.get(c, names.get(zc, ""))
        tag = ""
        if zc in buy_codes:
            tag = "[买]"
        elif zc in sell_codes:
            tag = "[卖]"
        else:
            tag = "[持]"
        label = f"{zc}{tag}"
        if nm:
            label += f" {nm}"
        parts.append(f"{label} {weights[c]:.1%}")
    return {
        "holdings_codes": "|".join(zcode(c) for c in codes),
        "holdings_weights": "|".join(f"{weights[c]:.4f}" for c in codes),
        "holdings_display": "; ".join(parts),
    }


def enrich_pnl_daily(pnl: pd.DataFrame, daily_weights: list[dict[str, float]], names: dict[str, str]) -> pd.DataFrame:
    rows = []
    for i, row in pnl.iterrows():
        w = daily_weights[i] if i < len(daily_weights) else {}
        buy_s = set(str(x) for x in str(row.get("buy_codes", "")).split("|") if x)
        sell_s = set(str(x) for x in str(row.get("sell_codes", "")).split("|") if x)
        extra = format_holdings_row(w, names, buy_s, sell_s)
        r = row.to_dict()
        r.pop("holdings", None)
        rows.append({**r, **extra})
    return pd.DataFrame(rows)


def _consensus_next_action(consensus: str) -> str:
    """收盘共识标签 -> 次日开盘应执行的操作。"""
    c = str(consensus or "").strip()
    if c in ("买入", "卖出", "持有", "观望", "空仓"):
        return c
    return "观望"


def _portfolio_next_action(
    sig: pd.Series | None,
    rules: PortfolioRules,
    risk_on: bool,
    is_held: bool,
) -> str:
    """组合规则下，收盘后对该标的的次日操作建议。"""
    if not is_held:
        if not risk_on and rules.regime_mode in ("no_buy", "force_cash"):
            return "不可买"
        if sig is None or (isinstance(sig, pd.Series) and sig.empty):
            return "观望"
        vote = int(sig.get("vote_hold", 0))
        mom = float(sig.get("mom120_pct") or -999)
        name = str(sig.get("name", ""))
        skip_kw = ("货币", "快线", "快钱", "日利", "添益", "理财")
        if any(k in name for k in skip_kw):
            return "过滤"
        if rules.entry_mode == "fill_vote3" and vote < 3:
            return "观望"
        if rules.min_mom120_pct > 0 and mom < rules.min_mom120_pct:
            return "观望"
        if rules.entry_mode == "buy_only" and str(sig.get("consensus", "")) != "买入":
            return "观望"
        return "可买入"
    if rules.regime_mode == "force_cash" and not risk_on:
        return "卖出"
    if sig is not None and not (isinstance(sig, pd.Series) and sig.empty):
        if _should_exit_row(sig, rules):
            return "卖出"
    return "持有"


def enrich_pnl_by_etf_next_action(
    all_etf: pd.DataFrame,
    detail: pd.DataFrame,
    rules: PortfolioRules,
    bench_regime: pd.DataFrame,
) -> pd.DataFrame:
    """为分 ETF 日度表增加次日操作建议（基于当日收盘信号）。"""
    if all_etf.empty:
        return all_etf
    out = all_etf.copy()
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["date"] = pd.to_datetime(out["date"]).dt.normalize()

    d = detail.copy()
    d["code"] = d["code"].astype(str).str.zfill(6)
    d["date"] = pd.to_datetime(d["date"]).dt.normalize()
    sig_idx = d.set_index(["date", "code"])

    cal = pd.DatetimeIndex(sorted(out["date"].unique()))
    next_date_map = {cal[i]: cal[i + 1] for i in range(len(cal) - 1)}

    consensus_list: list[str] = []
    vote_list: list[int] = []
    mom_list: list[float | None] = []
    risk_list: list[str] = []
    eligible_list: list[str] = []
    consensus_next: list[str] = []
    portfolio_next: list[str] = []
    next_dates: list[object] = []

    for _, row in out.iterrows():
        dt = row["date"]
        code = row["code"]
        held = float(row.get("weight", 0) or 0) > 1e-6
        key = (dt, code)
        sig = sig_idx.loc[key] if key in sig_idx.index else None
        if sig is not None and isinstance(sig, pd.DataFrame):
            sig = sig.iloc[0]

        bench_row = (
            bench_regime.loc[dt]
            if bench_regime is not None
            and not bench_regime.empty
            and dt in bench_regime.index
            else None
        )
        risk_on = _market_risk_on(bench_row, rules)

        if sig is not None and not (isinstance(sig, pd.Series) and sig.empty):
            cons = str(sig.get("consensus", ""))
            vote = int(sig.get("vote_hold", 0))
            mom_v = sig.get("mom120_pct")
            mom = round(float(mom_v), 2) if pd.notna(mom_v) else None
        else:
            cons, vote, mom = "", 0, None

        pn = _portfolio_next_action(sig, rules, risk_on, held)
        cn = _consensus_next_action(cons)

        consensus_list.append(cons)
        vote_list.append(vote)
        mom_list.append(mom)
        risk_list.append("是" if risk_on else "否")
        eligible_list.append("是" if pn == "可买入" else ("持仓中" if held else "否"))
        consensus_next.append(cn)
        portfolio_next.append(pn)
        next_dates.append(next_date_map.get(dt, pd.NaT))

    out["next_date"] = next_dates
    out["signal_consensus"] = consensus_list
    out["vote_hold"] = vote_list
    out["mom120_pct"] = mom_list
    out["market_ma200_ok"] = risk_list
    out["eligible_entry"] = eligible_list
    out["consensus_next_action"] = consensus_next
    out["portfolio_next_action"] = portfolio_next
    # 主列：已持仓用组合卖出/持有；未持仓用共识或「可买入」
    out["next_day_action"] = out.apply(
        lambda r: r["portfolio_next_action"]
        if float(r.get("weight", 0) or 0) > 1e-6
        else (
            r["consensus_next_action"]
            if r["portfolio_next_action"] in ("观望", "过滤", "不可买")
            else r["portfolio_next_action"]
        ),
        axis=1,
    )
    return out


def mark_etf_actions(all_etf: pd.DataFrame, trades: pd.DataFrame) -> pd.DataFrame:
    if all_etf.empty:
        return all_etf
    out = all_etf.copy()
    out["code"] = out["code"].astype(str).str.zfill(6)
    out["date"] = pd.to_datetime(out["date"])
    out["day_action"] = "持有"
    if trades is not None and not trades.empty:
        t = trades.copy()
        t["code"] = t["code"].astype(str).str.zfill(6)
        t["date"] = pd.to_datetime(t["date"])
        for _, tr in t.iterrows():
            m = (out["date"] == tr["date"]) & (out["code"] == tr["code"])
            out.loc[m, "day_action"] = str(tr["side"])
    return out


def build_per_etf_pnl(
    etf_records: dict[str, list[dict]],
    trades: pd.DataFrame,
    init_cash: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """汇总每只持仓过 ETF 的日度贡献与全周期指标。"""
    all_rows: list[dict] = []
    summary_rows: list[dict] = []

    for code, recs in sorted(etf_records.items()):
        if not recs:
            continue
        df = pd.DataFrame(recs).sort_values("date")
        all_rows.extend(df.to_dict("records"))
        total_contrib = float(df["contrib_usd"].sum())
        days = len(df)
        name = df["name"].iloc[0] if "name" in df.columns else ""
        total_ret = (1 + df["etf_ret"]).prod() - 1 if "etf_ret" in df.columns else 0.0
        summary_rows.append(
            {
                "code": zcode(code),
                "name": name,
                "hold_days": days,
                "contrib_usd": round(total_contrib, 2),
                "contrib_pct_of_init": round(total_contrib / init_cash * 100, 2),
                "etf_total_return_pct": round(float(total_ret) * 100, 2),
                "avg_weight": round(float(df["weight"].mean()), 4),
            }
        )

    all_df = pd.DataFrame(all_rows)
    sum_df = pd.DataFrame(summary_rows).sort_values("contrib_usd", ascending=False)
    return all_df, sum_df


def backtest_single_etf_in_portfolio(
    code: str,
    name: str,
    start: pd.Timestamp,
    end: pd.Timestamp,
    trades: pd.DataFrame,
    cost: float = 0.0005,
    init_cash: float = 10_000.0,
) -> pd.DataFrame | None:
    """该 ETF 在组合持仓区间内的独立仓位回测（10万基准下按组合权重缩放）。"""
    sina = sina_symbol(code)
    df = load_daily_tail(sina, tail=400)
    if df is None:
        return None
    df = df[(df["date"] >= start) & (df["date"] <= end)].copy()
    if len(df) < 5:
        return None

    t = trades[trades["code"].astype(str).str.zfill(6) == zcode(code)].sort_values("date")
    if t.empty:
        return None

    sig = pd.Series(0, index=df.index, dtype=int)
    in_pos = False
    trade_dates = set(pd.to_datetime(t["date"]).dt.normalize())
    for i, dt in enumerate(df["date"]):
        d = pd.Timestamp(dt).normalize()
        if d in trade_dates:
            acts = t[t["date"].dt.normalize() == d]
            for _, a in acts.iterrows():
                if a["side"] == "买入":
                    in_pos = True
                elif a["side"] == "卖出":
                    in_pos = False
        sig.iloc[i] = 1 if in_pos else 0

    df_bt = df[["date", "close"]].copy()
    for c in ("open", "high", "low"):
        df_bt[c] = df_bt["close"]
    res, m = backtest(df_bt, sig, zcode(code))
    res["code"] = zcode(code)
    res["name"] = name
    res["strategy_return_pct"] = m["total_return"]
    return res[["date", "code", "name", "close", "signal", "equity", "strat_ret"]].rename(
        columns={"equity": "equity_10k", "strat_ret": "daily_ret"}
    )


def write_portfolio_exports(
    out_dir: Path,
    pnl: pd.DataFrame,
    trades: pd.DataFrame,
    etf_records: dict[str, list[dict]],
    daily_weights: list[dict[str, float]],
    names: dict[str, str],
    init_cash: float,
    start: pd.Timestamp,
    end: pd.Timestamp,
    cost: float,
    detail: pd.DataFrame | None = None,
    rules: PortfolioRules | None = None,
    bench_regime: pd.DataFrame | None = None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pnl_out = enrich_pnl_daily(pnl, daily_weights, names)
    pnl_out.to_csv(out_dir / "pnl_daily.csv", index=False, encoding="utf-8-sig")

    all_etf, sum_etf = build_per_etf_pnl(etf_records, trades, init_cash)
    if not all_etf.empty:
        all_etf = mark_etf_actions(all_etf, trades)
        if detail is not None and rules is not None:
            br = bench_regime if bench_regime is not None else pd.DataFrame()
            all_etf = enrich_pnl_by_etf_next_action(all_etf, detail, rules, br)
        all_etf.to_csv(out_dir / "pnl_by_etf_all.csv", index=False, encoding="utf-8-sig")
    if not sum_etf.empty:
        sum_etf.to_csv(out_dir / "pnl_by_etf_summary.csv", index=False, encoding="utf-8-sig")

    etf_dir = out_dir / "pnl_by_etf"
    etf_dir.mkdir(exist_ok=True)
    for code in sorted(etf_records.keys(), key=zcode):
        recs = etf_records[code]
        if not recs:
            continue
        df = pd.DataFrame(recs).sort_values("date")
        df = mark_etf_actions(df, trades[trades["code"].astype(str).str.zfill(6) == zcode(code)])
        if detail is not None and rules is not None:
            br = bench_regime if bench_regime is not None else pd.DataFrame()
            df = enrich_pnl_by_etf_next_action(df, detail, rules, br)
        name = df["name"].iloc[0] if "name" in df.columns else code
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in name)[:20]
        df.to_csv(etf_dir / f"{zcode(code)}_{safe}.csv", index=False, encoding="utf-8-sig")

        solo = backtest_single_etf_in_portfolio(code, name, start, end, trades, cost, 10_000.0)
        if solo is not None:
            solo.to_csv(etf_dir / f"{zcode(code)}_{safe}_solo.csv", index=False, encoding="utf-8-sig")
