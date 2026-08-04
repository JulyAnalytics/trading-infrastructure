"""
Child-process job entry point: `python -m systems.orchestration.run_job <name>`.

Runs in a FRESH interpreter so the parameter registry's active versions are
picked up at import time, and so this process is the only DuckDB writer for
the duration of the pipeline. Writes nothing to the jobs table — the parent
JobManager owns job-state persistence.
Per-run arguments arrive as JSON in the JOB_ARGS_JSON environment variable
(set by JobManager when the job was submitted with args). Runners that do not
read it behave exactly as before.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


def _job_args() -> dict:
    raw = os.environ.get("JOB_ARGS_JSON")
    if not raw:
        return {}
    try:
        args = json.loads(raw)
    except ValueError as e:
        print(f"[run_job] ignoring malformed JOB_ARGS_JSON: {e}", file=sys.stderr)
        return {}
    return args if isinstance(args, dict) else {}


def _marcus_classify():
    from systems.signals.regime_classifier import RegimeClassifier
    clf = RegimeClassifier()
    result = clf.classify(persist=True)
    clf.write_output_contract(result)
    print(result)


def _fred_incremental():
    from systems.data_feeds.macro_feed import (
        run_fred_pipeline, compute_derived_series, fetch_cot_data,
        fetch_calendar_data, build_fred_client,
    )
    from systems.utils.db import get_connection
    run_fred_pipeline(full=False)
    compute_derived_series()
    conn = get_connection()
    try:
        fetch_cot_data(conn)
        # macro_calendar feeds the Sarah catalyst resolver (U4.3); it was
        # built in Phase 1 but never scheduled — keep it fresh with each pull.
        fetch_calendar_data(build_fred_client(), conn)
    finally:
        conn.close()


def _sarah_daily_vol():
    """Daily universe by default; an ad-hoc batch when args.tickers is given.

    When the batch came from the RCS trade intake seam, the per-ticker outcome
    is stamped back onto sarah_trade_inputs here — this child process is the
    single trading.db writer for the duration of the job, so recording the
    result is a write that belongs on this side, not in the API process.
    """
    from systems.sarah.daily_vol_run import run_daily_vol
    args = _job_args()
    tickers = args.get("tickers") or None
    result = run_daily_vol(
        tickers=tickers,
        skip_regime_check=bool(args.get("skip_regime_check")),
    )

    if args.get("source") == "rcs_intake":
        _stamp_intake_outcome(args.get("rcs_trade_ulids") or [], result)

    print(f"[sarah_daily_vol] {len(result.get('signals', {}))} ticker(s) OK, "
          f"failures={result.get('failures')}")


def _stamp_intake_outcome(ulids: "list[str]", result: dict) -> None:
    """Clear or set last_error on each intake row this batch was run for.

    A ticker that fails even after the underlier map (delisted, thin,
    yfinance throttle) becomes the blocking item on the intake — the same
    channel as the "which underlier?" prompt — rather than leaving Sarah
    silently empty.
    """
    if not ulids:
        return
    try:
        from systems.sarah.trade_intake import get_trade_inputs, record_error
    except Exception as e:
        print(f"[sarah_daily_vol] intake stamp skipped: {e}", file=sys.stderr)
        return
    failed = {t.upper() for t in (result.get("failures") or [])}
    for ulid in ulids:
        try:
            row = get_trade_inputs(ulid)
            if row is None:
                continue
            ticker = (row.get("ticker") or "").upper()
            if ticker in failed:
                record_error(ulid, (
                    f"no vol data for {ticker} — the options-chain pull failed "
                    f"(delisted, no listed chain, or a yfinance throttle). If "
                    f"{ticker} has no chain at all, map it to an "
                    f"options-liquid underlier in sarah.underlier_map and "
                    f"re-run intake."))
            else:
                record_error(ulid, None)
        except Exception as e:   # never fail the job over a metadata stamp
            print(f"[sarah_daily_vol] intake stamp failed for {ulid}: {e}",
                  file=sys.stderr)


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


def _backfill_vvix_history():
    import runpy
    runpy.run_path("scripts/backfill_vvix_history.py", run_name="__main__")


def _fred_full():
    from systems.data_feeds.macro_feed import (
        run_fred_pipeline, compute_derived_series, fetch_cot_data,
        fetch_calendar_data, build_fred_client,
    )
    from systems.utils.db import get_connection
    run_fred_pipeline(full=True)
    compute_derived_series()
    conn = get_connection()
    try:
        fetch_cot_data(conn)
        fetch_calendar_data(build_fred_client(), conn)
    finally:
        conn.close()


def _jordan_daily_check():
    from systems.orchestration.alerts import raise_alert
    from systems.risk.book import analyze_book
    from systems.risk.limits import evaluate_limits
    analysis = analyze_book()
    limits = evaluate_limits(analysis)
    print(f"positions={analysis['positions_analyzed']} "
          f"net_delta$={analysis['net_delta_dollars']} "
          f"net_vega$={analysis['net_vega_dollars']} ok={limits['ok']}")
    for breach in limits["breaches"]:
        raise_alert("jordan_limits", "error", breach)
    if analysis["errors"]:
        raise_alert("jordan_limits", "warning",
                    f"{len(analysis['errors'])} position(s) could not be "
                    "priced in the daily limit check")


def _weekly_review():
    from systems.reports.weekly_review import generate_weekly_review
    paths = generate_weekly_review()
    print(f"weekly review: {paths}")


RUNNERS = {
    "marcus_classify":         _marcus_classify,
    "fred_incremental":        _fred_incremental,
    "sarah_daily_vol":         _sarah_daily_vol,
    "snapshot_pdf":            _snapshot_pdf,
    "backfill_regime_history": _backfill_regime_history,
    "calibrate_divergence":    _calibrate_divergence,
    "backfill_vvix_history":   _backfill_vvix_history,
    "fred_full":               _fred_full,
    "jordan_daily_check":      _jordan_daily_check,
    "weekly_review":           _weekly_review,
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
