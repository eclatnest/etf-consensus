#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
全市场 ETF 策略扫描器

用法:
  python run_etf_scanner.py
  python run_etf_scanner.py --start 20210101 --end 20251031
  python run_etf_scanner.py --min-bars 600 --workers 12
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

from etf_scanner.config import ScanConfig
from etf_scanner.data import load_etf_universe
from etf_scanner.engine import scan_market
from etf_scanner.report import print_summary, save_reports


def main() -> None:
    ap = argparse.ArgumentParser(description="全市场 ETF 策略扫描")
    ap.add_argument("--start", default="20160101", help="开始 YYYYMMDD")
    ap.add_argument("--end", default="20251031", help="结束 YYYYMMDD")
    ap.add_argument("--min-bars", type=int, default=800, help="最少K线根数")
    ap.add_argument("--workers", type=int, default=8, help="并发线程")
    ap.add_argument("--out", default="", help="输出目录")
    args = ap.parse_args()

    ts = datetime.now().strftime("%Y%m%d_%H%M")
    out_dir = Path(args.out) if args.out else ScanConfig().out_dir / ts
    out_dir.mkdir(parents=True, exist_ok=True)

    cfg = ScanConfig(
        start=args.start,
        end=args.end,
        min_bars=args.min_bars,
        workers=args.workers,
        out_dir=out_dir,
    )

    print("=== ETF 全市场策略扫描器 ===\n")
    print(f"区间: {cfg.start} ~ {cfg.end} | 最少 {cfg.min_bars} 根 | 线程 {cfg.workers}")
    print(f"输出: {out_dir}\n")

    universe = load_etf_universe(cfg)
    print(f"标的池: {len(universe)} 只 (名称含ETF, 排除债/货币)\n")

    def prog(done: int, total: int, ok: int, elapsed: float) -> None:
        if done % 50 == 0 or done == total:
            print(f"  进度 {done}/{total}  有效 {ok}  用时 {elapsed:.0f}s")

    result = scan_market(universe, cfg, on_progress=prog)
    if result.empty:
        print("无有效结果，请缩短 --min-bars 或扩大区间")
        return

    period = f"{cfg.start} ~ {cfg.end}"
    paths = save_reports(result, out_dir, period)
    print_summary(result, len(universe))

    print("\n输出文件:")
    for k, p in paths.items():
        print(f"  {k}: {p}")


if __name__ == "__main__":
    main()
