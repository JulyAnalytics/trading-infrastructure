"""
Sarah workspace API — the five Phase 3 tools:
  vol monitor (signals + surface heatmap + vol cones), greeks tool,
  scenario lab, pre-trade memo builder (persisted to pretrade_memos),
  regime library (analog search, pre-transition monitor, event browser).

Read endpoints stay strictly read-only (deps.open_readonly); the two write
paths (memo persistence, event YAML) are small metadata writes on POST/PUT,
same pattern as the Jordan book.
"""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException

from systems.api.deps import macro_conn, trading_conn, rows_as_dicts

router = APIRouter(prefix="/api/sarah", tags=["sarah"])


def _py(v):
    """numpy scalar → native Python (FastAPI/pydantic can't serialize numpy)."""
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v != v:   # NaN → null
        return None
    return v

_SIGNAL_COLS = (
    "ticker, date, spot_price, forward_price, atm_iv_30d, iv_rank, "
    "iv_percentile, ivr_ivp_confidence, skew_25d_rr, skew_1025_ratio, "
    "ts_iv_30d, ts_iv_60d, ts_iv_180d, ts_front_slope, ts_back_slope, "
    "ts_shape, rv_21d, vrp_proxy_bkwd, vrp_proxy_signal, macro_regime, "
    "next_earnings_date, data_source, term_structure_json"
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
    rows = _signal_history_rows(ticker, days)
    if not rows:
        raise HTTPException(404, f"no vol_signals history for {ticker}")
    return {"ticker": ticker.upper(), "rows": rows}


def _signal_history_rows(ticker: str, days: int = 252) -> list[dict]:
    """Raw row fetch backing signal_history() and the IV-history-compare chart.
    Returns [] (not 404) so callers can compose many tickers without raising."""
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
    return rows


def _base_layout(title: str) -> dict:
    from config import CHART_BASE_LAYOUT
    return {**CHART_BASE_LAYOUT, "title": {"text": title}, "height": 320}


# ── Batch compare ────────────────────────────────────────────────────────────
# Four read-only endpoints that screen N tickers side-by-side. All are pure
# trading.db reads — no yfinance, no network. The batch run itself goes through
# the job queue (POST /api/jobs {name:"sarah_daily_vol", args:{tickers:[...]}});
# these endpoints read whatever the run persisted.
#
# ticker parsing is shared: comma/space/newline separated, uppercased, deduped.

_COMPARE_RANK_FIELDS = (
    "iv_rank", "vrp_proxy_bkwd", "skew_25d_rr", "atm_iv_30d", "ts_front_slope",
    "rv_21d",
)
# Distinct colours for up to ~12 overlaid tickers (matches the Sarah palette).
_COMPARE_PALETTE = [
    "#33b5e5", "#ffbb33", "#00c851", "#ff5252", "#aa66cc", "#00bcd4",
    "#ff8800", "#69f0ae", "#e040fb", "#ffd54f", "#40c4ff", "#eeff41",
]


def _parse_ticker_list(raw: str, *, limit: int = 30) -> list[str]:
    """Normalise a comma/space/newline ticker string into a deduped upper list."""
    seen, out = set(), []
    for tok in str(raw).replace(",", " ").split():
        t = tok.strip().upper()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
        if len(out) >= limit:
            break
    return out


@router.get("/compare")
def compare(tickers: str) -> dict:
    """Latest vol_signals row per requested ticker + per-dimension rankings.

    ?tickers=AMD,PLTR,PFE  (comma / space / newline separated; capped at 30)
    → {as_of, rows:[{..._SIGNAL_COLS, iv_rv_spread}], rankings:{field:[tkr,...]}}
    """
    tkrs = _parse_ticker_list(tickers)
    if not tkrs:
        raise HTTPException(422, "tickers query param is empty")
    placeholders = ",".join("?" * len(tkrs))
    conn = trading_conn()
    try:
        rel = conn.execute(f"""
            SELECT {_SIGNAL_COLS} FROM vol_signals v
            JOIN (SELECT ticker AS t, max(date) AS d FROM vol_signals
                  WHERE ticker IN ({placeholders})
                  GROUP BY ticker) m
              ON v.ticker = m.t AND v.date = m.d
            ORDER BY v.ticker
        """, tkrs)
        rows = rows_as_dicts(rel)
    finally:
        conn.close()
    if not rows:
        raise HTTPException(404, f"no vol_signals for {','.join(tkrs)}")

    # Derived: vol premium = IV − RV (fall back to vrp_proxy_bkwd if rv absent).
    for r in rows:
        r["iv_rv_spread"] = _py(r.get("vrp_proxy_bkwd"))
        try:
            iv = float(r.get("atm_iv_30d")) if r.get("atm_iv_30d") is not None else None
            rv = float(r.get("rv_21d")) if r.get("rv_21d") is not None else None
            if iv is not None and rv is not None:
                r["iv_rv_spread"] = _py(round(iv - rv, 4))
        except (TypeError, ValueError):
            pass

    # Rankings: per numeric field, tickers sorted desc with nulls last.
    # Higher = the dimension's "most" (highest IV rank, richest VRP, etc.).
    rankings: dict[str, list[str]] = {}
    for field in _COMPARE_RANK_FIELDS:
        ranked = sorted(
            rows,
            key=lambda r: (r.get(field) is not None, r.get(field) or float("-inf")),
            reverse=True,
        )
        rankings[field] = [r["ticker"] for r in ranked if r.get(field) is not None]

    return {"as_of": rows[0]["date"], "rows": rows, "rankings": rankings}


@router.get("/charts/term-structure-compare")
def chart_term_structure_compare(tickers: str) -> dict:
    """One ATM-IV-vs-DTE trace per ticker, overlaid. Parses each row's
    term_structure_json (the {dte: atm_iv} dict from build_term_structure)."""
    tkrs = _parse_ticker_list(tickers)
    if not tkrs:
        raise HTTPException(422, "tickers query param is empty")
    placeholders = ",".join("?" * len(tkrs))
    conn = trading_conn()
    try:
        rows = conn.execute(f"""
            SELECT ticker, term_structure_json FROM vol_signals v
            JOIN (SELECT ticker AS t, max(date) AS d FROM vol_signals
                  WHERE ticker IN ({placeholders}) GROUP BY ticker) m
              ON v.ticker = m.t AND v.date = m.d
            ORDER BY v.ticker
        """, tkrs).fetchall()
    finally:
        conn.close()
    if not rows:
        raise HTTPException(404, f"no vol_signals for {','.join(tkrs)}")
    traces = []
    for i, (tkr, ts_json) in enumerate(rows):
        try:
            ts = json.loads(ts_json) if ts_json else {}
        except Exception:
            ts = {}
        pairs = sorted(((int(k), float(v)) for k, v in ts.items()
                        if v is not None), key=lambda p: p[0])
        if not pairs:
            continue
        traces.append({
            "type": "scatter", "mode": "lines+markers",
            "x": [p[0] for p in pairs], "y": [p[1] for p in pairs],
            "name": tkr,
            "line": {"color": _COMPARE_PALETTE[i % len(_COMPARE_PALETTE)], "width": 2},
        })
    if not traces:
        raise HTTPException(404, "term_structure_json empty for all requested tickers")
    return {
        "data": traces,
        "layout": {**_base_layout("Term structure overlay — ATM IV by DTE"),
                   "xaxis": {"title": {"text": "DTE"}},
                   "yaxis": {"title": {"text": "ATM IV (vol pts)"}},
                   "legend": {"orientation": "h"},
                   "height": 420},
    }


@router.get("/charts/iv-history-compare")
def chart_iv_history_compare(tickers: str, days: int = 126) -> dict:
    """One ATM-IV-30d line per ticker over the trailing `days`, overlaid."""
    tkrs = _parse_ticker_list(tickers)
    if not tkrs:
        raise HTTPException(422, "tickers query param is empty")
    traces = []
    for i, tkr in enumerate(tkrs):
        rows = _signal_history_rows(tkr, days)
        if not rows:
            continue
        traces.append({
            "type": "scatter", "mode": "lines",
            "x": [r["date"] for r in rows],
            "y": [r["atm_iv_30d"] for r in rows],
            "name": tkr,
            "line": {"color": _COMPARE_PALETTE[i % len(_COMPARE_PALETTE)], "width": 1.8},
        })
    if not traces:
        raise HTTPException(404, f"no vol_signals history for {','.join(tkrs)}")
    return {
        "data": traces,
        "layout": {**_base_layout(f"ATM IV 30d — trailing {days}d"),
                   "yaxis": {"title": {"text": "ATM IV (vol pts)"}},
                   "legend": {"orientation": "h"},
                   "height": 420},
    }


@router.get("/charts/scatter-vol-map")
def chart_scatter_vol_map(tickers: str) -> dict:
    """One bubble per ticker: x=IV rank, y=VRP spread (IV−RV), size∝ATM IV.
    Quadrant lines at x=50, y=0 frame the cheap-vol vs rich-vol reading."""
    cmp = compare(tickers)
    rows = [r for r in cmp["rows"]
            if r.get("iv_rank") is not None and r.get("iv_rv_spread") is not None]
    if not rows:
        raise HTTPException(404, "no tickers with both iv_rank and iv_rv_spread")
    # Bubble size: scale ATM IV into a ~8–40 px range for readability.
    ivs = [float(r["atm_iv_30d"]) for r in rows if r.get("atm_iv_30d") is not None]
    iv_min, iv_max = (min(ivs), max(ivs)) if ivs else (0.0, 1.0)
    span = max(iv_max - iv_min, 1.0)
    sizes = []
    for r in rows:
        iv = r.get("atm_iv_30d")
        s = 8 + 32 * ((float(iv) - iv_min) / span) if iv is not None else 12.0
        sizes.append(max(s, 8.0))
    traces = [{
        "type": "scatter", "mode": "markers",
        "x": [float(r["iv_rank"]) for r in rows],
        "y": [float(r["iv_rv_spread"]) for r in rows],
        "text": [r["ticker"] for r in rows],
        "marker": {"size": sizes, "sizemode": "area",
                   "color": [_COMPARE_PALETTE[i % len(_COMPARE_PALETTE)]
                             for i in range(len(rows))],
                   "opacity": 0.78, "line": {"width": 1, "color": "#ffffff33"}},
        "hovertemplate": ("<b>%{text}</b><br>IV rank: %{x:.1f}<br>"
                          "VRP spread: %{y:.1f} vpts<extra></extra>"),
        "showlegend": False,
    }]
    shapes = [
        {"type": "line", "x0": 50, "x1": 50, "y0": 0, "y1": 1,
         "yref": "paper", "line": {"color": "#888", "width": 1, "dash": "dot"}},
        {"type": "line", "x0": 0, "x1": 1, "y0": 0, "y1": 0,
         "xref": "paper", "line": {"color": "#888", "width": 1, "dash": "dot"}},
    ]
    return {
        "data": traces,
        "layout": {**_base_layout("Vol opportunity map — IV rank vs VRP spread"),
                   "xaxis": {"title": {"text": "IV rank (0–100)"},
                             "range": [-2, 102]},
                   "yaxis": {"title": {"text": "IV − RV (vol pts)"}},
                   "shapes": shapes,
                   "height": 460},
    }


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


@router.get("/charts/surface/{ticker}")
def chart_surface(ticker: str) -> dict:
    """
    IV surface heatmap (strike × DTE) from the vol_surface table, latest date.
    OTM composite: puts below the forward, calls above (log_moneyness sign).
    """
    conn = trading_conn()
    try:
        row = conn.execute(
            "SELECT max(date) FROM vol_surface WHERE ticker = ?",
            [ticker.upper()]).fetchone()
        if not row or row[0] is None:
            raise HTTPException(
                404, f"no vol_surface rows for {ticker} — run the Sarah daily job")
        date_s = str(row[0])[:10]
        rows = conn.execute("""
            SELECT dte, strike, iv FROM vol_surface
            WHERE ticker = ? AND date = ?
              AND ((option_type = 'put' AND log_moneyness < 0)
                   OR (option_type = 'call' AND log_moneyness >= 0))
              AND log_moneyness BETWEEN -0.35 AND 0.25
            ORDER BY dte, strike
        """, [ticker.upper(), date_s]).fetchall()
    finally:
        conn.close()
    if not rows:
        raise HTTPException(404, f"vol_surface empty for {ticker} on {date_s}")

    dtes = sorted({r[0] for r in rows})
    strikes = sorted({r[1] for r in rows})
    iv_map = {(r[0], r[1]): r[2] for r in rows}
    z = [[iv_map.get((d, k)) for d in dtes] for k in strikes]

    return {
        "data": [{
            "type": "heatmap", "x": dtes, "y": strikes, "z": z,
            "colorscale": "Viridis", "connectgaps": True,
            "colorbar": {"title": {"text": "IV (vpts)"}},
            "hovertemplate": "DTE %{x} · K %{y}<br>IV %{z:.1f}<extra></extra>",
        }],
        "layout": {**_base_layout(
            f"{ticker.upper()} — IV surface (OTM composite, {date_s})"),
            "height": 420,
            "xaxis": {"title": {"text": "DTE"}},
            "yaxis": {"title": {"text": "Strike"}}},
        "n_points": len(rows),
    }


@router.get("/charts/vol-cone/{ticker}")
def chart_vol_cone(ticker: str, days: int = 500) -> dict:
    """
    U1.1 — realized-vol cone (VolCone, Hodges-Tompkins corrected) with the
    current ATM IV 30d overlaid for the buy/sell-vol context Sinclair
    describes. Price history via yfinance (research-grade, delayed).
    """
    import pandas as pd
    from systems.backtest.vol_estimators import VolCone

    try:
        import yfinance as yf
        hist = yf.Ticker(ticker.upper()).history(period=f"{days}d")
        close = hist["Close"]
    except Exception as e:
        raise HTTPException(502, f"price history fetch failed: {e}")
    if close is None or len(close) < 130:
        raise HTTPException(
            502, f"insufficient price history for {ticker} ({0 if close is None else len(close)}d)")

    cone = VolCone.compute(close)
    if cone.empty:
        raise HTTPException(500, "vol cone computation returned no rows")
    cone = cone.sort_values("window")
    x = [int(w) for w in cone["window"]]
    vp = lambda col: [round(float(v) * 100.0, 2) for v in cone[col]]  # noqa: E731

    atm_iv = None
    conn = trading_conn()
    try:
        r = conn.execute(
            "SELECT atm_iv_30d FROM vol_signals WHERE ticker = ? "
            "ORDER BY date DESC LIMIT 1", [ticker.upper()]).fetchone()
        atm_iv = float(r[0]) if r and r[0] is not None else None
    finally:
        conn.close()

    data = [
        {"type": "scatter", "x": x, "y": vp("p95"), "name": "p95",
         "mode": "lines", "line": {"color": "#666", "width": 1, "dash": "dot"}},
        {"type": "scatter", "x": x, "y": vp("p75"), "name": "p75", "mode": "lines",
         "line": {"color": "#888", "width": 1}, "fill": "tonexty",
         "fillcolor": "rgba(120,120,160,0.15)"},
        {"type": "scatter", "x": x, "y": vp("p50"), "name": "median", "mode": "lines",
         "line": {"color": "#33b5e5", "width": 2}, "fill": "tonexty",
         "fillcolor": "rgba(51,181,229,0.15)"},
        {"type": "scatter", "x": x, "y": vp("p25"), "name": "p25", "mode": "lines",
         "line": {"color": "#888", "width": 1}, "fill": "tonexty",
         "fillcolor": "rgba(51,181,229,0.15)"},
        {"type": "scatter", "x": x, "y": vp("p5"), "name": "p5", "mode": "lines",
         "line": {"color": "#666", "width": 1, "dash": "dot"}, "fill": "tonexty",
         "fillcolor": "rgba(120,120,160,0.15)"},
        {"type": "scatter", "x": x, "y": vp("current"), "name": "current RV",
         "mode": "lines+markers", "line": {"color": "#ffbb33", "width": 2.2}},
    ]
    if atm_iv is not None:
        data.append({"type": "scatter", "x": [21], "y": [round(atm_iv, 2)],
                     "name": "ATM IV 30d", "mode": "markers",
                     "marker": {"color": "#ff4444", "size": 11, "symbol": "diamond"}})

    return {
        "data": data,
        "layout": {**_base_layout(
            f"{ticker.upper()} — realized vol cone ({len(close)}d history)"),
            "height": 380,
            "xaxis": {"title": {"text": "window (days)"}},
            "yaxis": {"title": {"text": "annualized vol (vpts)"}},
            "legend": {"orientation": "h"}},
        "table": cone.round(4).to_dict(orient="records"),
        "note": ("Hodges-Tompkins overlap-corrected realized vol percentiles. "
                 "Red diamond = current ATM IV 30d (implied vs realized cone)."),
    }


# ── Catalyst calendar (U4.3) ─────────────────────────────────────────────────

@router.get("/catalysts/{ticker}")
def catalysts(ticker: str) -> dict:
    from systems.sarah.catalyst_calendar import resolve_catalyst
    conn = macro_conn()
    try:
        return resolve_catalyst(ticker.upper(), macro_conn=conn)
    finally:
        conn.close()


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


# ── Pre-trade memo builder (Stage 4 GUI) ─────────────────────────────────────

@router.post("/memo")
def build_memo(body: dict = Body(...)) -> dict:
    """
    Body: {ticker, expected_move, thesis_days, catalyst_type, max_loss_budget,
           expected_move_sign?, flow?: {FlowObservation fields},
           rcs_trade_ulid?}
    Builds the full 5-panel dashboard + BL density + structure comparison,
    persists it to pretrade_memos with a stable ID, returns the memo.

    With rcs_trade_ulid, every field except expected_move is loaded from the
    trade's stored intake row, and the memo is persisted carrying that ULID —
    the citation key back to the RCS trade.
    """
    from systems.sarah.pretrade_dashboard import (
        FlowObservation, TradeThesisInput, run_pretrade_dashboard,
    )
    from systems.sarah.trade_intake import (
        get_trade_inputs, validate_expected_move,
    )

    ulid = body.get("rcs_trade_ulid") or None
    stored: dict = {}
    if ulid:
        stored = get_trade_inputs(ulid) or {}
        if not stored:
            raise HTTPException(
                404, f"no intake row for trade {ulid} — POST /api/sarah/intake "
                     "first")

    def value(field: str):
        v = body.get(field)
        return stored.get(field) if v in (None, "") else v

    ticker = value("ticker")
    fields = {f: value(f) for f in
              ("expected_move", "thesis_days", "catalyst_type",
               "max_loss_budget")}
    missing = ([] if ticker else ["ticker"]) + \
              [f for f, v in fields.items() if v in (None, "")]
    if missing:
        raise HTTPException(422, f"missing fields: {missing}")

    try:
        # Unsigned DECIMAL FRACTION (0.20 = ±20%), and non-zero. Both bounds
        # exist because a browser sends Number("") === 0 for an empty numeric
        # field, and a 0 would otherwise render a complete-looking memo built
        # on a degenerate ±0% forecast.
        expected_move = validate_expected_move(fields["expected_move"])
    except ValueError as e:
        raise HTTPException(422, str(e))

    # Same empty-field trap: 0 is a *present* value to the check above, but
    # neither of these is meaningful at zero. thesis_days=0 picks an arbitrary
    # expiration; max_loss_budget=0 marks every candidate structure
    # "over budget", which reads as a finding rather than as missing input.
    for name, minimum in (("thesis_days", 1), ("max_loss_budget", 0.01)):
        try:
            if float(fields[name]) < minimum:
                raise HTTPException(
                    422, f"{name}={fields[name]} — must be at least {minimum}. "
                         f"(An empty numeric field arrives as 0; enter a value.)")
        except (TypeError, ValueError):
            raise HTTPException(422, f"{name} must be a number, got "
                                     f"{fields[name]!r}")

    flow_payload = body.get("flow") or stored.get("flow")

    try:
        thesis = TradeThesisInput(
            ticker=str(ticker).upper(),
            expected_move=expected_move,
            thesis_days=int(fields["thesis_days"]),
            catalyst_type=fields["catalyst_type"],
            max_loss_budget=float(fields["max_loss_budget"]),
            expected_move_sign=(int(value("expected_move_sign"))
                                if value("expected_move_sign") else None),
        )
        flow = None
        if flow_payload:
            f = flow_payload
            flow = FlowObservation(
                ticker=thesis.ticker,
                observation_date=f.get("observation_date")
                or __import__("datetime").date.today().isoformat(),
                flow_type=f["flow_type"],
                execution_type=f.get("execution_type", "unknown"),
                size_contracts=int(f.get("size_contracts", 0)),
                expiration_dte=int(f.get("expiration_dte", 0)),
                strike_delta_approx=float(f.get("strike_delta_approx", 0.0)),
                vs_avg_volume=f.get("vs_avg_volume", "avg"),
                notes=f.get("notes", ""),
            )
        return run_pretrade_dashboard(thesis, flow, rcs_trade_ulid=ulid)
    except (AssertionError, ValueError, KeyError) as e:
        raise HTTPException(422, str(e))


# ── RCS trade intake (Sarah ← RCS seam) ──────────────────────────────────────

def _intake_view(row: dict) -> dict:
    """Stored intake row + everything the UI needs to render only the fields
    that actually still block a memo."""
    from systems.sarah.trade_intake import (
        has_vol_data, implied_move_reference, needs_user,
    )
    ticker = row.get("ticker")
    return {
        **{k: v for k, v in row.items() if k != "flow_json"},
        "flow": row.get("flow"),
        "needs_user": needs_user(row),
        "has_vol_data": has_vol_data(ticker) if ticker else False,
        # Shown BESIDE the expected_move field as reference — never as its
        # default. Pre-filling the implied move would collapse the user's
        # independent forecast onto the market's, defeating the
        # belief-vs-implied comparison the memo exists to make.
        "implied_move_reference": implied_move_reference(
            ticker, row.get("thesis_days")) if ticker else None,
    }


@router.get("/rcs-trades")
def search_rcs_trades(q: "str | None" = None, status: str = "idea,active",
                      limit: int = 50) -> dict:
    """
    Search RCS trades by ticker, name, or ULID — read-only.

    ULIDs are not memorable, so this is how you reach a trade without one.
    Each row carries `leg_count` (whether the position surfaces will have
    anything to price) and `intaken` (whether Sarah already tracks it, so the
    UI can offer "Re-pull" instead of "Analyse").
    """
    from systems.risk import rcs_bridge
    from systems.sarah.trade_intake import get_trade_inputs, resolve_ticker

    if not rcs_bridge.available():
        raise HTTPException(503, "RCS journal not reachable")
    statuses = tuple(s.strip() for s in status.split(",") if s.strip())
    rows = rcs_bridge.list_trades(q, statuses=statuses, limit=limit)
    for r in rows:
        existing = get_trade_inputs(r["id"])
        r["intaken"] = existing is not None
        r["rcs_synced_at"] = (existing or {}).get("rcs_synced_at")
        r["needs_user"] = (existing or {}).get("needs_user")
        r["resolved_ticker"] = resolve_ticker(r.get("instrument") or "")
        r["analysable"] = r.get("instrument_type") == "option"
    return {"trades": rows}


@router.post("/intake")
def sarah_intake(body: dict = Body(...)) -> dict:
    """
    Body: {"rcs_trade_ulid": "01KZ…", "refresh_vol": bool?}

    Reads the trade from RCS (read-only), resolves the options-liquid
    underlier, stores everything Class A/B can derive, and enqueues the vol
    pull for that ticker. Returns the ticker, the job id, the pre-fills, and
    `needs_user` — the exact list of judgment inputs still blocking a memo.

    **Safe to call again on a trade already intaken** — that is the re-pull
    path. It refreshes every Class-A/B field you have not explicitly
    overridden (so a leg or defined max-loss captured in RCS *after* the first
    intake lands here), reports what moved in `changed`, and never touches
    `expected_move`. By default it re-fetches the chain only when the ticker
    has no signals for today; `refresh_vol: true` forces it.

    Equity trades are rejected by design: they need no vol pull.
    """
    from systems.sarah.trade_intake import intake_trade

    ulid = body.get("rcs_trade_ulid")
    if not ulid:
        raise HTTPException(422, "body.rcs_trade_ulid required")
    refresh_vol = body.get("refresh_vol")
    conn = macro_conn()
    try:
        return intake_trade(str(ulid), requested_by="api", macro_conn=conn,
                            refresh_vol=(None if refresh_vol is None
                                         else bool(refresh_vol)))
    except KeyError as e:
        raise HTTPException(404, e.args[0])
    except ValueError as e:
        raise HTTPException(422, str(e))
    finally:
        conn.close()


@router.get("/intake")
def list_intakes(limit: int = 100) -> dict:
    from systems.sarah.trade_intake import list_trade_inputs
    return {"intakes": [_intake_view(r) for r in list_trade_inputs(limit)]}


@router.get("/intake/{rcs_trade_ulid}")
def get_intake(rcs_trade_ulid: str) -> dict:
    from systems.sarah.trade_intake import get_trade_inputs
    row = get_trade_inputs(rcs_trade_ulid)
    if row is None:
        raise HTTPException(
            404, f"no intake row for trade {rcs_trade_ulid} — "
                 "POST /api/sarah/intake first")
    return _intake_view(row)


@router.put("/intake/{rcs_trade_ulid}")
def put_intake(rcs_trade_ulid: str, body: dict = Body(...)) -> dict:
    """
    The user's Class-C answers: {expected_move?, expected_move_sign?,
    thesis_days?, catalyst_type?, max_loss_budget?, ticker?, flow_json?}.

    expected_move is an unsigned DECIMAL FRACTION (0.20 = ±20%). `ticker` is
    the underlier override for a position with no options chain — prefer
    adding the mapping to sarah.underlier_map, which is reusable across every
    trade on that ticker.
    """
    from systems.sarah.trade_intake import update_user_inputs
    try:
        row = update_user_inputs(rcs_trade_ulid, body)
    except KeyError as e:
        raise HTTPException(404, e.args[0])
    except ValueError as e:
        raise HTTPException(422, str(e))
    return _intake_view(row)


@router.get("/memos")
def list_memos(limit: int = 50, ticker: "str | None" = None) -> dict:
    conn = trading_conn()
    try:
        where = "WHERE ticker = ?" if ticker else ""
        args = ([ticker.upper()] if ticker else []) + [limit]
        rel = conn.execute(f"""
            SELECT memo_id, ticker, date, created_at, catalyst_type,
                   expected_move, thesis_days, max_loss_budget
            FROM pretrade_memos {where}
            ORDER BY created_at DESC LIMIT ?
        """, args)
        rows = rows_as_dicts(rel)
    except Exception:
        rows = []   # table not created yet — empty history, not an error
    finally:
        conn.close()
    return {"memos": rows}


@router.get("/memos/{memo_id}")
def get_memo(memo_id: str) -> dict:
    conn = trading_conn()
    try:
        row = conn.execute(
            "SELECT memo_json FROM pretrade_memos WHERE memo_id = ?",
            [memo_id]).fetchone()
    finally:
        conn.close()
    if not row:
        raise HTTPException(404, f"no memo '{memo_id}'")
    return json.loads(row[0])


# ── Regime library (Stage 5 GUI) ─────────────────────────────────────────────

def _load_vix_history(conn) -> "object":
    import pandas as pd
    df = conn.execute(
        "SELECT date, value FROM macro_series WHERE series_id = 'vix' "
        "ORDER BY date").fetchdf()
    if df.empty:
        return pd.Series(dtype=float)
    return df.set_index('date')['value'].sort_index()


def _load_vvix_history(conn) -> "object":
    import pandas as pd
    try:
        df = conn.execute(
            "SELECT date, vvix FROM vvix_daily ORDER BY date").fetchdf()
    except Exception:
        return pd.Series(dtype=float)
    if df.empty:
        return pd.Series(dtype=float)
    return df.set_index('date')['vvix'].sort_index()


@router.get("/regime-library/analogs")
def analogs(ticker: str = "SPY", n: int = 10,
            exclude_zero_rate_era: bool = False,
            require_regime_match: bool = False) -> dict:
    """
    Analog search over historical vol_signals with runtime vix_z1y/vvix_z1y
    enrichment (the feature vector is derived, not stored — see U5.0
    reconciliation note in the Phase 3 roadmap). Includes the GAP-001
    macro.db staleness warning.
    """
    from config import ANALOG_MIN_HISTORY_DAYS
    from systems.sarah.regime_library import (
        analog_search, enrich_snapshots_with_z_scores, macro_db_staleness,
    )

    tconn = trading_conn()
    try:
        snapshots = tconn.execute(
            "SELECT * FROM vol_signals WHERE ticker = ? ORDER BY date",
            [ticker.upper()]).fetchdf()
        vvix_history = _load_vvix_history(tconn)
    finally:
        tconn.close()
    if snapshots.empty:
        raise HTTPException(404, f"no vol_signals history for {ticker}")
    snapshots = snapshots.set_index('date')

    mconn = macro_conn()
    try:
        vix_history = _load_vix_history(mconn)
    finally:
        mconn.close()

    staleness = macro_db_staleness(vix_history=vix_history)
    enriched = enrich_snapshots_with_z_scores(snapshots, vix_history, vvix_history)

    current = enriched.iloc[-1].to_dict()
    current_date = str(enriched.index[-1])[:10]
    candidates = enriched.iloc[:-1]

    include_vvix = (len(vvix_history) >= 252
                    and current.get('vvix_z1y') == current.get('vvix_z1y'))

    warnings = []
    if staleness.get('warning'):
        warnings.append(staleness['warning'])
    if len(candidates) < ANALOG_MIN_HISTORY_DAYS:
        warnings.append(
            f"Only {len(candidates)} days of searchable history "
            f"(minimum {ANALOG_MIN_HISTORY_DAYS} for reliable analogs). The "
            "library fills as the daily run accumulates; CBOE historical EOD "
            "(U5.2, deferred paid gate) would bootstrap 20 years.")

    results = []
    if not candidates.empty:
        macro_filter = {
            'exclude_zero_rate_era': exclude_zero_rate_era,
            'require_regime_match': require_regime_match,
            'current_regime': current.get('macro_regime', ''),
        }
        df = analog_search(current, candidates, macro_filter,
                           n_results=n, include_vvix=include_vvix)
        results = [
            {k: (str(v)[:10] if k == 'date' else _py(v)) for k, v in r.items()}
            for r in df.to_dict(orient="records")
        ]

    return {
        "ticker": ticker.upper(),
        "as_of": current_date,
        "current_snapshot": {
            k: _py(current.get(k)) for k in
            ("atm_iv_30d", "iv_rank", "ts_front_slope", "ts_back_slope",
             "skew_25d_rr", "vix_z1y", "vvix_z1y", "macro_regime")
            if current.get(k) == current.get(k)  # drop NaN
        },
        "n_history": int(len(candidates)),
        "include_vvix": bool(include_vvix),
        "macro_db_staleness": staleness,
        "warnings": warnings,
        "analogs": results,
    }


@router.get("/regime-library/monitor")
def pre_transition(ticker: str = "SPY") -> dict:
    """VVIX pre-transition monitor — vix/vvix z-scores, ratio, warning flags."""
    from systems.sarah.regime_library import (
        macro_db_staleness, pre_transition_monitor,
    )

    tconn = trading_conn()
    try:
        vvix_history = _load_vvix_history(tconn)
        row = tconn.execute(
            "SELECT vvix, vix, date FROM vvix_daily "
            "ORDER BY date DESC LIMIT 1").fetchone()
    finally:
        tconn.close()

    mconn = macro_conn()
    try:
        vix_history = _load_vix_history(mconn)
    finally:
        mconn.close()

    vvix = float(row[0]) if row and row[0] is not None else None
    vix = None
    if row and row[1] is not None:
        vix = float(row[1])
    elif not vix_history.empty:
        vix = float(vix_history.iloc[-1])
    if vix is None:
        raise HTTPException(404, "no VIX available (vvix_daily and macro.db empty)")

    result = pre_transition_monitor(vix, vvix, vix_history, vvix_history)
    result["vvix_history_days"] = int(len(vvix_history))
    result["vvix_as_of"] = str(row[2])[:10] if row else None
    result["macro_db_staleness"] = macro_db_staleness(vix_history=vix_history)
    return result


@router.get("/regime-library/charts/vvix")
def chart_vvix(days: int = 756) -> dict:
    conn = trading_conn()
    try:
        rows = conn.execute("""
            SELECT date, vvix, vix FROM
              (SELECT date, vvix, vix FROM vvix_daily ORDER BY date DESC LIMIT ?)
            ORDER BY date ASC
        """, [days]).fetchall()
    finally:
        conn.close()
    if not rows:
        raise HTTPException(404, "vvix_daily is empty — run backfill_vvix_history")
    x = [str(r[0])[:10] for r in rows]
    return {
        "data": [
            {"type": "scatter", "mode": "lines", "x": x, "name": "VVIX",
             "y": [r[1] for r in rows], "line": {"color": "#aa66cc", "width": 1.4}},
            {"type": "scatter", "mode": "lines", "x": x, "name": "VIX",
             "y": [r[2] for r in rows], "line": {"color": "#33b5e5", "width": 1.1},
             "yaxis": "y2"},
        ],
        "layout": {**_base_layout(f"VVIX vs VIX — last {len(rows)} sessions"),
                   "legend": {"orientation": "h"},
                   "yaxis": {"title": {"text": "VVIX"}},
                   "yaxis2": {"title": {"text": "VIX"}, "overlaying": "y",
                              "side": "right"}},
    }


# ── Event library (YAML browser + editor) ────────────────────────────────────

_EVENTS_PATH = "data/events/regime_events.yaml"


@router.get("/regime-library/events")
def events() -> dict:
    from systems.sarah.regime_library import list_events
    return {"events": list_events(_EVENTS_PATH)}


@router.get("/regime-library/events/{event_id}")
def event_detail(event_id: str) -> dict:
    from systems.sarah.regime_library import event_browser
    e = event_browser(event_id, _EVENTS_PATH)
    if e is None:
        raise HTTPException(404, f"no event '{event_id}'")
    return e


@router.get("/regime-library/events-yaml")
def events_yaml() -> dict:
    from pathlib import Path
    p = Path(_EVENTS_PATH)
    if not p.exists():
        raise HTTPException(404, f"{_EVENTS_PATH} not found")
    return {"path": _EVENTS_PATH, "yaml": p.read_text()}


@router.put("/regime-library/events-yaml")
def save_events_yaml(body: dict = Body(...)) -> dict:
    """Save the curated event library. Validated before write; the previous
    version is kept alongside as .bak so a bad edit is one copy away."""
    import shutil
    from pathlib import Path

    import yaml

    text = body.get("yaml")
    if not text or not isinstance(text, str):
        raise HTTPException(422, "body.yaml (string) required")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise HTTPException(422, f"invalid YAML: {e}")
    if not isinstance(data, dict) or not isinstance(data.get("events"), list):
        raise HTTPException(422, "YAML must be a mapping with an 'events' list")
    ids = [e.get("id") for e in data["events"]]
    if any(not i for i in ids):
        raise HTTPException(422, "every event needs an 'id'")
    if len(ids) != len(set(ids)):
        raise HTTPException(422, "duplicate event ids")
    for e in data["events"]:
        if not e.get("name"):
            raise HTTPException(422, f"event '{e.get('id')}' missing 'name'")

    p = Path(_EVENTS_PATH)
    if p.exists():
        shutil.copy2(p, p.with_suffix(".yaml.bak"))
    p.write_text(text)
    return {"saved": True, "n_events": len(ids)}
