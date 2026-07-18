"""
Child-process job entry point: `python -m systems.orchestration.run_job <name>`.

Runs in a FRESH interpreter so the parameter registry's active versions are
picked up at import time, and so this process is the only DuckDB writer for
the duration of the pipeline. Writes nothing to the jobs table — the parent
JobManager owns job-state persistence.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _marcus_classify():
    from systems.signals.regime_classifier import RegimeClassifier
    clf = RegimeClassifier()
    result = clf.classify(persist=True)
    clf.write_output_contract(result)
    print(result)


def _fred_incremental():
    from systems.data_feeds.macro_feed import (
        run_fred_pipeline, compute_derived_series, fetch_cot_data,
    )
    from systems.utils.db import get_connection
    run_fred_pipeline(full=False)
    compute_derived_series()
    conn = get_connection()
    try:
        fetch_cot_data(conn)
    finally:
        conn.close()


def _sarah_daily_vol():
    from systems.sarah.daily_vol_run import run_daily_vol
    run_daily_vol()


def _snapshot_pdf():
    from systems.reports.snapshot_generator import generate_snapshot
    path = generate_snapshot()
    print(f"snapshot: {path}")


def _backfill_regime_history():
    import runpy
    runpy.run_path("scripts/backfill_regime_history.py", run_name="__main__")


def _calibrate_divergence():
    import runpy
    runpy.run_path("scripts/calibrate_divergence_threshold.py", run_name="__main__")


RUNNERS = {
    "marcus_classify":         _marcus_classify,
    "fred_incremental":        _fred_incremental,
    "sarah_daily_vol":         _sarah_daily_vol,
    "snapshot_pdf":            _snapshot_pdf,
    "backfill_regime_history": _backfill_regime_history,
    "calibrate_divergence":    _calibrate_divergence,
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in RUNNERS:
        print(f"usage: python -m systems.orchestration.run_job "
              f"<{'|'.join(sorted(RUNNERS))}>", file=sys.stderr)
        return 2
    name = sys.argv[1]
    from systems.params import all_active_hashes
    print(f"[run_job] {name} — param hashes: {all_active_hashes()}")
    RUNNERS[name]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
