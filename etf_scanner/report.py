# -*- coding: utf-8 -*-
"""扫描结果输出"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from etf_scanner.strategies import PRACTICAL_IDS


def save_reports(df: pd.DataFrame, out_dir: Path, period: str) -> dict[str, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[str, Path] = {}

    df.to_csv(out_dir / "scan_all.csv", index=False, encoding="utf-8-sig")
    paths["all"] = out_dir / "scan_all.csv"

    triple = df[df["beats_practical"] == 3].sort_values("practical_cagr_avg", ascending=False)
    triple.to_csv(out_dir / "scan_practical_3of3.csv", index=False, encoding="utf-8-sig")
    paths["triple"] = out_dir / "scan_practical_3of3.csv"

    for pid, label in [
        ("mom120_5", "动量120"),
        ("dc30_10", "唐奇安30"),
        ("hi60", "60日新高"),
    ]:
        sub = df.sort_values(f"{pid}_cagr", ascending=False).head(50)
        p = out_dir / f"top50_{pid}.csv"
        sub.to_csv(p, index=False, encoding="utf-8-sig")
        paths[pid] = p

    # 简要 markdown 摘要
    lines = [
        f"# ETF 全市场策略扫描\n",
        f"区间: {period}\n",
        f"有效样本: {len(df)} 只\n",
        f"三实操均跑赢持有: {len(triple)} 只\n\n",
        "## 综合得分 Top15\n",
    ]
    cols = ["code", "name", "score", "practical_cagr_avg", "beats_practical", "bh_cagr"]
    cols += [f"{p}_cagr" for p in PRACTICAL_IDS]
    lines.append("```\n" + df[cols].head(15).to_string(index=False) + "\n```\n")
    (out_dir / "README_scan.md").write_text("\n".join(lines), encoding="utf-8")
    paths["readme"] = out_dir / "README_scan.md"
    return paths


def print_summary(df: pd.DataFrame, universe_n: int) -> None:
    triple = df[df["beats_practical"] == 3]
    print(f"\n有效: {len(df)} / {universe_n} | 三策略跑赢持有: {len(triple)} 只\n")
    cols = ["code", "name", "score", "practical_cagr_avg", "mom120_5_cagr", "dc30_10_cagr", "hi60_cagr", "bh_cagr"]
    print("=== 综合得分 Top15 ===")
    print(df[cols].head(15).to_string(index=False))
