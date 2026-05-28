# AGENTS.md

## Cursor Cloud specific instructions

### Project overview

Chinese A-share ETF quantitative trading system using a 3-strategy consensus approach (120-day momentum, Donchian Channel 30/10, 60-day high breakout). All scripts are CLI-based Python; there is no web server, database, or Docker involved.

### Key scripts (see README.md for full list)

| Script | Purpose | Typical runtime |
|--------|---------|-----------------|
| `run_etf_daily_signals.py --sequential` | Full-market daily signal scan | ~10 min (1400+ ETFs, sequential API calls) |
| `run_etf_consensus_portfolio_10.py --days 60 --sequential` | Portfolio backtest | ~12 min for 60 days |
| `scripts/execute_next_open_actions.py --dry-run` | Dry-run trade execution plan | ~2 min |

### Important caveats

- **API latency**: All price data comes from Chinese financial APIs (EastMoney/Sina) via `akshare`. Fetches are slow from outside mainland China (~2s per ETF). Use `--sequential` to avoid rate-limiting errors; concurrent mode (`--workers N`) may cause intermittent API failures.
- **ETF universe cache**: The file `mx_data_output/etf_daily/universe.csv` caches the ETF list for the current day. Delete it or use `--refresh-universe` to force a refresh.
- **Signal detail cache**: Backtest caches signal data as pickle files (`mx_data_output/etf_daily/detail_cache_*d.pkl`). Delete these to force fresh data loading.
- **`MX_APIKEY`**: Required only for live mock-trading execution (`scripts/execute_next_open_actions.py` without `--dry-run`). Always use `--dry-run` or `--skip-moni` in dev/test environments.
- **No lint/test framework**: The project has no linter config, test suite, or CI pipeline. Validation is done by running the scripts and checking CSV/chart outputs.
- **Output directories**: Scripts create `mx_data_output/etf_daily/` subdirectories. These are gitignored.
