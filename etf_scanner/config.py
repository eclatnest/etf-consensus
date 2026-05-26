# -*- coding: utf-8 -*-
"""全市场 ETF 扫描默认配置"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUT = ROOT / "mx_data_output" / "etf_scanner"


@dataclass
class ScanConfig:
    start: str = "20160101"
    end: str = "20251031"
    min_bars: int = 800
    workers: int = 8
    cost: float = 0.0005
    init_cash: float = 100_000.0
    out_dir: Path = field(default_factory=lambda: DEFAULT_OUT)
    # 名称过滤
    name_must_contain: str = "ETF"
    exclude_keywords: tuple[str, ...] = (
        "货币",
        "债券",
        "国债",
        "可转债",
        "短债",
        "纯债",
        "信用债",
        "利债",
        "地方债",
        "REIT",
    )
