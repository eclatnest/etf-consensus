@echo off
cd /d "%~dp0"
python run_etf_nightly_update.py >> mx_data_output\etf_daily\nightly\cron.log 2>&1
