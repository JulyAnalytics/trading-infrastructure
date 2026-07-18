"""Shared context — output contracts and their freshness."""
from __future__ import annotations

import json
from datetime import datetime
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


@router.get("/regime")
def regime() -> dict:
    from systems.params import get_params
    data = _load_output("regime_state.json")
    age = _age_hours(data.get("written_at", ""))
    limit = get_params("ops").regime_staleness_hours_production
    return {
        **data,
        "age_hours": age,
        "staleness_limit_hours": limit,
        "stale": (age is None) or (age > limit),
    }


@router.get("/vol-signals")
def vol_signals() -> dict:
    return _load_output("vol_signals.json")


@router.get("/research-verdict")
def research_verdict() -> dict:
    data = _load_output("research_verdict.json")
    return {**data, "age_hours": _age_hours(data.get("written_at", ""))}
