"""
Sarah workspace API — vol monitor (persisted signals), greeks tool, scenario
lab. The memo builder and regime library land with the Phase 3 data
completions; endpoints here only use validated persisted outputs plus the
two compute engines.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException

from systems.api.deps import trading_conn, rows_as_dicts

router = APIRouter(prefix="/api/sarah", tags=["sarah"])

_SIGNAL_COLS = (
    "ticker, date, spot_price, forward_price, atm_iv_30d, iv_rank, "
    "iv_percentile, ivr_ivp_confidence, skew_25d_rr, skew_1025_ratio, "
    "ts_iv_30d, ts_iv_60d, ts_iv_180d, ts_front_slope, ts_back_slope, "
    "ts_shape, rv_21d, vrp_proxy_bkwd, vrp_proxy_signal, macro_regime, "
    "term_structure_json"
)


@router.get("/signals")
def latest_signals() -> dict:
    conn = trading_conn()
    try:
        rel = conn.execute(f"""
            SELECT {_SIGNAL_COLS}
            FROM vol_signals v
            JOIN (SELECT ticker AS t, max(date) AS d FROM vol_signals
                  GROUP BY ticker) m
              ON v.ticker = m.t AND v.date = m.d
            ORDER BY v.ticker
        """)
        rows = rows_as_dicts(rel)
    finally:
        conn.close()
    if not rows:
        raise HTTPException(404, "vol_signals is empty — run the Sarah daily job")
    return {"signals": rows}


@router.get("/signals/{ticker}/history")
def signal_history(ticker: str, days: int = 252) -> dict:
    conn = trading_conn()
    try:
        rel = conn.execute("""
            SELECT date, atm_iv_30d, rv_21d, vrp_proxy_bkwd, iv_rank,
                   skew_25d_rr, ts_front_slope
            FROM vol_signals
            WHERE ticker = ? AND date >= current_date - INTERVAL (?) DAY
            ORDER BY date ASC
        """, [ticker.upper(), days])
        rows = rows_as_dicts(rel)
    finally:
        conn.close()
    if not rows:
        raise HTTPException(404, f"no vol_signals history for {ticker}")
    return {"ticker": ticker.upper(), "rows": rows}


def _base_layout(title: str) -> dict:
    from config import CHART_BASE_LAYOUT
    return {**CHART_BASE_LAYOUT, "title": {"text": title}, "height": 320}


@router.get("/charts/iv-history/{ticker}")
def chart_iv_history(ticker: str, days: int = 252) -> dict:
    rows = signal_history(ticker, days)["rows"]
    x = [r["date"] for r in rows]
    return {
        "data": [
            {"type": "scatter", "mode": "lines", "x": x, "name": "ATM IV 30d",
             "y": [r["atm_iv_30d"] for r in rows],
             "line": {"color": "#33b5e5", "width": 1.6}},
            {"type": "scatter", "mode": "lines", "x": x, "name": "RV 21d",
             "y": [r["rv_21d"] for r in rows],
             "line": {"color": "#ffbb33", "width": 1.2, "dash": "dot"}},
        ],
        "layout": {**_base_layout(f"{ticker.upper()} — IV vs RV (vol pts)"),
                   "legend": {"orientation": "h"}},
    }


@router.get("/charts/term-structure/{ticker}")
def chart_term_structure(ticker: str) -> dict:
    conn = trading_conn()
    try:
        row = conn.execute("""
            SELECT date, term_structure_json, ts_shape FROM vol_signals
            WHERE ticker = ? ORDER BY date DESC LIMIT 1
        """, [ticker.upper()]).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, f"no vol_signals for {ticker}")
    date_s, ts_json, shape = str(row[0])[:10], row[1], row[2]
    try:
        ts = json.loads(ts_json) if ts_json else {}
    except Exception:
        ts = {}
    pairs = sorted(((int(k), float(v)) for k, v in ts.items()
                    if v is not None), key=lambda p: p[0])
    if not pairs:
        raise HTTPException(404, f"term_structure_json empty for {ticker}")
    return {
        "data": [{"type": "scatter", "mode": "lines+markers",
                  "x": [p[0] for p in pairs], "y": [p[1] for p in pairs],
                  "line": {"color": "#00c851", "width": 2},
                  "name": "ATM IV"}],
        "layout": {**_base_layout(
            f"{ticker.upper()} term structure — {shape} ({date_s})"),
            "xaxis": {"title": {"text": "DTE"}},
            "yaxis": {"title": {"text": "ATM IV (vol pts)"}},
            "showlegend": False},
    }


# ── Greeks tool (live data — yfinance, delayed) ──────────────────────────────

@router.post("/greeks")
def greeks(body: dict = Body(...)) -> dict:
    from systems.sarah.greeks_tool import GreeksTool
    required = ("ticker", "flag", "strike", "expiration", "quantity", "long_short")
    missing = [f for f in required if not body.get(f)]
    if missing:
        raise HTTPException(422, f"missing fields: {missing}")
    try:
        return GreeksTool().analyze_position(
            ticker=str(body["ticker"]).upper(), flag=body["flag"],
            strike=float(body["strike"]), expiration=body["expiration"],
            quantity=int(body["quantity"]), long_short=body["long_short"],
        )
    except ValueError as e:
        raise HTTPException(422, str(e))


# ── Scenario lab ─────────────────────────────────────────────────────────────

@router.post("/scenario")
def scenario(body: dict = Body(...)) -> dict:
    """
    Body: {"position": <output of POST /greeks>, "checkpoint": 0.0,
           "spot_vix": optional}
    Returns a P&L heatmap figure for the checkpoint + all stress scenarios +
    the kill scenario, all under the ACTIVE Sarah parameters.
    """
    from systems.sarah.scenario_engine import ScenarioEngine
    position = body.get("position")
    if not position or "market" not in position or "position" not in position:
        raise HTTPException(422, "body.position must be a /greeks result")
    eng = ScenarioEngine()

    grid = eng.scenario_pnl_grid(position, spot_vix=body.get("spot_vix"))
    checkpoints = list(grid["grids"].keys())
    cp = body.get("checkpoint", checkpoints[0])
    if cp not in grid["grids"]:
        cp = checkpoints[0]
    df = grid["grids"][cp]

    heatmap = {
        "data": [{
            "type": "heatmap",
            "z": [[None if v != v else round(float(v), 2) for v in row]
                  for row in df.values],
            "y": [float(i) for i in df.index],
            "x": [float(c) for c in df.columns],
            "colorscale": "RdBu", "zmid": 0,
            "colorbar": {"title": {"text": "P&L $"}},
        }],
        "layout": {
            **_base_layout(
                f"P&L grid — {int(float(cp) * 100)}% of DTE elapsed"
                + (" (HIGH-VOL grid)" if grid["high_vol_mode"] else "")),
            "height": 420,
            "xaxis": {"title": {"text": "IV shift (vol pts)"}},
            "yaxis": {"title": {"text": "Spot move (%)"}},
        },
    }

    stress = {}
    for key in eng.stress_scenario_library():
        try:
            stress[key] = eng.stress_scenario_pnl(position, key)
        except Exception as e:
            stress[key] = {"error": str(e)}

    return {
        "checkpoints": [float(c) for c in checkpoints],
        "checkpoint": float(cp),
        "grid_fig": heatmap,
        "grid_params": grid["grid_params"],
        "bs_limitation": grid["bs_limitation"],
        "stress": stress,
        "kill": eng.kill_scenario(position),
    }
