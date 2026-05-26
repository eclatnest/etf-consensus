# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioRules:
    """组合交易规则（可调参以提升收益/控制仓位）。"""

    max_positions: int = 10
    # 买入: buy_only | fill_vote2 | fill_vote3 | fill_vote2 2_mom5
    entry_mode: str = "fill_vote3"
    # 卖出: sell_only | vote_lt2 | vote_lt3
    exit_mode: str = "vote_lt2"
    min_mom120_pct: float = 0.0
    min_vote_entry: int = 2
    # 大盘择时: none | ma60 | ma200 | mom120_pos
    market_filter: str = "none"
    # 弱市: none=不限制 | no_buy=暂停新开 | force_cash=清仓
    regime_mode: str = "none"
    # 弱市最大持仓（None=与 max_positions 相同）
    weak_max_positions: int | None = None
    # 允许买入的最低广度（vote>=2 占比）
    min_breadth: float = 0.0

    @property
    def label(self) -> str:
        parts = [
            self.entry_mode,
            self.exit_mode,
            f"n{self.max_positions}",
            f"mom{self.min_mom120_pct}",
        ]
        if self.market_filter != "none":
            parts.append(f"mk{self.market_filter}")
        if self.regime_mode != "none":
            parts.append(f"rg{self.regime_mode}")
        if self.weak_max_positions is not None:
            parts.append(f"wk{self.weak_max_positions}")
        if self.min_breadth > 0:
            parts.append(f"br{self.min_breadth}")
        return "_".join(parts)


# 默认增强版（近1年约 26% 年化）：两票及以上择优入场 + 投票<2 出场
DEFAULT_ENHANCED = PortfolioRules(
    max_positions=10,
    entry_mode="fill_vote2",
    exit_mode="vote_lt2",
    min_mom120_pct=0.0,
    min_vote_entry=2,
)

# 5年优化版（高动量扫描最优约 19.2% 年化）：三票共识 + 动量>30% + 最多2只 + MA200 才开仓
DEFAULT_5Y = PortfolioRules(
    max_positions=2,
    entry_mode="fill_vote3",
    exit_mode="vote_lt2",
    min_mom120_pct=30.0,
    min_vote_entry=2,
    market_filter="ma200",
    regime_mode="no_buy",
)

# 5年备选（115套扫描次优约 17% 年化）：三票 + 动量>25% + 最多5只 + MA200 才开仓
PROFILE_5Y_N5_MOM25 = PortfolioRules(
    max_positions=5,
    entry_mode="fill_vote3",
    exit_mode="vote_lt2",
    min_mom120_pct=25.0,
    min_vote_entry=2,
    market_filter="ma200",
    regime_mode="no_buy",
)

BASELINE = PortfolioRules(
    max_positions=10,
    entry_mode="buy_only",
    exit_mode="sell_only",
    min_mom120_pct=0.0,
    min_vote_entry=2,
)
