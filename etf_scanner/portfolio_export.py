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


_OPEN_FROM_CONSENSUS = {
    "买入": "开盘买入",
    "卖出": "开盘卖出",
    "持有": "开盘持有",
    "观望": "观望不动",
    "空仓": "空仓不动",
}


def _portfolio_signal_flag(
    sig: pd.Series | None,
    rules: PortfolioRules,
    risk_on: bool,
    is_held: bool,
) -> str:
    """内部：组合规则判断 卖出/持有/可买入/观望/不可买。"""
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


def resolve_next_open_action(
    *,
    held: bool,
    today_close_action: str,
    port_flag: str,
    risk_on: bool,
    consensus: str,
    vote: int,
    mom: float | None,
    next_date: pd.Timestamp | None,
) -> tuple[str, str]:
    """
    返回 (next_open_action, next_open_brief)。
    约定：收盘算信号 → 次日开盘执行（与回测一致）。
    """
    nd = ""
    if next_date is not None and pd.notna(next_date):
        nd = pd.Timestamp(next_date).strftime("%Y-%m-%d")

    tc = str(today_close_action or "持有").strip()
    cons = str(consensus or "").strip()

    # 今日收盘已下卖单
    if tc == "卖出":
        brief = f"{nd} 开盘卖出" if nd else "开盘卖出"
        return "开盘卖出", f"{brief}（今日收盘已发卖单，次日开盘清仓）"

    # 今日收盘买入 → 次日开盘起持仓
    if tc == "买入":
        if port_flag == "卖出":
            brief = f"{nd} 开盘卖出" if nd else "开盘卖出"
            return "开盘卖出", f"{brief}（今日新开仓，但组合规则要求次日卖出）"
        brief = f"{nd} 开盘持有" if nd else "开盘持有"
        return "开盘持有", f"{brief}（今日收盘买入，次日开盘起算持仓）"

    if not held:
        if port_flag == "不可买" or not risk_on:
            return "大盘弱·不开仓", f"{nd or '次日'} 不买入（沪深300未站上MA200）"
        if port_flag == "可买入":
            mom_s = f"动量{mom}%" if mom is not None else "动量—"
            return "开盘买入", f"{nd or '次日'} 开盘买入（三票{vote}+ {mom_s}，满足组合条件）"
        if port_flag == "过滤":
            return "观望不动", f"{nd or '次日'} 不操作（货币/理财类过滤）"
        open_a = _OPEN_FROM_CONSENSUS.get(cons, "观望不动")
        return open_a, f"{nd or '次日'} {open_a}（共识{cons}，vote={vote}，未在组合仓）"

    # 组合持仓中
    if port_flag == "卖出":
        return "开盘卖出", f"{nd or '次日'} 开盘卖出（vote={vote}，共识{cons}，组合出场）"
    open_a = _OPEN_FROM_CONSENSUS.get(cons, "开盘持有")
    if open_a in ("开盘卖出",):
        return "开盘卖出", f"{nd or '次日'} 开盘卖出（共识{cons}，vote={vote}）"
    return "开盘持有", f"{nd or '次日'} 开盘持有（共识{cons}，vote={vote}，继续持仓）"


def add_consensus_open_action_columns(df: pd.DataFrame) -> pd.DataFrame:
    """每日扫描 CSV：按单标的共识给出次日开盘操作。"""
    if df.empty:
        return df
    out = df.copy()
    out["next_open_action"] = out["consensus"].map(_OPEN_FROM_CONSENSUS).fillna("观望不动")
    out["next_open_brief"] = out.apply(
        lambda r: f"次日开盘：{_OPEN_FROM_CONSENSUS.get(str(r.get('consensus','')), '观望不动')}"
        f"（共识{ r.get('consensus','')}，vote={r.get('vote_hold',0)}）",
        axis=1,
    )
    return out


def _reorder_etf_pnl_columns(df: pd.DataFrame) -> pd.DataFrame:
    front = [
        "date",
        "next_date",
        "code",
        "name",
        "next_open_action",
        "next_open_brief",
        "today_close_action",
        "weight",
        "etf_ret",
        "etf_ret_pct",
        "contrib_usd",
        "cum_contrib_usd",
    ]
    rest = [c for c in df.columns if c not in front]
    cols = [c for c in front if c in df.columns] + rest
    return df[cols]


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

    open_actions: list[str] = []
    open_briefs: list[str] = []
    next_dates: list[object] = []
    consensus_list: list[str] = []
    vote_list: list[int] = []
    mom_list: list[float | None] = []
    risk_list: list[str] = []

    for _, row in out.iterrows():
        dt = row["date"]
        code = row["code"]
        held = float(row.get("weight", 0) or 0) > 1e-6
        today_close = str(row.get("day_action", row.get("today_close_action", "持有")))
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
        nd = next_date_map.get(dt, pd.NaT)

        if sig is not None and not (isinstance(sig, pd.Series) and sig.empty):
            cons = str(sig.get("consensus", ""))
            vote = int(sig.get("vote_hold", 0))
            mom_v = sig.get("mom120_pct")
            mom = round(float(mom_v), 2) if pd.notna(mom_v) else None
        else:
            cons, vote, mom = "", 0, None

        port_flag = _portfolio_signal_flag(sig, rules, risk_on, held)
        open_a, open_b = resolve_next_open_action(
            held=held,
            today_close_action=today_close,
            port_flag=port_flag,
            risk_on=risk_on,
            consensus=cons,
            vote=vote,
            mom=mom,
            next_date=nd,
        )

        open_actions.append(open_a)
        open_briefs.append(open_b)
        next_dates.append(nd)
        consensus_list.append(cons)
        vote_list.append(vote)
        mom_list.append(mom)
        risk_list.append("是" if risk_on else "否")

    out["next_date"] = next_dates
    out["next_open_action"] = open_actions
    out["next_open_brief"] = open_briefs
    if "day_action" in out.columns:
        out["today_close_action"] = out["day_action"]
        out = out.drop(columns=["day_action"])
    elif "today_close_action" not in out.columns:
        out["today_close_action"] = "持有"
    out["signal_consensus"] = consensus_list
    out["vote_hold"] = vote_list
    out["mom120_pct"] = mom_list
    out["market_ma200_ok"] = risk_list
    return _reorder_etf_pnl_columns(out)


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
    # 保留 day_action 供 enrich 读取，enrich 会改名为 today_close_action
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
