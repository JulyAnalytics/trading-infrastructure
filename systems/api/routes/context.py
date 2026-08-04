"""Shared context — output contracts and their freshness."""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, HTTPException

from systems.api.deps import REPO_ROOT

router = APIRouter(prefix="/api/context", tags=["context"])


def _load_output(name: str) -> dict:
    from config import OUTPUTS_DIR
    path = Path(OUTPUTS_DIR)
    path = path if path.is_absolute() else REPO_ROOT / path
    fp = path / name
    if not fp.exists():
        raise HTTPException(404, f"{name} not found — has its pipeline run?")
    return json.loads(fp.read_text())


def _age_hours(written_at: str) -> "float | None":
    try:
        return round(
            (datetime.now() - datetime.fromisoformat(written_at)).total_seconds() / 3600.0,
            2,
        )
    except Exception:
        return None


def _regime_is_stale(now: datetime, written_at: str, pipeline_time: str) -> bool:
    """
    Weekend/weekly-cycle aware staleness for regime_state.json.

    A regime written by the previous scheduled evening run is the *correct*
    signal until the next run lands — Friday's 18:05 regime carries through
    the weekend and Monday morning by design (Sarah's 80h gate exists for
    exactly that carryover). The tight production limit only bites once a
    scheduled run time has passed without producing a fresh regime.
    """
    if not written_at:
        return True
    try:
        written = datetime.fromisoformat(written_at)
    except Exception:
        return True
    try:
        hh, mm = (int(x) for x in pipeline_time.split(":"))
    except Exception:
        hh, mm = 18, 5
    # Most recent scheduled daily-run instant at-or-before `now` (weekdays only).
    expected = now.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if now < expected or now.weekday() >= 5:
        expected -= timedelta(days=1)
        while expected.weekday() >= 5:
            expected -= timedelta(days=1)
    # Grace window for the fred → marcus chain to land after the scheduled time.
    if now < expected + timedelta(minutes=45):
        return False
    # A refresh was due at `expected`; stale iff the regime predates it
    # (10-min epsilon for clock drift / schedule edits).
    return written < expected - timedelta(minutes=10)


@router.get("/regime")
def regime() -> dict:
    from systems.params import get_params
    data = _load_output("regime_state.json")
    age = _age_hours(data.get("written_at", ""))
    ops = get_params("ops")
    limit = ops.regime_staleness_hours_production
    return {
        **data,
        "age_hours": age,
        "staleness_limit_hours": limit,
        "stale": _regime_is_stale(datetime.now(),
                                  data.get("written_at", ""),
                                  ops.daily_pipeline_time),
    }


@router.get("/vol-signals")
def vol_signals() -> dict:
    return _load_output("vol_signals.json")


@router.get("/research-verdict")
def research_verdict() -> dict:
    data = _load_output("research_verdict.json")
    return {**data, "age_hours": _age_hours(data.get("written_at", ""))}
