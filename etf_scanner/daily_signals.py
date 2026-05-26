# -*- coding: utf-8 -*-
"""每日 ETF 买卖信号：对比昨日/今日仓位变化"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import akshare as ak
import pandas as pd

from etf_scanner.config import ScanConfig
from etf_scanner.data import load_etf_universe_cached, sina_symbol
from etf_scanner.strategies import PRACTICAL_IDS, StrategyDef, DEFAULT_STRATEGIES

# 信号计算所需最少K线（动量120 + 缓冲）
LOOKBACK_BARS = 280


def load_daily_tail(sina: str, tail: int = LOOKBACK_BARS) -> pd.DataFrame | None:
    try:
        df = ak.fund_etf_hist_sina(symbol=sina)
        df["date"] = pd.to_datetime(df["date"])
        for c in ("open", "high", "low", "close"):
            df[c] = pd.to_numeric(df[c], errors="coerce")
        df = df.sort_values("date").dropna(subset=["close"]).tail(tail)
        if len(df) < 200:
            return None
        return df.reset_index(drop=True)
    except Exception:
        return None


def signal_action_at(sig: pd.Series, idx: int) -> tuple[str, int, int]:
    """在指定 K 线索引处计算操作建议（收盘算信号 -> 次日开盘执行）。"""
    pos_s = sig.shift(1).fillna(0).astype(int)
    if idx < 0 or idx >= len(pos_s):
        return "空仓", 0, 0
    pos = int(pos_s.iloc[idx])
    prev_pos = int(pos_s.iloc[idx - 1]) if idx > 0 else 0
    chg = pos - prev_pos
    if chg == 1:
        label = "买入"
    elif chg == -1:
        label = "卖出"
    elif pos == 1:
        label = "持有"
    else:
        label = "空仓"
    return label, pos, prev_pos


def signal_action(sig: pd.Series) -> tuple[str, int, int]:
    """
    今日收盘信号 -> 明日开盘仓位 (shift(1))。
    返回: (操作建议, 明日仓位, 前一日明日仓位)
    """
    pos_s = sig.shift(1).fillna(0).astype(int)
    pos = int(pos_s.iloc[-1])
    prev_pos = int(pos_s.iloc[-2]) if len(pos_s) > 1 else 0
    return signal_action_at(sig, len(sig) - 1)


def consensus_label(row: dict) -> str:
    buy_n = sum(1 for p in PRACTICAL_IDS if row.get(f"{p}_action") == "买入")
    sell_n = sum(1 for p in PRACTICAL_IDS if row.get(f"{p}_action") == "卖出")
    votes = int(row.get("vote_hold", 0))
    if buy_n >= 1 and votes >= 2:
        return "买入"
    if sell_n >= 1 and votes == 0:
        return "卖出"
    if votes >= 2:
        return "持有"
    if votes == 1:
        return "观望"
    return "空仓"


def eval_at_index(
    code: str,
    name: str,
    df: pd.DataFrame,
    idx: int,
    strategies: list[StrategyDef],
) -> dict | None:
    if idx < 0 or idx >= len(df) or idx < 200:
        return None
    last_date = df["date"].iloc[idx]
    close = float(df["close"].iloc[idx])
    row: dict = {
        "code": code,
        "name": name,
        "date": last_date.strftime("%Y-%m-%d"),
        "close": round(close, 4),
    }
    votes = 0
    for sd in strategies:
        if sd.id not in PRACTICAL_IDS:
            continue
        sig = sd.build(df)
        label, pos, _prev = signal_action_at(sig, idx)
        row[f"{sd.id}_action"] = label
        row[f"{sd.id}_pos"] = pos
        if pos == 1:
            votes += 1
        if sd.id == "mom120_5":
            mom = df["close"].pct_change(120).iloc[idx] * 100
            row["mom120_pct"] = round(float(mom), 2) if pd.notna(mom) else None
    row["vote_hold"] = votes
    row["consensus"] = consensus_label(row)
    return row


def eval_daily(
    code: str,
    name: str,
    strategies: list[StrategyDef],
) -> dict | None:
    sina = sina_symbol(code)
    df = load_daily_tail(sina)
    if df is None:
        return None
    last_date = df["date"].iloc[-1]
    close = float(df["close"].iloc[-1])
    row: dict = {
        "code": code,
        "name": name,
        "sina": sina,
        "date": last_date.strftime("%Y-%m-%d"),
        "close": round(close, 4),
    }
    votes = 0
    for sd in strategies:
        if sd.id not in PRACTICAL_IDS:
            continue
        sig = sd.build(df)
        label, pos, _prev = signal_action(sig)
        row[f"{sd.id}_action"] = label
        row[f"{sd.id}_pos"] = pos
        if pos == 1:
            votes += 1
        # 唐奇安附加价位
        if sd.id == "dc30_10":
            hi = df["close"].rolling(30).max().shift(1).iloc[-1]
            lo = df["close"].rolling(10).min().shift(1).iloc[-1]
            row["dc30_hi"] = round(float(hi), 4) if pd.notna(hi) else None
            row["dc30_lo"] = round(float(lo), 4) if pd.notna(lo) else None
        if sd.id == "mom120_5":
            mom = df["close"].pct_change(120).iloc[-1] * 100
            row["mom120_pct"] = round(float(mom), 2) if pd.notna(mom) else None

    row["vote_hold"] = votes
    row["consensus"] = consensus_label(row)
    return row


def scan_daily_signals(
    cfg: ScanConfig,
    strategies: list[StrategyDef] | None = None,
    universe: pd.DataFrame | None = None,
    sequential: bool = False,
) -> pd.DataFrame:
    strategies = strategies or [s for s in DEFAULT_STRATEGIES if s.id in PRACTICAL_IDS]
    universe = universe if universe is not None else load_etf_universe_cached(cfg)
    rows: list[dict] = []
    total = len(universe)
    t0 = time.time()
    workers = 1 if sequential else min(cfg.workers, 6)

    def _run_one(r) -> dict | None:
        return eval_daily(r.code, r.name, strategies)

    if sequential:
        done = 0
        for r in universe.itertuples():
            done += 1
            try:
                row = _run_one(r)
                if row:
                    rows.append(row)
            except Exception:
                pass
            if done % 100 == 0 or done == total:
                print(f"  进度 {done}/{total}  有效 {len(rows)}  {time.time()-t0:.0f}s")
        return pd.DataFrame(rows)

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(eval_daily, r.code, r.name, strategies): r for r in universe.itertuples()
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
            if done % 100 == 0 or done == total:
                print(f"  进度 {done}/{total}  有效 {len(rows)}  {time.time()-t0:.0f}s")

    return pd.DataFrame(rows)


def build_report(df: pd.DataFrame, out_dir: Path) -> dict[str, pd.DataFrame]:
    out_dir.mkdir(parents=True, exist_ok=True)
    trade_date = df["date"].iloc[0] if not df.empty else datetime.now().strftime("%Y-%m-%d")

    buy = df[df["consensus"] == "买入"].sort_values(["vote_hold", "code"], ascending=[False, True])
    sell = df[df["consensus"] == "卖出"].sort_values("code")
    hold = df[df["consensus"] == "持有"].sort_values("vote_hold", ascending=False)

    # 分策略明细
    for pid in PRACTICAL_IDS:
        b = df[df[f"{pid}_action"] == "买入"]
        s = df[df[f"{pid}_action"] == "卖出"]
        b.to_csv(out_dir / f"buy_{pid}.csv", index=False, encoding="utf-8-sig")
        s.to_csv(out_dir / f"sell_{pid}.csv", index=False, encoding="utf-8-sig")

    buy.to_csv(out_dir / "buy_consensus.csv", index=False, encoding="utf-8-sig")
    sell.to_csv(out_dir / "sell_consensus.csv", index=False, encoding="utf-8-sig")
    hold.to_csv(out_dir / "hold_consensus.csv", index=False, encoding="utf-8-sig")
    df.to_csv(out_dir / "signals_all.csv", index=False, encoding="utf-8-sig")

    summary = pd.DataFrame(
        [
            {"type": "买入(共识)", "count": len(buy)},
            {"type": "卖出(共识)", "count": len(sell)},
            {"type": "持有(共识)", "count": len(hold)},
            {"type": "总扫描", "count": len(df)},
        ]
    )
    summary.to_csv(out_dir / "summary.csv", index=False, encoding="utf-8-sig")

    readme = out_dir / "README_daily.md"
    readme.write_text(
        f"""# ETF 每日信号

生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M")}

## 共识规则

| 结论 | 条件 |
|------|------|
| 买入 | 任一策略今日触发买入，且三策略明日持仓数 ≥ 2 |
| 卖出 | 任一策略今日触发卖出，且三策略明日持仓数 = 0 |
| 持有 | 明日持仓数 ≥ 2，无上述买卖 |
| 观望 | 明日仅 1 个策略持仓 |
| 空仓 | 明日三策略均空仓 |

## 文件

- `buy_consensus.csv` / `sell_consensus.csv` / `hold_consensus.csv`
- `buy_mom120_5.csv` 等分策略买卖列表
- `signals_all.csv` 全量

执行: `python run_etf_daily_signals.py`
""",
        encoding="utf-8",
    )
    return {"buy": buy, "sell": sell, "hold": hold, "all": df, "trade_date": trade_date}
