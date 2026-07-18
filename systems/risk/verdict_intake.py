"""
Research verdict intake — the Priya → Jordan handoff, done defensively.

Closes audit gap G4-7 on the consumer side: a GO verdict is only actionable
if it is fresh AND the regime it was validated under still holds. The intake
never mutates the verdict; it annotates it with pass/fail checks and a
sizing suggestion.
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path


def _load(name: str) -> "dict | None":
    from config import OUTPUTS_DIR
    fp = Path(OUTPUTS_DIR) / name
    if not fp.exists():
        return None
    try:
        return json.loads(fp.read_text())
    except Exception:
        return None


def _age_hours(written_at: str) -> "float | None":
    try:
        return (datetime.now() - datetime.fromisoformat(written_at)
                ).total_seconds() / 3600.0
    except Exception:
        return None


def intake(params=None) -> dict:
    from systems.params import get_params
    p = params or get_params("jordan")

    verdict = _load("research_verdict.json")
    regime = _load("regime_state.json")

    checks: "list[dict]" = []

    def check(name: str, ok: "bool | None", detail: str):
        checks.append({"name": name, "ok": ok, "detail": detail})

    if verdict is None:
        check("verdict_exists", False,
              "research_verdict.json not found — no validated strategy to size")
        return {"actionable": False, "checks": checks, "verdict": None}
    check("verdict_exists", True, f"hypothesis {verdict.get('hypothesis_id')}")

    age = _age_hours(verdict.get("written_at", ""))
    fresh = age is not None and age <= p.verdict_max_age_hours
    check("verdict_fresh", fresh,
          f"{age:.0f}h old (limit {p.verdict_max_age_hours}h)"
          if age is not None else "written_at unparseable")

    is_go = verdict.get("verdict") == "GO"
    check("verdict_go", is_go, f"verdict = {verdict.get('verdict')}")

    viable = bool(verdict.get("viable_after_haircut"))
    check("viable_after_haircut", viable,
          f"haircut Sharpe {verdict.get('production_haircut_sharpe')}")

    regime_ok: "bool | None" = None
    regime_detail = "regime_state.json missing — CLAUDE.md Rule 4 blocks action"
    current_regime = None
    if regime is not None:
        current_regime = regime.get("regime_state")
        rcs_table = verdict.get("regime_conditional_sharpe") or {}
        if verdict.get("regime_at_verdict") and \
                verdict["regime_at_verdict"] != current_regime:
            regime_detail = (
                f"regime shifted since validation: "
                f"{verdict['regime_at_verdict']} → {current_regime}")
            regime_ok = current_regime in rcs_table and \
                (rcs_table.get(current_regime) or 0) > 0
        elif current_regime in rcs_table:
            sr = rcs_table[current_regime]
            regime_ok = (sr or 0) > 0
            regime_detail = (f"strategy Sharpe in current regime "
                             f"({current_regime}): {sr}")
        else:
            regime_ok = None
            regime_detail = (f"no regime-conditional Sharpe for current regime "
                             f"{current_regime} — insufficient observations; "
                             f"treat as unvalidated in this regime")
    check("regime_compatible", regime_ok, regime_detail)

    actionable = bool(fresh and is_go and viable and regime_ok)
    return {
        "actionable": actionable,
        "checks": checks,
        "verdict": verdict,
        "current_regime": current_regime,
        "note": None if actionable else
        "One or more intake checks failed — do not size this strategy.",
    }


def suggest_size(entry: float, stop: float, params=None,
                 risk_pct: "float | None" = None) -> dict:
    """
    Position size = (NAV × risk%) / |entry − stop|  (build-sequence formula).
    """
    from systems.params import get_params
    p = params or get_params("jordan")
    risk_pct = risk_pct if risk_pct is not None else p.default_risk_pct_per_trade
    if entry <= 0 or stop <= 0 or math.isclose(entry, stop):
        raise ValueError("entry and stop must be positive and different")
    risk_dollars = float(p.nav) * float(risk_pct)
    per_unit = abs(entry - stop)
    units = risk_dollars / per_unit
    notional = units * entry
    capped = None
    max_notional = float(p.nav) * p.max_single_position_pct
    if notional > max_notional:
        capped = "single-position limit"
        units = max_notional / entry
        notional = max_notional
    return {
        "nav": p.nav,
        "risk_pct": risk_pct,
        "risk_dollars": round(risk_dollars, 2),
        "entry": entry, "stop": stop,
        "stop_distance": round(per_unit, 4),
        "units": math.floor(units),
        "notional": round(notional, 2),
        "capped_by": capped,
    }
