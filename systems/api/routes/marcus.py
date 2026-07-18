"""
Marcus workspace API.

Read endpoints never classify — they serve what the pipeline persisted
(the legacy Dash app's classify-on-page-load behavior is deliberately gone).
POST /preview is the exception: it classifies in-memory under a CANDIDATE
parameter set with persist=False, for the parameter-editor preview.
"""
from __future__ import annotations

import json
from datetime import date, datetime

from fastapi import APIRouter, Body, HTTPException

from systems.api.deps import macro_conn, rows_as_dicts

router = APIRouter(prefix="/api/marcus", tags=["marcus"])

_HISTORY_COLS = (
    "date, regime, composite_score, confidence, "
    "vol_score, credit_score, curve_score, inflation_score, labor_score, "
    "positioning_score, vol_as_of, credit_as_of, curve_as_of, inflation_as_of, "
    "labor_as_of, positioning_as_of, divergence_type, divergence_severity, "
    "vix, hy_spread, yield_curve, breakeven_10y"
)


def _latest_row() -> dict:
    conn = macro_conn()
    try:
        rel = conn.execute(
            f"SELECT {_HISTORY_COLS} FROM regime_history ORDER BY date DESC LIMIT 1"
        )
        rows = rows_as_dicts(rel)
    finally:
        conn.close()
    if not rows:
        raise HTTPException(404, "regime_history is empty — run marcus_classify")
    return rows[0]


def _staleness(row: dict) -> dict:
    from systems.params import get_params
    p = get_params("marcus")
    today = date.today()
    out = {}
    for comp, col in [("vol", "vol_as_of"), ("credit", "credit_as_of"),
                      ("curve", "curve_as_of"), ("inflation", "inflation_as_of"),
                      ("labor", "labor_as_of"), ("positioning", "positioning_as_of")]:
        as_of = row.get(col)
        limit = p.staleness_thresholds_days.get(comp)
        if not as_of:
            out[comp] = {"as_of": None, "age_days": None, "stale": True, "limit": limit}
            continue
        age = (today - date.fromisoformat(str(as_of)[:10])).days
        out[comp] = {"as_of": str(as_of)[:10], "age_days": age,
                     "stale": age > limit, "limit": limit}
    return out


def _result_from_row(row: dict, params=None):
    """Rebuild a RegimeResult from a persisted regime_history row."""
    from systems.signals.regime_classifier import RegimeResult
    divergence = None
    if row.get("divergence_type"):
        divergence = {"type": row["divergence_type"],
                      "severity": row.get("divergence_severity") or "LOW",
                      "label": row["divergence_type"].replace("_", " ").title()}
    return RegimeResult(
        regime=row["regime"],
        composite_score=float(row["composite_score"]),
        confidence=row.get("confidence") or "LOW",
        vol_score=float(row.get("vol_score") or 0),
        credit_score=float(row.get("credit_score") or 0),
        curve_score=float(row.get("curve_score") or 0),
        inflation_score=float(row.get("inflation_score") or 0),
        labor_score=float(row.get("labor_score") or 0),
        positioning_score=float(row.get("positioning_score") or 0),
        divergence=divergence,
        params=params,
    )


def _history_df(days: int):
    import pandas as pd
    conn = macro_conn()
    try:
        df = conn.execute(
            f"""SELECT {_HISTORY_COLS} FROM regime_history
                WHERE date >= current_date - INTERVAL (?) DAY
                ORDER BY date ASC""", [days]
        ).df()
    finally:
        conn.close()
    return df


@router.get("/summary")
def summary() -> dict:
    from config import REGIME_COLORS
    row = _latest_row()
    result = _result_from_row(row)
    history = _history_df(30)
    return {
        "latest": row,
        "regime_color": REGIME_COLORS.get(row["regime"]),
        "staleness": _staleness(row),
        "attribution": result.attribution(),
        "regime_change_probability": result.regime_change_probability(history),
    }


@router.get("/history")
def history(days: int = 252) -> dict:
    df = _history_df(days)
    df["date"] = df["date"].astype(str)
    return {"days": days, "rows": json.loads(df.to_json(orient="records"))}


@router.get("/transitions")
def transitions(limit: int = 12) -> dict:
    conn = macro_conn()
    try:
        rel = conn.execute("""
            WITH ordered AS (
                SELECT date, regime,
                       lag(regime) OVER (ORDER BY date) AS prev_regime
                FROM regime_history
            )
            SELECT date, prev_regime, regime FROM ordered
            WHERE prev_regime IS NOT NULL AND regime != prev_regime
            ORDER BY date DESC LIMIT ?
        """, [limit])
        rows = rows_as_dicts(rel)
    finally:
        conn.close()
    return {"transitions": rows}


@router.get("/calendar")
def calendar(days_ahead: int = 45) -> dict:
    conn = macro_conn()
    try:
        rel = conn.execute("""
            SELECT event_name, event_date, category, importance, component, source
            FROM macro_calendar
            WHERE event_date BETWEEN current_date AND current_date + INTERVAL (?) DAY
            ORDER BY event_date ASC
        """, [days_ahead])
        rows = rows_as_dicts(rel)
    finally:
        conn.close()
    return {"events": rows}


@router.get("/cot")
def cot() -> dict:
    conn = macro_conn()
    try:
        rel = conn.execute("""
            SELECT c.instrument, c.date, c.net_spec, c.net_spec_pct,
                   c.z_score_1y, c.z_score_3y
            FROM cot_positioning c
            JOIN (SELECT instrument, max(date) AS d FROM cot_positioning
                  GROUP BY instrument) m
              ON c.instrument = m.instrument AND c.date = m.d
            ORDER BY c.instrument
        """)
        rows = rows_as_dicts(rel)
    finally:
        conn.close()
    return {"positioning": rows}


@router.get("/returns")
def regime_returns() -> dict:
    conn = macro_conn()
    try:
        try:
            rel = conn.execute("""
                SELECT regime, asset, horizon, median_return, p25_return,
                       p75_return, n_observations
                FROM regime_return_stats ORDER BY regime, asset, horizon
            """)
            rows = rows_as_dicts(rel)
        except Exception:
            rows = []
    finally:
        conn.close()
    return {"stats": rows,
            "note": None if rows else
            "regime_return_stats is empty — run scripts/compute_regime_return_stats.py"}


@router.get("/series/{series_id}")
def series(series_id: str, days: int = 756) -> dict:
    conn = macro_conn()
    try:
        rel = conn.execute("""
            SELECT date, value, z_score_1y FROM macro_series
            WHERE series_id = ? AND date >= current_date - INTERVAL (?) DAY
            ORDER BY date ASC
        """, [series_id, days])
        rows = rows_as_dicts(rel)
    finally:
        conn.close()
    if not rows:
        raise HTTPException(404, f"no data for series '{series_id}'")
    return {"series_id": series_id, "rows": rows}


# ── Plotly figure endpoints (rendered by react-plotly on the client) ─────────

def _base_layout(title: str) -> dict:
    from config import CHART_BASE_LAYOUT
    return {**CHART_BASE_LAYOUT, "title": {"text": title}, "height": 340}


@router.get("/charts/regime-history")
def chart_regime_history(days: int = 504) -> dict:
    from config import REGIME_COLORS
    df = _history_df(days)
    if df.empty:
        raise HTTPException(404, "regime_history is empty")
    dates = df["date"].astype(str).tolist()
    colors = [REGIME_COLORS.get(r, "#888888") for r in df["regime"]]
    return {
        "data": [
            {"type": "scatter", "mode": "lines", "x": dates,
             "y": df["composite_score"].tolist(), "name": "composite",
             "line": {"color": "#e0e0e0", "width": 1.5}},
            {"type": "scatter", "mode": "markers", "x": dates,
             "y": df["composite_score"].tolist(), "name": "regime",
             "marker": {"color": colors, "size": 5},
             "text": df["regime"].tolist(), "hoverinfo": "x+y+text"},
        ],
        "layout": {**_base_layout(f"Composite score — {days}d"),
                   "showlegend": False},
    }


_SERIES_CHARTS = {
    "vix":              ("VIX", "vix"),
    "hy_spread":        ("HY OAS (bps)", "hy_spread"),
    "yield_curve_10_2": ("10Y–2Y (bps)", "yield_curve_10_2"),
    "breakeven_10y":    ("10Y breakeven (%)", "breakeven_10y"),
}


@router.get("/charts/series/{name}")
def chart_series(name: str, days: int = 756) -> dict:
    from systems.params import get_params
    if name not in _SERIES_CHARTS:
        raise HTTPException(404, f"unknown chart '{name}'; valid: {sorted(_SERIES_CHARTS)}")
    title, series_id = _SERIES_CHARTS[name]
    data = series(series_id, days)["rows"]
    fig = {
        "data": [{"type": "scatter", "mode": "lines",
                  "x": [r["date"] for r in data],
                  "y": [r["value"] for r in data],
                  "name": series_id, "line": {"color": "#33b5e5", "width": 1.5}}],
        "layout": {**_base_layout(title), "showlegend": False, "shapes": []},
    }
    thresholds = get_params("marcus").regime_thresholds.get(series_id, {})
    for label, level in thresholds.items():
        fig["layout"]["shapes"].append({
            "type": "line", "xref": "paper", "x0": 0, "x1": 1,
            "y0": level, "y1": level,
            "line": {"color": "#FF8800", "width": 1, "dash": "dot"},
        })
        fig["data"].append({
            "type": "scatter", "mode": "text",
            "x": [data[-1]["date"]], "y": [level],
            "text": [f" {label}"], "textposition": "middle right",
            "textfont": {"size": 10, "color": "#FF8800"},
            "showlegend": False, "hoverinfo": "skip",
        })
    return fig


# ── Marcus 1.0 analytics (Gaps 1, 3, 4, 5) ───────────────────────────────────

def _history_rows(days: int = 3650) -> "list[dict]":
    conn = macro_conn()
    try:
        rel = conn.execute(
            f"""SELECT {_HISTORY_COLS} FROM regime_history
                WHERE date >= current_date - INTERVAL (?) DAY
                ORDER BY date ASC""", [days]
        )
        return rows_as_dicts(rel)
    finally:
        conn.close()


@router.get("/fragility")
def fragility() -> dict:
    from systems.signals.regime_analytics import fragility_assessment
    row = _latest_row()
    result = _result_from_row(row)
    history = _history_df(30)
    prob = result.regime_change_probability(history)
    rows_30d = _history_rows(30)
    return fragility_assessment(row, rows_30d, prob)


@router.get("/state-vector")
def state_vector(k: int = 5) -> dict:
    from systems.params import get_params
    from systems.signals.regime_analytics import (
        build_state_vector, nearest_neighbours, regime_geometry,
    )
    row = _latest_row()
    p = get_params("marcus")
    vector = build_state_vector(row, p)
    analogues = nearest_neighbours(row, _history_rows(), k=k)
    geometry = regime_geometry(row, analogues)
    return {"vector": vector.to_dict(), "geometry": geometry}


@router.get("/implications")
def implications(horizon: str = "1M") -> dict:
    from systems.signals.regime_analytics import (
        implication_summary, nearest_neighbours, regime_geometry,
    )
    row = _latest_row()
    stats = regime_returns()["stats"]
    analogues = nearest_neighbours(row, _history_rows(), k=5)
    geometry = regime_geometry(row, analogues)
    return implication_summary(row["regime"], stats, geometry, horizon=horizon)


@router.get("/interpretations")
def interpretations() -> dict:
    from systems.params import get_params
    from systems.signals.regime_analytics import interpret_components
    row = _latest_row()
    return {"interpretations": interpret_components(row, get_params("marcus")),
            "as_of": str(row["date"])[:10]}


# ── Parameter preview (classify under candidate params, never persisted) ─────

@router.post("/preview")
def preview(body: dict = Body(...)) -> dict:
    """
    Body: {"payload": {<MarcusParams field overrides>}}
    Classifies TODAY's snapshot under the candidate parameters, persist=False,
    and returns both current-active and candidate results for diffing.
    """
    from systems.params import MarcusParams, get_params
    from systems.signals.regime_classifier import RegimeClassifier

    overrides = body.get("payload") or {}
    merged = {**get_params("marcus").to_dict(), **overrides}
    candidate = MarcusParams.from_dict(merged)
    problems = candidate.validate()
    if problems:
        raise HTTPException(422, "; ".join(problems))

    def run(params) -> dict:
        clf = RegimeClassifier(params=params)
        try:
            r = clf.classify(persist=False)
        finally:
            clf.conn.close()
        return {
            "regime": r.regime, "composite_score": r.composite_score,
            "confidence": r.confidence,
            "scores": {"vol": r.vol_score, "credit": r.credit_score,
                       "curve": r.curve_score, "inflation": r.inflation_score,
                       "labor": r.labor_score, "positioning": r.positioning_score},
            "divergence": r.divergence,
        }

    active = run(None)   # None -> classifier binds current active params
    cand = run(candidate)
    return {
        "active": active,
        "candidate": cand,
        "changed": {k: {"from": active[k], "to": cand[k]}
                    for k in ("regime", "composite_score", "confidence")
                    if active[k] != cand[k]},
        "generated_at": datetime.now().isoformat(),
    }
