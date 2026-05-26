#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
每晚数据更新：全市场信号 + 5年组合回测 CSV + PnL 图。
输出固定目录 mx_data_output/etf_daily/nightly/（便于 Automation / 本地任务读取）
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "mx_data_output" / "etf_daily" / "nightly"
LATEST_LINK = ROOT / "mx_data_output" / "etf_daily" / "latest_portfolio"


def run(cmd: list[str], desc: str) -> None:
    print(f"\n=== {desc} ===")
    print(" ".join(cmd))
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M")
    port_dir = OUT / f"portfolio_{ts}"
    OUT.mkdir(parents=True, exist_ok=True)

    py = sys.executable
    run([py, "run_etf_daily_signals.py", "--workers", "4"], "全市场 ETF 信号")

    run(
        [
            py,
            "run_etf_consensus_portfolio_10.py",
            "--days",
            "1260",
            "--profile",
            "enhanced5y_n5",
            "--out",
            str(port_dir),
        ],
        "5年组合回测 enhanced5y_n5 (fill_vote3+MA200+mom25%+5只)",
    )

    run([py, "plot_etf_portfolio_pnl.py", "--dir", str(port_dir)], "PnL 图")

    # 固定「最新」目录：复制 portfolio 结果 + 链到 nightly
    if LATEST_LINK.exists():
        if LATEST_LINK.is_symlink():
            LATEST_LINK.unlink()
        else:
            shutil.rmtree(LATEST_LINK, ignore_errors=True)
    shutil.copytree(port_dir, LATEST_LINK, dirs_exist_ok=True)

    status = OUT / "last_run.txt"
    status.write_text(
        f"ok {datetime.now().isoformat()}\nportfolio={port_dir.name}\n",
        encoding="utf-8",
    )

    from etf_scanner.publish_github import publish_daily

    pub = publish_daily(LATEST_LINK, ROOT / "mx_data_output" / "etf_daily" / "latest", push=False)
    print(f"\nGitHub 摘要: {pub['next_open_md']}")

    print(f"\n完成。组合 CSV/图: {port_dir.resolve()}")
    print(f"最新副本: {LATEST_LINK.resolve()}")
    print(f"信号 CSV: {(ROOT / 'mx_data_output' / 'etf_daily' / 'latest').resolve()}")
    print(f"次日操作 Markdown: {pub['next_open_md'].resolve()}")
    print("推送到 GitHub: python scripts/publish_daily_to_github.py --push")


if __name__ == "__main__":
    main()
