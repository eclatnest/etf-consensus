#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
根据 published/daily（每晚数据更新产物）在妙想模拟账户执行次日开盘操作。

读取：
  - published/daily/next_open_actions.csv
  - published/daily/portfolio_snapshot.csv
  - published/daily/LAST_UPDATED.txt

顺序：一键撤单 → 卖出（目标外持仓 + 开盘卖出）→ 买入（开盘买入，等权目标市值）
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
PUBLISHED = ROOT / "published" / "daily"
DEFAULT_API = "https://mkapi2.dfcfs.com/finskillshub"
EXEC_LOG_DIR = ROOT / "mx_data_output" / "etf_daily" / "executions"


def _zcode(c) -> str:
    return str(c).strip().zfill(6)


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)


def git_pull() -> str:
    r = subprocess.run(
        ["git", "pull", "--ff-only", "origin", "HEAD"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise RuntimeError(f"git pull 失败: {out.strip()}")
    return out.strip() or "ok"


def parse_holdings_display(text: str) -> tuple[list[str], dict[str, float]]:
    """从 portfolio_snapshot 的 holdings_display 解析代码与权重（0~1）。"""
    codes: list[str] = []
    weights: dict[str, float] = {}
    if not text or str(text).strip() in ("", "nan", "_空仓_"):
        return codes, weights
    for part in str(text).split(";"):
        part = part.strip()
        if not part:
            continue
        m = re.match(r"(\d{6})\[[^\]]*\]\s+[^0-9]*?([\d.]+)\s*%", part)
        if m:
            c, w = _zcode(m.group(1)), float(m.group(2)) / 100.0
            codes.append(c)
            weights[c] = w
        else:
            m2 = re.search(r"(\d{6})", part)
            if m2:
                codes.append(_zcode(m2.group(1)))
    # 去重保序
    seen: set[str] = set()
    ordered: list[str] = []
    for c in codes:
        if c not in seen:
            seen.add(c)
            ordered.append(c)
    if ordered and not weights:
        w = 1.0 / len(ordered)
        weights = {c: w for c in ordered}
    return ordered, weights


class MoniClient:
    def __init__(self, api_key: str, base_url: str) -> None:
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.headers = {"apikey": api_key, "Content-Type": "application/json"}

    def post(self, path: str, body: dict) -> dict:
        r = requests.post(
            f"{self.base_url}{path}",
            headers=self.headers,
            json=body,
            timeout=45,
        )
        r.raise_for_status()
        return r.json()

    def cancel_all(self) -> dict:
        return self.post("/api/claw/mockTrading/cancel", {"type": "all"})

    def positions(self) -> dict:
        return self.post("/api/claw/mockTrading/positions", {"moneyUnit": 1})

    def balance(self) -> dict:
        return self.post("/api/claw/mockTrading/balance", {"moneyUnit": 1})

    def market_trade(self, side: str, code: str, quantity: int) -> dict:
        return self.post(
            "/api/claw/mockTrading/trade",
            {
                "type": side,
                "stockCode": _zcode(code),
                "quantity": quantity,
                "useMarketPrice": True,
            },
        )


def fetch_etf_spot_prices(codes: list[str]) -> dict[str, float]:
    import akshare as ak

    df = ak.fund_etf_spot_em()
    df = df.rename(columns={"代码": "code", "最新价": "price"})
    df["code"] = df["code"].astype(str).str.zfill(6)
    df["price"] = pd.to_numeric(df["price"], errors="coerce")
    mp = {str(r.code): float(r.price) for r in df.itertuples() if pd.notna(r.price)}
    out: dict[str, float] = {}
    for c in codes:
        if c in mp and mp[c] > 0:
            out[c] = mp[c]
    return out


def qty_for_value(value: float, price: float) -> int:
    if price <= 0 or value <= 0:
        return 0
    raw = int(value / price / 100) * 100
    return max(raw, 0)


def load_plan() -> dict:
    actions_path = PUBLISHED / "next_open_actions.csv"
    snap_path = PUBLISHED / "portfolio_snapshot.csv"
    updated_path = PUBLISHED / "LAST_UPDATED.txt"

    if not actions_path.is_file() and not (PUBLISHED / "NEXT_OPEN.md").is_file():
        raise FileNotFoundError(
            f"缺少 {PUBLISHED} 下的操作文件，请先运行 run_etf_nightly_update.py "
            "或 python scripts/publish_daily_to_github.py --push"
        )

    actions = _read_csv(actions_path)
    snap = _read_csv(snap_path)

    target_codes: list[str] = []
    weights: dict[str, float] = {}
    equity = 0.0
    signal_date = ""

    if not snap.empty:
        row = snap.iloc[-1]
        signal_date = str(row.get("date", ""))[:10]
        equity = float(row.get("equity", 0) or 0)
        target_codes, weights = parse_holdings_display(str(row.get("holdings_display", "")))

    explicit_sell: set[str] = set()
    explicit_buy: set[str] = set()
    if not actions.empty:
        if "code" in actions.columns:
            actions["code"] = actions["code"].astype(str).map(_zcode)
        for _, r in actions.iterrows():
            act = str(r.get("next_open_action", "")).strip()
            c = _zcode(r.get("code", ""))
            if not c:
                continue
            if act == "开盘卖出":
                explicit_sell.add(c)
            elif act == "开盘买入":
                explicit_buy.add(c)
            elif act == "开盘持有" and c not in target_codes:
                target_codes.append(c)

    # 目标组合：快照持仓为准；显式卖出从目标中剔除；显式买入加入
    target_set = set(target_codes) - explicit_sell
    target_set |= explicit_buy
    if not target_set and not explicit_sell and not explicit_buy:
        # 仅 actions 里「持有」行
        if not actions.empty:
            hold = actions[actions["next_open_action"] == "开盘持有"]
            target_set = set(hold["code"].astype(str).map(_zcode))

    meta = ""
    if updated_path.is_file():
        meta = updated_path.read_text(encoding="utf-8")

    return {
        "signal_date": signal_date,
        "equity": equity,
        "target_codes": sorted(target_set),
        "weights": weights,
        "explicit_sell": sorted(explicit_sell),
        "explicit_buy": sorted(explicit_buy),
        "actions_rows": len(actions),
        "last_updated": meta,
    }


def build_trades(plan: dict, client: MoniClient | None, dry_run: bool) -> dict:
    target = set(plan["target_codes"])
    pos_resp = None
    current: dict[str, int] = {}
    avail_balance = 0.0
    total_assets = 0.0

    if client:
        pos_resp = client.positions()
        data = pos_resp.get("data") or {}
        total_assets = float(data.get("totalAssets") or 0)
        avail_balance = float(data.get("availBalance") or 0)
        for h in data.get("posList") or []:
            c = _zcode(h.get("secCode", ""))
            n = int(h.get("availCount") or h.get("count") or 0)
            if n > 0:
                current[c] = n
    elif dry_run:
        total_assets = float(plan.get("equity") or 0)
        avail_balance = total_assets

    sells: list[dict] = []
    for code, qty in sorted(current.items()):
        if code not in target or code in plan["explicit_sell"]:
            sells.append({"code": code, "quantity": qty, "reason": "调仓卖出/开盘卖出"})

    for code in plan["explicit_sell"]:
        if code in current and code not in {s["code"] for s in sells}:
            sells.append({"code": code, "quantity": current[code], "reason": "开盘卖出"})

    buys: list[dict] = []
    to_buy = [c for c in plan["explicit_buy"] if c in target]
    # 若目标组合有新增标的（在 target 但不在 current），也买入
    for c in sorted(target):
        if c not in current and c not in to_buy:
            to_buy.append(c)
    to_buy = sorted(set(to_buy))

    prices = fetch_etf_spot_prices(list(target | set(current.keys()) | set(to_buy))) if to_buy else {}

    n_pos = max(len(target), 1)
    for code in to_buy:
        w = plan["weights"].get(code, 1.0 / n_pos)
        budget = total_assets * w * 0.98 if total_assets > 0 else avail_balance / max(len(to_buy), 1)
        price = prices.get(code, 0)
        qty = qty_for_value(budget, price)
        if qty < 100:
            continue
        buys.append(
            {
                "code": code,
                "quantity": qty,
                "price_ref": price,
                "budget": round(budget, 2),
                "weight": w,
                "reason": "开盘买入/调仓买入",
            }
        )

    return {
        "target_codes": sorted(target),
        "current_positions": current,
        "total_assets": total_assets,
        "avail_balance": avail_balance,
        "sells": sells,
        "buys": buys,
        "dry_run": dry_run,
    }


def execute_trades(client: MoniClient, trades: dict) -> list[dict]:
    log: list[dict] = []
    cancel = client.cancel_all()
    log.append({"step": "cancel_all", "result": cancel})

    for s in trades["sells"]:
        if s["quantity"] < 100:
            continue
        res = client.market_trade("sell", s["code"], s["quantity"])
        log.append({"step": "sell", **s, "result": res})
        time.sleep(0.4)

    time.sleep(1.0)
    bal = client.balance()
    trades["avail_balance"] = float((bal.get("data") or {}).get("availBalance") or 0)

    for b in trades["buys"]:
        res = client.market_trade("buy", b["code"], b["quantity"])
        log.append({"step": "buy", **b, "result": res})
        time.sleep(0.4)

    pos_after = client.positions()
    log.append({"step": "positions_after", "result": pos_after})
    return log


def main() -> None:
    ap = argparse.ArgumentParser(description="按 published/daily 执行次日开盘模拟交易")
    ap.add_argument("--pull", action="store_true", help="执行前 git pull 拉取最新 published/daily")
    ap.add_argument("--dry-run", action="store_true", help="只输出计划，不下单")
    ap.add_argument("--skip-moni", action="store_true", help="不调用妙想 API，仅打印计划")
    args = ap.parse_args()

    if args.pull:
        print(git_pull())

    plan = load_plan()
    print("=== 操作计划来源 ===")
    print(f"信号日: {plan['signal_date']}")
    print(f"目标持仓: {plan['target_codes']}")
    print(f"显式卖出: {plan['explicit_sell']}")
    print(f"显式买入: {plan['explicit_buy']}")
    if plan.get("last_updated"):
        print(plan["last_updated"].strip())

    api_key = os.environ.get("MX_APIKEY", "")
    base = os.environ.get("MX_API_URL", DEFAULT_API)
    client = None
    if not args.skip_moni and not args.dry_run:
        if not api_key:
            print("错误: 未设置 MX_APIKEY，无法下单。可加 --dry-run 仅查看计划。", file=sys.stderr)
            sys.exit(1)
        client = MoniClient(api_key, base)

    trades = build_trades(plan, client, dry_run=args.dry_run or args.skip_moni)

    print("\n=== 拟执行交易 ===")
    print(json.dumps(trades, ensure_ascii=False, indent=2))

    log: list[dict] = []
    if client and not args.dry_run:
        print("\n=== 开始下单（妙想模拟） ===")
        log = execute_trades(client, trades)

    EXEC_LOG_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = EXEC_LOG_DIR / f"run_{ts}.json"
    payload = {"plan": plan, "trades": trades, "execution_log": log, "at": datetime.now().isoformat()}
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n日志已写入: {out}")


if __name__ == "__main__":
    main()
