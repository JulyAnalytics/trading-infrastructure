"""
DEPRECATED (2026-07-18, Phase 6): superseded by scheduler v2 —
systems/orchestration/scheduler_v2.py, which runs inside the API process
(:8100), reads schedule times live from the parameter registry (OpsParams),
enforces the Marcus→Sarah dependency, retries, and alerts on failure.
Do not run this file; it bypasses the single-writer job discipline.
Kept only as a reference for the pre-v1.0 cron layout.
"""

"""
Daily Pipeline Scheduler
Runs the macro pipeline on a schedule so data is always fresh.

Usage:
    # Keep running (use screen / tmux / systemd):
    python scheduler.py

    # Or add to crontab for clean separation:
    # 0 18 * * 1-5  cd /path/to/phase1_macro && python data_feeds/macro_feed.py
    # 5 18 * * 1-5  cd /path/to/phase1_macro && python signals/regime_classifier.py

# NOTE: Priya (Phase 3 backtesting) runs manually, not on a schedule.
# It requires regime_state.json to be < BACKTEST_REGIME_STALENESS_HOURS old.
# If running Priya on Monday, ensure Marcus ran over the weekend or
# run Marcus manually first:
#   python -c "from systems.signals.regime_classifier import RegimeClassifier; \
#               c = RegimeClassifier(); c.classify(persist=True); c.write_output_contract(c.classify())"
# Then run research:
#   from systems.backtest.research_pipeline import ResearchPipeline
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
    # Retired 2026-07-18 (Phase 6), and code-enforced retired 2026-07-19:
    # scheduler v2 (systems/orchestration/scheduler_v2.py) runs inside the
    # API process, reads times live from OpsParams, enforces the Marcus→Sarah
    # dependency, and submits through JobManager (single-writer discipline).
    # This legacy loop bypasses all of that. Refuse to run rather than risk a
    # second scheduler firing the same engines from a second process.
    import sys
    sys.stderr.write(
        "scheduler.py is retired. The live scheduler is systems/orchestration/"
        "scheduler_v2.py, which runs inside the API process:\n"
        "    venv/bin/python -m uvicorn systems.api.main:app "
        "--host 127.0.0.1 --port 8100\n"
        "This file is kept only as a historical reference for the pre-v1.0 "
        "cron layout. It will not start.\n"
    )
    sys.exit(2)
