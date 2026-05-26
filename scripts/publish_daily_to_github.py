#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""生成 published/daily/NEXT_OPEN.md 并可选 push 到 GitHub。"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from etf_scanner.publish_github import publish_daily


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--portfolio-dir", default=str(ROOT / "mx_data_output" / "etf_daily" / "latest_portfolio"))
    ap.add_argument("--signals-dir", default=str(ROOT / "mx_data_output" / "etf_daily" / "latest"))
    ap.add_argument("--push", action="store_true", help="git commit + push published/daily")
    args = ap.parse_args()

    info = publish_daily(Path(args.portfolio_dir), Path(args.signals_dir), push=args.push)
    print(f"已生成: {info['next_open_md']}")
    print(f"信号日: {info['signal_date']}")
    if args.push:
        print(f"Git: {info.get('git_push_msg', '')}")


if __name__ == "__main__":
    main()
