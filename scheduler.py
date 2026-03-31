"""
Daily Pipeline Scheduler
Runs the macro pipeline on a schedule so data is always fresh.

Usage:
    # Keep running (use screen / tmux / systemd):
    python scheduler.py

    # Or add to crontab for clean separation:
    # 0 18 * * 1-5  cd /path/to/phase1_macro && python data_feeds/macro_feed.py
    # 5 18 * * 1-5  cd /path/to/phase1_macro && python signals/regime_classifier.py
"""

import sys
import os
import schedule
import time
from loguru import logger
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from systems.data_feeds.macro_feed import (
    run_fred_pipeline, compute_derived_series, fetch_cot_data,
    fetch_equity_data, fetch_calendar_data, build_fred_client,
)
from systems.signals.regime_classifier import RegimeClassifier
from systems.utils.db import get_connection
from systems.sarah.daily_vol_run import run_daily_vol


def run_daily_pipeline():
    logger.info("="*50)
    logger.info(f"Daily pipeline started at {datetime.now()}")

    # 1. Fetch all FRED data (incremental)
    try:
        run_fred_pipeline(full=False)
        compute_derived_series()
        logger.info("FRED data updated.")
    except Exception as e:
        logger.error(f"FRED pipeline failed: {e}")

    # 2. Fetch CFTC COT (weekly — fine to run daily, will just update latest)
    try:
        conn = get_connection()
        fetch_cot_data(conn)
        conn.close()
        logger.info("COT data updated.")
    except Exception as e:
        logger.error(f"COT pipeline failed: {e}")

    # 3. Run regime classifier and persist
    try:
        clf = RegimeClassifier()
        result = clf.classify(persist=True)
        clf.write_output_contract(result)
        logger.info(f"Regime classified: {result.regime} (score: {result.composite_score:+.2f})")
        logger.info(str(result))
    except Exception as e:
        logger.error(f"Regime classification failed: {e}")

    logger.info(f"Pipeline complete at {datetime.now()}")


def run_weekly_full_refresh():
    """Full history pull — run once a week to catch any revisions."""
    logger.info("Weekly full refresh starting...")
    try:
        run_fred_pipeline(full=True)
        compute_derived_series()
        logger.info("Weekly full refresh complete.")
    except Exception as e:
        logger.error(f"Weekly full refresh failed: {e}")


def run_nightly_snapshot():
    try:
        from systems.reports.snapshot_generator import generate_snapshot
        path = generate_snapshot()
        logger.info(f"Snapshot saved: {path}")
    except Exception as e:
        logger.error(f"Snapshot generation failed: {e}")


if __name__ == "__main__":
    os.makedirs("logs", exist_ok=True)
    logger.add("logs/phase1.log", rotation="1 week", retention="4 weeks")

    # Run immediately on startup
    run_daily_pipeline()

    # Schedule: weekdays at 6:05pm ET (after US close + data publishing lag)
    schedule.every().monday.at("18:05").do(run_daily_pipeline)
    schedule.every().tuesday.at("18:05").do(run_daily_pipeline)
    schedule.every().wednesday.at("18:05").do(run_daily_pipeline)
    schedule.every().thursday.at("18:05").do(run_daily_pipeline)
    schedule.every().friday.at("18:05").do(run_daily_pipeline)

    # Weekly full refresh on Sunday evening
    schedule.every().sunday.at("20:00").do(run_weekly_full_refresh)

    # Phase 4: weekly calendar fetch (Sunday after full refresh)
    schedule.every().sunday.at("20:05").do(
        lambda: fetch_calendar_data(build_fred_client(), get_connection())
    )

    # Phase 4: daily SPY equity fetch
    schedule.every().day.at("18:05").do(
        lambda: fetch_equity_data(get_connection())
    )

    # Sarah — vol surface daily run (08:00, after Marcus writes regime_state.json)
    schedule.every().monday.at("08:00").do(run_daily_vol)
    schedule.every().tuesday.at("08:00").do(run_daily_vol)
    schedule.every().wednesday.at("08:00").do(run_daily_vol)
    schedule.every().thursday.at("08:00").do(run_daily_vol)
    schedule.every().friday.at("08:00").do(run_daily_vol)

    # Phase 4: nightly snapshot, weekdays only (single lambda)
    schedule.every().day.at("18:15").do(
        lambda: run_nightly_snapshot() if datetime.today().weekday() < 5 else None
    )

    logger.info("Scheduler running. Press Ctrl+C to stop.")
    while True:
        schedule.run_pending()
        time.sleep(60)
