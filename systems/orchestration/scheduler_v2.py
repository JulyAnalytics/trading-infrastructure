"""
Scheduler v2 (Phase 6) — replaces the legacy root scheduler.py.

A daemon thread inside the API process ticks once a minute and submits jobs
through the JobManager when their OpsParams time is crossed. Everything the
legacy scheduler lacked lives here:

  - Times come from the registry (OpsParams) and are read LIVE each tick —
    editing a schedule time in the GUI takes effect without a restart.
  - Dependency enforcement: the Sarah vol run is submitted with
    depends_on=<today's marcus_classify> when the regime is stale, so a
    failed Marcus blocks Sarah instead of letting it run on stale regime
    state (the worker refuses jobs whose dependency did not succeed).
  - Catch-up-on-start guard: on startup, anything already due today that has
    not been attempted today is submitted once — and because the jobs table
    is consulted (not in-memory state), a restart never double-runs a job.
  - Retries + failure alerts live in the JobManager (OpsParams-driven).

Weekly cadence: Sunday full FRED refresh (fred_full — the calendar rides
every FRED pull now, so calendar_fetch_time needs no separate job); Friday
weekly review. The jordan_daily_check runs after the vol run so limit
breaches alert daily.

Sub-daily cadence: `sarah_intake_poll` (every `sarah.intake_poll_minutes`,
every day of the week) reads RCS entity_events read-only and enqueues a vol
pull for newly committed option trades. It is a poll, not a job — it does no
vol writes itself, it submits onto the same single job queue.
"""
from __future__ import annotations

import threading
import time
from datetime import date, datetime

from loguru import logger

from systems.orchestration.jobs import MANAGER

_WEEKDAYS = range(0, 5)          # Mon–Fri
_FRIDAY = 4
_SUNDAY = 6


def _due(now: datetime, hhmm: str) -> bool:
    try:
        h, m = (int(x) for x in hhmm.split(":"))
    except ValueError:
        return False
    return (now.hour, now.minute) >= (h, m)


def _attempted_today(name: str, today: date) -> bool:
    """Any job of this name created today (any status, incl. its retries) —
    the double-run guard consults the persisted jobs table, not memory."""
    from systems.orchestration.jobs import list_jobs
    for j in list_jobs(limit=200):
        if j["name"] == name and str(j["created_at"])[:10] == str(today):
            return True
    return False


def _last_success(name: str) -> "dict | None":
    from systems.orchestration.jobs import list_jobs
    for j in list_jobs(limit=200):
        if j["name"] == name and j["status"] == "succeeded":
            return j
    return None


def _regime_age_hours() -> "float | None":
    import json
    from pathlib import Path
    from config import OUTPUTS_DIR
    p = Path(OUTPUTS_DIR) / "regime_state.json"
    if not p.exists():
        return None
    try:
        written = datetime.fromisoformat(json.loads(p.read_text())["written_at"])
        return (datetime.now() - written).total_seconds() / 3600.0
    except Exception:
        return None


class ScheduleLoop:
    def __init__(self):
        self._thread: "threading.Thread | None" = None
        self._stop = threading.Event()
        # Last RCS intake poll (monotonic). In-memory only — the durable
        # position is the trading-side watermark in sarah_intake_watermark,
        # so a restart re-polls harmlessly instead of replaying history.
        self._last_intake_poll: float = 0.0

    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._loop, name="scheduler-v2", daemon=True)
            self._thread.start()
            logger.info("scheduler v2 started")

    def stop(self):
        self._stop.set()

    # ── internals ────────────────────────────────────────────────────────

    def _loop(self):
        while not self._stop.wait(timeout=60):
            try:
                self._tick()
            except Exception as e:   # the loop must survive anything
                logger.exception(f"scheduler tick failed: {e}")

    def _tick(self):
        from systems.params import get_params
        ops = get_params("ops")
        if not getattr(ops, "scheduler_enabled", True):
            return

        now = datetime.now()
        today = now.date()
        wd = now.weekday()

        # RCS trade intake — sub-daily, every day (a trade can be committed on
        # a weekend; the vol pull is screening, not execution). Runs before
        # the time-of-day blocks so an intake enqueued this tick queues ahead
        # of nothing it depends on.
        self._maybe_poll_rcs_intake()

        def fire(name: str, depends_on: "str | None" = None):
            if _attempted_today(name, today):
                return None
            logger.info(f"scheduler: submitting {name}"
                        + (f" (depends_on={depends_on})" if depends_on else ""))
            return MANAGER.submit(name, requested_by="scheduler",
                                  depends_on=depends_on)

        # Weekday evening macro chain: fred → marcus → snapshot
        if wd in _WEEKDAYS and _due(now, ops.daily_pipeline_time):
            fred = fire("fred_incremental")
            fred_id = fred["id"] if fred else None
            marcus = fire("marcus_classify", depends_on=fred_id)
            if wd in _WEEKDAYS and _due(now, ops.snapshot_time):
                fire("snapshot_pdf",
                     depends_on=marcus["id"] if marcus else None)

        # Weekday morning vol chain: sarah (blocks on marcus) → jordan check
        if wd in _WEEKDAYS and _due(now, ops.vol_run_time):
            sarah_dep = None
            age = _regime_age_hours()
            try:
                limit = get_params("sarah").regime_staleness_hours
            except Exception:
                limit = 80.0
            if age is None or age > limit:
                # Regime too old for Sarah's gate — refresh Marcus first and
                # make Sarah's run conditional on that succeeding.
                marcus = fire("marcus_classify")
                sarah_dep = marcus["id"] if marcus else None
            sarah = fire("sarah_daily_vol", depends_on=sarah_dep)
            fire("jordan_daily_check",
                 depends_on=sarah["id"] if sarah else None)

        # Sunday full refresh (calendar rides every FRED pull)
        if wd == _SUNDAY and _due(now, ops.weekly_refresh_time):
            fire("fred_full")

        # Friday weekly review
        if wd == _FRIDAY and _due(now, getattr(ops, "weekly_review_time",
                                               "17:00")):
            fire("weekly_review")

    def _maybe_poll_rcs_intake(self):
        """Steps 1–4 of the trade-intake trigger, on its own sub-daily cadence.

        Failures are logged and swallowed: a journal that is momentarily
        unreadable, or a trading.db held by a running pipeline, must never
        take down the schedule loop. The watermark only advances over events
        actually processed, so a skipped cycle is retried, not lost.
        """
        from systems.params import get_params
        try:
            minutes = float(get_params("sarah").intake_poll_minutes)
        except Exception:
            minutes = 5.0
        if minutes <= 0:
            return
        elapsed = time.monotonic() - self._last_intake_poll
        if elapsed < minutes * 60:
            return
        self._last_intake_poll = time.monotonic()
        try:
            from systems.sarah.trade_intake import poll_activations
            result = poll_activations()
            if result.get("intaken") or result.get("errors"):
                logger.info(f"scheduler: rcs intake poll — {result}")
        except Exception as e:
            logger.warning(f"scheduler: rcs intake poll failed — {e}")


SCHEDULER = ScheduleLoop()
