# -*- coding: utf-8 -*-
"""共识三策略：组合等权回测 + 单标的统计"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from backtest_kc50 import backtest, metrics
from etf_scanner.config import ScanConfig
from etf_scanner.daily_signals import (
    LOOKBACK_BARS,
    consensus_label,
    load_daily_tail,
    signal_action_at,
)
from etf_scanner.data import load_etf_universe_cached, sina_symbol
from etf_scanner.portfolio_rules import PortfolioRules
from etf_scanner.strategies import DEFAULT_STRATEGIES, PRACTICAL_IDS, StrategyDef


def consensus_position_signal(df: pd.DataFrame, strategies: list[StrategyDef] | None = None) -> pd.Series:
    """收盘信号：vote>=2 则次日持仓。返回 0/1，与 backtest_kc50.backtest 的 signal 列一致。"""
    strategies = strategies or [s for s in DEFAULT_STRATEGIES if s.id in PRACTICAL_IDS]
    votes = pd.Series(0, index=df.index, dtype=int)
    for sd in strategies:
        if sd.id not in PRACTICAL_IDS:
            continue
        votes += sd.build(df).shift(1).fillna(0).astype(int)
    return (votes >= 2).astype(int)


def count_edge_trades(sig: pd.Series) -> tuple[int, int, int]:
    """买入/卖出次数（边沿），及持仓切换总次数。"""
    pos = sig.shift(1).fillna(0).astype(int)
    chg = pos.diff().fillna(0)
    buys = int((chg == 1).sum())
    sells = int((chg == -1).sum())
    rounds = min(buys, sells)
    return buys, sells, rounds


def consensus_detail_for_df(
    df: pd.DataFrame,
    code: str,
    name: str,
    start: pd.Timestamp,
    strategies: list[StrategyDef],
) -> pd.DataFrame | None:
    if len(df) < 220:
        return None
    rows: list[dict] = []
    for idx in range(len(df)):
        if idx < 200:
            continue
        dt = df["date"].iloc[idx]
        if pd.Timestamp(dt) < start:
            continue
        row: dict = {
            "date": pd.Timestamp(dt),
            "code": code,
            "name": name,
            "close": float(df["close"].iloc[idx]),
            "ret": float(df["close"].pct_change().iloc[idx])
            if pd.notna(df["close"].pct_change().iloc[idx])
            else 0.0,
        }
        votes = 0
        for sd in strategies:
            if sd.id not in PRACTICAL_IDS:
                continue
            sig = sd.build(df)
            label, pos, _ = signal_action_at(sig, idx)
            row[f"{sd.id}_action"] = label
            if pos == 1:
                votes += 1
        row["vote_hold"] = votes
        row["consensus"] = consensus_label(row)
        mom = df["close"].pct_change(120).iloc[idx] * 100
        row["mom120_pct"] = round(float(mom), 2) if pd.notna(mom) else None
        rows.append(row)
    if not rows:
        return None
    return pd.DataFrame(rows)


def history_tail_bars(trade_days: int) -> int:
    """动量120预热 + 回测区间 + 缓冲"""
    return LOOKBACK_BARS + trade_days + 120


def load_etf_detail_row(
    code: str,
    name: str,
    start: pd.Timestamp,
    strategies: list[StrategyDef],
    tail_bars: int | None = None,
) -> tuple[str, str, pd.DataFrame | None]:
    sina = sina_symbol(code)
    df = load_daily_tail(sina, tail=tail_bars or (LOOKBACK_BARS + 30))
    if df is None:
        return code, name, None
    return code, name, consensus_detail_for_df(df, code, name, start, strategies)


def load_etf_panel_row(
    code: str,
    name: str,
    start: pd.Timestamp,
    strategies: list[StrategyDef],
) -> tuple[str, str, pd.DataFrame | None]:
    sina = sina_symbol(code)
    df = load_daily_tail(sina, tail=LOOKBACK_BARS + 30)
    if df is None:
        return code, name, None
    df = df[df["date"] >= start - pd.Timedelta(days=5)].copy()
    if len(df) < 220:
        return code, name, None
    sig = consensus_position_signal(df, strategies)
    out = pd.DataFrame(
        {
            "date": df["date"],
            "close": df["close"],
            "signal": sig,
            "ret": df["close"].pct_change(),
        }
    )
    out["code"] = code
    out["name"] = name
    return code, name, out


def build_panels(
    cfg: ScanConfig,
    start: pd.Timestamp,
    universe: pd.DataFrame | None = None,
    sequential: bool = False,
) -> tuple[pd.DataFrame, pd.DataFrame, list[dict]]:
    universe = universe if universe is not None else load_etf_universe_cached(cfg)
    strategies = [s for s in DEFAULT_STRATEGIES if s.id in PRACTICAL_IDS]
    rows: list[pd.DataFrame] = []
    per_etf: list[dict] = []
    total = len(universe)
    t0 = time.time()
    workers = 1 if sequential else min(cfg.workers, 6)

    def _one(r):
        return load_etf_panel_row(r.code, r.name, start, strategies)

    if sequential:
        done = 0
        for r in universe.itertuples():
            done += 1
            try:
                code, name, panel = _one(r)
                if panel is not None:
                    rows.append(panel)
            except Exception:
                pass
            if done % 100 == 0 or done == total:
                print(f"  加载 {done}/{total}  有效 {len(rows)}  {time.time()-t0:.0f}s")
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one, r): r for r in universe.itertuples()}
            done = 0
            for fut in as_completed(futs):
                done += 1
                try:
                    code, name, panel = fut.result()
                    if panel is not None:
                        rows.append(panel)
                except Exception:
                    pass
                if done % 100 == 0 or done == total:
                    print(f"  加载 {done}/{total}  有效 {len(rows)}  {time.time()-t0:.0f}s")

    if not rows:
        return pd.DataFrame(), pd.DataFrame(), []

    long = pd.concat(rows, ignore_index=True)
    long = long[long["date"] >= start].copy()

    pos_wide = long.pivot(index="date", columns="code", values="signal")
    ret_wide = long.pivot(index="date", columns="code", values="ret")
    close_wide = long.pivot(index="date", columns="code", values="close")

    # 单标的回测（近一年切片）
    for code in pos_wide.columns:
        sub = long[long["code"] == code].sort_values("date").reset_index(drop=True)
        if len(sub) < 60:
            continue
        sig = sub["signal"]
        df_bt = sub[["date", "close"]].copy()
        for c in ("open", "high", "low"):
            df_bt[c] = df_bt["close"]
        _d, m = backtest(df_bt, sig, "共识")
        buys, sells, rounds = count_edge_trades(sig)
        name = sub["name"].iloc[0]
        per_etf.append(
            {
                "code": code,
                "name": name,
                **m,
                "buy_trades": buys,
                "sell_trades": sells,
                "round_trips": rounds,
            }
        )

    return pos_wide, ret_wide, per_etf


def backtest_equal_weight_portfolio(
    pos_wide: pd.DataFrame,
    ret_wide: pd.DataFrame,
    cost: float,
    init_cash: float,
) -> tuple[pd.DataFrame, dict]:
    """每日等权持有 signal=1 的 ETF，收盘再平衡。"""
    dates = pos_wide.index.sort_values()
    equity = init_cash
    prev_w: dict[str, float] = {}
    records: list[dict] = []

    for dt in dates:
        sig_row = pos_wide.loc[dt]
        ret_row = ret_wide.loc[dt]
        held = sig_row[sig_row == 1].index.tolist()
        held = [c for c in held if c in ret_row.index and pd.notna(ret_row[c])]

        if not held:
            w = {}
            port_ret = 0.0
        else:
            w = {c: 1.0 / len(held) for c in held}
            port_ret = float(np.nanmean([ret_row[c] for c in held]))

        turnover = 0.0
        all_codes = set(prev_w) | set(w)
        for c in all_codes:
            turnover += abs(w.get(c, 0.0) - prev_w.get(c, 0.0))
        trade_cost = turnover * cost

        strat_ret = port_ret - trade_cost
        equity *= 1.0 + strat_ret
        records.append(
            {
                "date": dt,
                "n_held": len(held),
                "port_ret": strat_ret,
                "equity": equity,
                "turnover": turnover,
                "buy_signals": int((sig_row == 1).sum()),
            }
        )
        prev_w = w

    pnl = pd.DataFrame(records)
    m = metrics(pnl["equity"], pnl["port_ret"], pnl["date"])
    m["avg_held"] = round(pnl["n_held"].mean(), 1)
    m["max_held"] = int(pnl["n_held"].max())
    m["total_turnover"] = round(pnl["turnover"].sum(), 2)
    return pnl, m


def build_signal_detail(
    cfg: ScanConfig,
    start: pd.Timestamp,
    universe: pd.DataFrame | None = None,
    sequential: bool = False,
    trade_days: int = 252,
) -> pd.DataFrame:
    universe = universe if universe is not None else load_etf_universe_cached(cfg)
    strategies = [s for s in DEFAULT_STRATEGIES if s.id in PRACTICAL_IDS]
    tail_bars = history_tail_bars(trade_days)
    rows: list[pd.DataFrame] = []
    total = len(universe)
    t0 = time.time()
    workers = 1 if sequential else min(cfg.workers, 6)

    def _one(r):
        return load_etf_detail_row(r.code, r.name, start, strategies, tail_bars=tail_bars)

    if sequential:
        done = 0
        for r in universe.itertuples():
            done += 1
            try:
                _c, _n, panel = _one(r)
                if panel is not None:
                    rows.append(panel)
            except Exception:
                pass
            if done % 100 == 0 or done == total:
                print(f"  加载 {done}/{total}  有效 {len(rows)}  {time.time()-t0:.0f}s")
    else:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(_one, r): r for r in universe.itertuples()}
            done = 0
            for fut in as_completed(futs):
                done += 1
                try:
                    _c, _n, panel = fut.result()
                    if panel is not None:
                        rows.append(panel)
                except Exception:
                    pass
                if done % 100 == 0 or done == total:
                    print(f"  加载 {done}/{total}  有效 {len(rows)}  {time.time()-t0:.0f}s")

    if not rows:
        return pd.DataFrame()
    return pd.concat(rows, ignore_index=True)


def _active_weights(weights: dict[str, float], eps: float = 1e-6) -> dict[str, float]:
    return {c: w for c, w in weights.items() if w > eps}


def _should_exit_row(row: pd.Series, rules: PortfolioRules) -> bool:
    if rules.exit_mode == "sell_only":
        return str(row.get("consensus", "")) == "卖出"
    if rules.exit_mode == "vote_lt2":
        return str(row.get("consensus", "")) == "卖出" or int(row.get("vote_hold", 0)) < 2
    if rules.exit_mode == "vote_lt3":
        return str(row.get("consensus", "")) == "卖出" or int(row.get("vote_hold", 0)) < 3
    return str(row.get("consensus", "")) == "卖出"


def load_benchmark_regime(tail_bars: int) -> pd.DataFrame:
    """510300 大盘择时指标（按 date 索引）。"""
    from backtest_kc50 import sma

    df = load_daily_tail(sina_symbol("510300"), tail=tail_bars)
    if df is None or df.empty:
        return pd.DataFrame()
    out = df.copy()
    out["ma60"] = sma(out["close"], 60)
    out["ma200"] = sma(out["close"], 200)
    out["mom120_pct"] = out["close"].pct_change(120) * 100
    return out.set_index("date")


def _market_risk_on(row: pd.Series | None, rules: PortfolioRules) -> bool:
    if rules.market_filter == "none" or row is None or (isinstance(row, pd.Series) and row.empty):
        return True
    close = float(row["close"])
    if rules.market_filter == "ma60":
        ma = row.get("ma60")
        return pd.notna(ma) and close > float(ma)
    if rules.market_filter == "ma200":
        ma = row.get("ma200")
        return pd.notna(ma) and close > float(ma)
    if rules.market_filter == "mom120_pos":
        mom = row.get("mom120_pct")
        return pd.notna(mom) and float(mom) > 0
    return True


def _entry_candidates(
    day: pd.DataFrame,
    held: set[str],
    rules: PortfolioRules,
    skip_name_kw: tuple[str, ...],
) -> pd.DataFrame:
    cands = day[~day["code"].isin(held)].copy()
    cands = cands[~cands["name"].str.contains("|".join(skip_name_kw), na=False)]
    if rules.entry_mode == "buy_only":
        cands = cands[cands["consensus"] == "买入"]
    elif rules.entry_mode == "fill_vote3":
        cands = cands[cands["vote_hold"] >= 3]
    elif rules.entry_mode == "fill_vote2":
        cands = cands[cands["vote_hold"] >= max(rules.min_vote_entry, 2)]
    elif rules.entry_mode == "fill_vote2_mom5":
        cands = cands[
            (cands["vote_hold"] >= 2)
            & (cands["mom120_pct"].fillna(-999) >= rules.min_mom120_pct)
        ]
    else:
        cands = cands[cands["consensus"] == "买入"]
    if rules.min_mom120_pct > 0 and rules.entry_mode in (
        "fill_vote2",
        "fill_vote3",
        "fill_vote2_mom5",
    ):
        cands = cands[cands["mom120_pct"].fillna(-999) >= rules.min_mom120_pct]
    if "mom120_pct" not in cands.columns:
        cands["mom120_pct"] = 0.0
    return cands.sort_values(["mom120_pct", "vote_hold", "code"], ascending=[False, False, True])


def backtest_portfolio_buy_sell_max_n(
    detail: pd.DataFrame,
    ret_wide: pd.DataFrame,
    max_positions: int = 10,
    cost: float = 0.0005,
    init_cash: float = 100_000.0,
    calendar_dates: pd.DatetimeIndex | None = None,
    rules: PortfolioRules | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict, list[dict[str, float]], dict[str, list[dict]]]:
    """
    组合回测：收盘调仓，次日收益用调仓前权重。
    rules 控制买入/卖出条件（见 portfolio_rules.py）。
    """
    from etf_scanner.portfolio_rules import BASELINE, PortfolioRules

    rules = rules or BASELINE
    max_positions = rules.max_positions or max_positions
    dates = (
        calendar_dates.sort_values()
        if calendar_dates is not None
        else pd.DatetimeIndex(sorted(detail["date"].unique()))
    )
    code_names: dict[str, str] = (
        detail.drop_duplicates("code").set_index("code")["name"].astype(str).to_dict()
        if not detail.empty
        else {}
    )
    weights: dict[str, float] = {}
    skip_name_kw = ("货币", "快线", "快钱", "日利", "添益", "理财")
    equity = init_cash
    pnl_rows: list[dict] = []
    trade_rows: list[dict] = []
    daily_weights: list[dict[str, float]] = []
    etf_records: dict[str, list[dict]] = {}
    n_buy = 0
    n_sell = 0
    daily_buys: list[list[str]] = []
    daily_sells: list[list[str]] = []
    bench_regime = (
        load_benchmark_regime(history_tail_bars(len(dates)))
        if rules.market_filter != "none" or rules.regime_mode != "none"
        else pd.DataFrame()
    )
    detail_dates = pd.to_datetime(detail["date"]).dt.normalize()
    _empty_day = pd.DataFrame(columns=detail.columns)
    day_map: dict[pd.Timestamp, pd.DataFrame] = {
        pd.Timestamp(k): v.reset_index(drop=True)
        for k, v in detail.groupby(detail_dates, sort=False)
    }

    def _day_slice(day_df: pd.DataFrame, code: str) -> pd.DataFrame:
        if day_df.empty or "code" not in day_df.columns:
            return _empty_day
        zc = str(code).zfill(6)
        return day_df[day_df["code"].astype(str).str.zfill(6) == zc]

    for dt in dates:
        weights = _active_weights(weights)
        ret_row = ret_wide.loc[dt] if dt in ret_wide.index else pd.Series(dtype=float)
        equity_before = equity
        port_ret = 0.0
        for code, w in weights.items():
            ri = ret_row.get(code, np.nan)
            if pd.notna(ri):
                ri = float(ri)
                port_ret += w * ri
                contrib = equity_before * w * ri
                etf_records.setdefault(code, []).append(
                    {
                        "date": dt,
                        "code": str(code).zfill(6),
                        "name": code_names.get(code, ""),
                        "weight": round(w, 4),
                        "etf_ret": round(ri, 6),
                        "etf_ret_pct": round(ri * 100, 4),
                        "contrib_usd": round(contrib, 2),
                    }
                )

        equity *= 1.0 + port_ret
        trade_cost = 0.0
        day = day_map.get(pd.Timestamp(dt).normalize(), _empty_day)
        sold_today: list[str] = []
        bought_today: list[str] = []

        bench_row = bench_regime.loc[dt] if not bench_regime.empty and dt in bench_regime.index else None
        risk_on = _market_risk_on(bench_row, rules)
        day_max_pos = max_positions
        if not risk_on and rules.weak_max_positions is not None:
            day_max_pos = min(max_positions, rules.weak_max_positions)

        def _force_sell(code: str, w: float, reason: str = "") -> None:
            nonlocal trade_cost, n_sell, equity
            weights.pop(code, None)
            trade_cost += w * cost
            n_sell += 1
            zc = str(code).zfill(6)
            sold_today.append(zc)
            sub = _day_slice(day, code)
            trade_rows.append(
                {
                    "date": dt,
                    "code": zc,
                    "name": sub.iloc[0]["name"] if not sub.empty else "",
                    "side": "卖出",
                    "weight": round(w, 4),
                    "consensus": sub.iloc[0]["consensus"] if not sub.empty else reason,
                    "vote_hold": int(sub.iloc[0]["vote_hold"]) if not sub.empty else 0,
                    "equity": round(equity, 2),
                }
            )

        if rules.regime_mode == "force_cash" and not risk_on:
            for code in list(weights.keys()):
                _force_sell(code, weights[code], "弱市清仓")
        else:
            for code in list(weights.keys()):
                sub = _day_slice(day, code)
                if sub.empty:
                    continue
                if _should_exit_row(sub.iloc[0], rules):
                    _force_sell(code, weights[code])

        weights = _active_weights(weights)
        if len(weights) > day_max_pos:
            trim = sorted(weights.items(), key=lambda x: x[0])[: len(weights) - day_max_pos]
            for code, w in trim:
                _force_sell(code, w)

        weights = _active_weights(weights)
        slots = day_max_pos - len(weights)
        allow_buy = True
        if rules.regime_mode in ("no_buy", "force_cash") and not risk_on:
            allow_buy = False
        if slots > 0 and not day.empty and allow_buy:
            breadth = float((day["vote_hold"] >= 2).mean()) if "vote_hold" in day.columns else 1.0
            if breadth >= rules.min_breadth:
                held = set(weights.keys())
                buys = _entry_candidates(day, held, rules, skip_name_kw).head(slots)
                if not buys.empty:
                    remaining = max(0.0, 1.0 - sum(weights.values()))
                    target_w = 1.0 / day_max_pos
                    each = min(target_w, remaining / len(buys))
                    if each >= 1e-4:
                        for _, row in buys.iterrows():
                            code = str(row["code"]).zfill(6)
                            weights[code] = each
                            trade_cost += each * cost
                            n_buy += 1
                            bought_today.append(code)
                            trade_rows.append(
                                {
                                    "date": dt,
                                    "code": code,
                                    "name": row["name"],
                                    "side": "买入",
                                    "weight": round(each, 4),
                                    "vote_hold": int(row["vote_hold"]),
                                    "mom120_pct": row.get("mom120_pct"),
                                    "consensus": row["consensus"],
                                    "equity": round(equity, 2),
                                }
                            )

        equity *= 1.0 - trade_cost
        weights = _active_weights(weights)
        daily_weights.append(dict(weights))
        daily_buys.append(bought_today)
        daily_sells.append(sold_today)
        pnl_rows.append(
            {
                "date": dt,
                "n_held": len(weights),
                "port_ret": port_ret - trade_cost,
                "equity": equity,
                "cash_weight": round(1.0 - sum(weights.values()), 4),
                "buy_codes": "|".join(bought_today),
                "sell_codes": "|".join(sold_today),
                "trade_flag": "买" if bought_today else ("卖" if sold_today else ""),
            }
        )

    # 累计贡献
    for code, recs in etf_records.items():
        cum = 0.0
        for r in recs:
            cum += r["contrib_usd"]
            r["cum_contrib_usd"] = round(cum, 2)

    pnl = pd.DataFrame(pnl_rows)
    trades = pd.DataFrame(trade_rows)
    m = metrics(pnl["equity"], pnl["port_ret"], pnl["date"])
    m["max_positions"] = max_positions
    m["avg_held"] = round(pnl["n_held"].mean(), 2)
    m["max_held"] = int(pnl["n_held"].max())
    m["portfolio_buys"] = n_buy
    m["portfolio_sells"] = n_sell
    m["round_trips"] = min(n_buy, n_sell)
    r = pnl["port_ret"]
    gp = r[r > 0].sum()
    gl = -r[r < 0].sum()
    m["profit_factor"] = round(gp / gl, 2) if gl > 0 else 0.0
    m["pnl_abs"] = round(pnl["equity"].iloc[-1] - init_cash, 2)
    m["rules"] = rules.label
    return pnl, trades, m, daily_weights, etf_records


def trade_calendar_start(n_days: int = 252) -> pd.Timestamp:
    df = load_daily_tail(sina_symbol("510300"), tail=history_tail_bars(n_days))
    if df is None or len(df) < n_days:
        raise RuntimeError("无法加载 510300 日历")
    return pd.Timestamp(df["date"].iloc[-n_days])


def write_backtest_report(
    out_dir: Path,
    pnl: pd.DataFrame,
    port_m: dict,
    per_etf: list[dict],
    start: pd.Timestamp,
    end: pd.Timestamp,
    cost: float,
    init_cash: float = 100_000.0,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    pnl.to_csv(out_dir / "pnl_daily.csv", index=False, encoding="utf-8-sig")

    per_df = pd.DataFrame(per_etf).sort_values("total_return", ascending=False)
    per_df.to_csv(out_dir / "per_etf_metrics.csv", index=False, encoding="utf-8-sig")

    buys = int(per_df["buy_trades"].sum()) if not per_df.empty else 0
    sells = int(per_df["sell_trades"].sum()) if not per_df.empty else 0

    summary = {
        **port_m,
        "start": start.strftime("%Y-%m-%d"),
        "end": end.strftime("%Y-%m-%d"),
        "cost_per_side": cost,
        "init_cash": init_cash,
        "universe_backtested": len(per_df),
        "sum_buy_edges": buys,
        "sum_sell_edges": sells,
        "median_etf_return_pct": round(per_df["total_return"].median(), 2) if len(per_df) else 0,
        "mean_etf_return_pct": round(per_df["total_return"].mean(), 2) if len(per_df) else 0,
    }
    pd.DataFrame([summary]).to_csv(out_dir / "portfolio_summary.csv", index=False, encoding="utf-8-sig")

    readme = f"""# 共识策略近一年回测

区间: {start.date()} ~ {end.date()}

## 组合规则
- 三策略投票，≥2 票则持仓（与每日扫描共识持仓一致）
- 组合：每个交易日等权持有所有「持仓=1」的 ETF，日终再平衡
- 单边成本: {cost*10000:.1f}bp

## 组合结果
见 `portfolio_summary.csv`、`pnl_daily.csv`

## 单标的
见 `per_etf_metrics.csv`（每只 ETF 独立按共识信号回测）
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")
