# -*- coding: utf-8 -*-
"""生成可提交 GitHub 的每日操作摘要（次日开盘）。"""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PUBLISHED = ROOT / "published" / "daily"


def _read_csv(path: Path) -> pd.DataFrame:
    if not path.is_file():
        return pd.DataFrame()
    for enc in ("utf-8-sig", "utf-8", "gb18030", "gbk"):
        try:
            return pd.read_csv(path, encoding=enc)
        except UnicodeDecodeError:
            continue
    return pd.read_csv(path)


def _zcode(c) -> str:
    return str(c).strip().zfill(6)


def _parse_date(s) -> pd.Timestamp | None:
    if s is None or (isinstance(s, float) and pd.isna(s)):
        return None
    try:
        return pd.Timestamp(s).normalize()
    except Exception:
        return None


def _md_table(df: pd.DataFrame, cols: list[str]) -> str:
    if df.empty:
        return "_（无）_\n"
    sub = df[[c for c in cols if c in df.columns]].copy()
    headers = "| " + " | ".join(sub.columns) + " |"
    sep = "| " + " | ".join("---" for _ in sub.columns) + " |"
    lines = [headers, sep]
    for _, row in sub.iterrows():
        cells = [str(row[c]).replace("|", "/") for c in sub.columns]
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def build_next_open_md(
    signal_date: pd.Timestamp,
    equity: float,
    n_held: int,
    holdings_display: str,
    actions: pd.DataFrame,
    summary_row: dict | None,
    signals_buy: pd.DataFrame,
    signals_sell: pd.DataFrame,
) -> str:
    execute = signal_date + pd.Timedelta(days=1)
    while execute.weekday() >= 5:
        execute += pd.Timedelta(days=1)

    strat = "enhanced5y_n5（三票 + 动量>25% + 最多5只 + 沪深300>MA200）"
    if summary_row:
        ann = summary_row.get("annual_return", "")
        dd = summary_row.get("max_drawdown", "")
        perf = f"近5年年化 **{ann}%**，最大回撤 **{dd}%**"
    else:
        perf = ""

    buy = actions[actions["next_open_action"] == "开盘买入"].copy()
    sell = actions[actions["next_open_action"] == "开盘卖出"].copy()
    hold = actions[actions["next_open_action"] == "开盘持有"].copy()
    skip = actions[actions["next_open_action"].isin(["观望不动", "大盘弱·不开仓", "空仓不动"])].copy()

    lines = [
        "# ETF 组合 · 次日开盘操作",
        "",
        f"> 自动生成于 {datetime.now().strftime('%Y-%m-%d %H:%M')}（北京时间）",
        "",
        "## 概要",
        "",
        f"| 项目 | 值 |",
        f"| --- | --- |",
        f"| 信号日（已收盘） | **{signal_date.date()}** |",
        f"| 执行日（开盘） | **{execute.date()}** |",
        f"| 组合权益 | **{equity:,.2f}** |",
        f"| 持仓只数 | **{n_held}** |",
        f"| 策略 | {strat} |",
    ]
    if perf:
        lines.append(f"| 回测参考 | {perf} |")
    lines.extend(["", "## 当前持仓（信号日收盘后）", "", holdings_display or "_空仓_", ""])

    lines.extend(["## 开盘买入", ""])
    if buy.empty:
        lines.append("_无新开仓信号_\n")
    else:
        lines.append(
            _md_table(
                buy,
                ["code", "name", "next_open_brief", "vote_hold", "mom120_pct"],
            )
        )

    lines.extend(["## 开盘卖出", ""])
    if sell.empty:
        lines.append("_无卖出_\n")
    else:
        lines.append(_md_table(sell, ["code", "name", "next_open_brief"]))

    lines.extend(["## 开盘继续持有", ""])
    if hold.empty:
        lines.append("_无_\n")
    else:
        lines.append(_md_table(hold, ["code", "name", "next_open_brief", "mom120_pct"]))

    if not skip.empty:
        lines.extend(["## 观望 / 弱市不开仓（节选）", ""])
        lines.append(_md_table(skip.head(15), ["code", "name", "next_open_action", "next_open_brief"]))

    lines.extend(["## 全市场共识信号（参考）", ""])
    lines.append(f"- 共识买入候选：**{len(signals_buy)}** 只 → `signals_buy.csv`")
    lines.append(f"- 共识卖出候选：**{len(signals_sell)}** 只 → `signals_sell.csv`")
    lines.extend(
        [
            "",
            "## 说明",
            "",
            "- **开盘买入/卖出/持有** 以组合回测规则为准（`pnl_by_etf_all.csv`）。",
            "- 全市场 `signals_*.csv` 为单标的共识，未经过组合仓位与 MA200 过滤。",
            "- 完整 CSV 见本目录；历史大文件仍在本地 `mx_data_output/`（不入库）。",
            "",
        ]
    )
    return "\n".join(lines)


def collect_next_open_actions(
    port_dir: Path,
    signals_dir: Path,
) -> dict[str, Path | str]:
    """从 latest_portfolio + latest 信号生成 published/daily 文件，返回路径映射。"""
    PUBLISHED.mkdir(parents=True, exist_ok=True)

    pnl = _read_csv(port_dir / "pnl_daily.csv")
    all_etf = _read_csv(port_dir / "pnl_by_etf_all.csv")
    summary = _read_csv(port_dir / "portfolio_summary.csv")

    if pnl.empty:
        raise FileNotFoundError(f"缺少 {port_dir / 'pnl_daily.csv'}")

    pnl["date"] = pd.to_datetime(pnl["date"], errors="coerce")
    pnl = pnl.dropna(subset=["date"]).sort_values("date")
    signal_date = pnl["date"].iloc[-1]
    last = pnl.iloc[-1]

    equity = float(last.get("equity", 0))
    n_held = int(last.get("n_held", 0))
    holdings_display = str(last.get("holdings_display", "") or "")

    actions = pd.DataFrame()
    if not all_etf.empty:
        all_etf["date"] = pd.to_datetime(all_etf["date"], errors="coerce")
        day_rows = all_etf[all_etf["date"] == signal_date].copy()
        held_codes = set(
            _zcode(c)
            for c in str(last.get("holdings_codes", "")).split("|")
            if c.strip()
        )
        if held_codes:
            held_rows = day_rows[day_rows["code"].astype(str).map(_zcode).isin(held_codes)]
            if held_rows.empty:
                sub = all_etf[all_etf["code"].astype(str).map(_zcode).isin(held_codes)].sort_values("date")
                held_rows = sub.groupby(sub["code"].astype(str).map(_zcode), as_index=False).tail(1)
            # 补齐 pnl 有仓但 pnl_by_etf 缺行的标的
            have = set(held_rows["code"].astype(str).map(_zcode)) if not held_rows.empty else set()
            for c in sorted(held_codes - have):
                held_rows = pd.concat(
                    [
                        held_rows,
                        pd.DataFrame(
                            [
                                {
                                    "date": signal_date,
                                    "code": c,
                                    "name": c,
                                    "next_open_action": "开盘持有",
                                    "next_open_brief": f"{signal_date.date()} 开盘持有（组合持仓续作）",
                                }
                            ]
                        ),
                    ],
                    ignore_index=True,
                )
            for idx, r in held_rows.iterrows():
                if pd.isna(r.get("next_open_action")) or str(r.get("next_open_action", "")).strip() in ("", "nan"):
                    held_rows.at[idx, "next_open_action"] = "开盘持有"
                    held_rows.at[idx, "next_open_brief"] = (
                        f"{signal_date.date()} 开盘持有（持仓续作）"
                    )
        else:
            held_rows = pd.DataFrame()
        buy_rows = day_rows[day_rows["next_open_action"] == "开盘买入"]
        sell_rows = day_rows[day_rows["next_open_action"] == "开盘卖出"]
        actions = pd.concat([held_rows, buy_rows, sell_rows], ignore_index=True)
        actions = actions.drop_duplicates(subset=["code"], keep="last")
        if not actions.empty:
            actions["code"] = actions["code"].astype(str).map(_zcode)

    signals_buy = _read_csv(signals_dir / "buy_consensus.csv")
    signals_sell = _read_csv(signals_dir / "sell_consensus.csv")
    signals_hold = _read_csv(signals_dir / "hold_consensus.csv")

    summary_row = summary.iloc[0].to_dict() if not summary.empty else None
    md = build_next_open_md(
        signal_date,
        equity,
        n_held,
        holdings_display,
        actions,
        summary_row,
        signals_buy,
        signals_sell,
    )

    out_md = PUBLISHED / "NEXT_OPEN.md"
    out_md.write_text(md, encoding="utf-8")

    if not actions.empty:
        cols = [
            c
            for c in [
                "date",
                "next_date",
                "code",
                "name",
                "next_open_action",
                "next_open_brief",
                "today_close_action",
                "equity",
                "vote_hold",
                "mom120_pct",
                "market_ma200_ok",
            ]
            if c in actions.columns
        ]
        actions[cols].to_csv(PUBLISHED / "next_open_actions.csv", index=False, encoding="utf-8-sig")

    snap = last.to_frame().T
    keep = [c for c in ["date", "n_held", "equity", "port_ret", "trade_flag", "buy_codes", "sell_codes", "holdings_display"] if c in snap.columns]
    snap[keep].to_csv(PUBLISHED / "portfolio_snapshot.csv", index=False, encoding="utf-8-sig")

    if not summary.empty:
        shutil.copy2(port_dir / "portfolio_summary.csv", PUBLISHED / "portfolio_summary.csv")

    for name, src in [
        ("signals_buy.csv", signals_dir / "buy_consensus.csv"),
        ("signals_sell.csv", signals_dir / "sell_consensus.csv"),
        ("signals_hold.csv", signals_dir / "hold_consensus.csv"),
    ]:
        if src.is_file():
            shutil.copy2(src, PUBLISHED / name)

    (PUBLISHED / "LAST_UPDATED.txt").write_text(
        f"signal_date={signal_date.date()}\n"
        f"generated_at={datetime.now().isoformat()}\n"
        f"equity={equity:.2f}\n"
        f"source_portfolio={port_dir.name}\n",
        encoding="utf-8",
    )

    return {
        "next_open_md": out_md,
        "published_dir": PUBLISHED,
        "signal_date": str(signal_date.date()),
    }


def git_commit_and_push(published_dir: Path, signal_date: str) -> tuple[bool, str]:
    """提交 published/daily 并 push；Automation 需已配置 git 凭据。"""
    import subprocess

    def run(cmd: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")

    rel = published_dir.relative_to(ROOT).as_posix()
    run(["git", "add", rel, "published/README.md"])
    st = run(["git", "status", "--porcelain", rel])
    if not st.stdout.strip():
        return True, "无变更，跳过 commit"

    msg = f"chore(daily): ETF 次日开盘操作 {signal_date}"
    c = run(["git", "commit", "-m", msg])
    if c.returncode != 0:
        return False, c.stderr or c.stdout

    sha_r = run(["git", "rev-parse", "HEAD"])
    if sha_r.returncode != 0:
        return False, sha_r.stderr or sha_r.stdout
    sha = sha_r.stdout.strip()

    # 用户从 GitHub master 阅读 NEXT_OPEN.md；Automation 可能在非 master 分支运行
    cur = run(["git", "branch", "--show-current"]).stdout.strip()
    fetch = run(["git", "fetch", "origin", "master"])
    if fetch.returncode != 0:
        return False, fetch.stderr or fetch.stdout
    co = run(["git", "checkout", "master"])
    if co.returncode != 0:
        return False, co.stderr or co.stdout
    run(["git", "pull", "--ff-only", "origin", "master"])
    paths = [rel, "published/README.md"]
    run(["git", "checkout", sha, "--", *paths])
    st2 = run(["git", "status", "--porcelain", *paths])
    if st2.stdout.strip():
        run(["git", "commit", "-m", msg])
    p = run(["git", "push", "origin", "master"])
    if cur and cur != "master":
        run(["git", "checkout", cur])
    if p.returncode != 0:
        return False, p.stderr or p.stdout
    return True, "已 push 到 origin/master"


def publish_daily(
    portfolio_dir: Path | None = None,
    signals_dir: Path | None = None,
    push: bool = False,
) -> dict:
    portfolio_dir = portfolio_dir or (ROOT / "mx_data_output" / "etf_daily" / "latest_portfolio")
    signals_dir = signals_dir or (ROOT / "mx_data_output" / "etf_daily" / "latest")
    info = collect_next_open_actions(portfolio_dir, signals_dir)
    if push:
        ok, msg = git_commit_and_push(PUBLISHED, info["signal_date"])
        info["git_push_ok"] = ok
        info["git_push_msg"] = msg
    return info
