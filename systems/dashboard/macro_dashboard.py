"""
Macro Dashboard — Phase 2 output UI.
Runs as a local Dash app. Open http://127.0.0.1:8050 after starting.

Usage:
    python dashboard/macro_dashboard.py

Features (Phase 2):
  - Current regime state with change probability
  - Per-component data staleness layer (stale bars at 60% opacity)
  - Cross-asset divergence banner
  - Regime attribution panel (drivers / contradictors / flip watch)
  - Component score sparklines (separate row, 30d trend)
  - Regime transition log + days-in-regime counter
  - Divergence history chart tab
  - Regime-conditional return table tab
  - Auto-refreshes every hour
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import dash
from dash import dcc, html, Input, Output, State, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import pandas as pd
from datetime import datetime, date

from config import (REGIME_COLORS, DASHBOARD_HOST, DASHBOARD_PORT,
                    DASHBOARD_REFRESH_SECONDS, CHART_BASE_LAYOUT,
                    STALENESS_THRESHOLDS_DAYS, DIVERGENCE_THRESHOLD_VC,
                    COMPONENT_WEIGHTS)
from systems.signals.regime_classifier import RegimeClassifier
from systems.utils.db import get_connection, get_series_history, initialize_schema

# Ensure schema is up to date (safe to call on every startup — all DDL is idempotent)
initialize_schema()


# ── App Setup ─────────────────────────────────────────────────────────────────

app = dash.Dash(
    __name__,
    external_stylesheets=[dbc.themes.DARKLY],
    title="Macro Regime Dashboard",
    suppress_callback_exceptions=True,
)


# ── Helper: Load Data ─────────────────────────────────────────────────────────

def get_regime_result():
    clf = RegimeClassifier()
    return clf.classify(persist=True)

def get_regime_history_df():
    clf = RegimeClassifier()
    return clf.get_history(lookback_days=756)  # 3 years

def get_series_df(series_id: str, days: int = 756) -> pd.DataFrame:
    conn = get_connection()
    df = get_series_history(conn, series_id, lookback_days=days)
    conn.close()
    return df

def get_series_delta(series_id: str, periods: int = 5) -> "dict | None":
    df = get_series_df(series_id, days=30)
    if df is None or len(df) < periods + 1:
        return None
    df = df.sort_values("date")
    current = df["value"].iloc[-1]
    prior   = df["value"].iloc[-(periods + 1)]
    delta   = current - prior
    pct     = (delta / abs(prior) * 100) if prior != 0 else 0
    return {
        "current":    current,
        "delta":      delta,
        "pct_change": pct,
        "direction":  "▲" if delta > 0 else "▼" if delta < 0 else "→",
        "color":      "#ff4444" if delta > 0 else "#00C851" if delta < 0 else "#aaa",
    }

def get_component_history_df(days: int = 30) -> pd.DataFrame:
    conn = get_connection()
    df = conn.execute(f"""
        SELECT date, vol_score, credit_score, curve_score,
               inflation_score, labor_score, positioning_score,
               composite_score
        FROM regime_history
        WHERE date >= current_date - INTERVAL '{days} days'
          AND vol_score IS NOT NULL
        ORDER BY date
    """).df()
    conn.close()
    df["date"] = pd.to_datetime(df["date"])
    return df

def get_transition_log_df() -> pd.DataFrame:
    conn = get_connection()
    df = conn.execute("""
        SELECT * FROM (
            SELECT
                date,
                LAG(regime) OVER (ORDER BY date)              AS from_regime,
                regime                                         AS to_regime,
                composite_score,
                LAG(composite_score) OVER (ORDER BY date)     AS prior_score,
                composite_score
                    - LAG(composite_score) OVER (ORDER BY date) AS score_change,
                DATEDIFF('day',
                    LAG(date) OVER (ORDER BY date), date)      AS days_in_prior
            FROM regime_history
            ORDER BY date
        ) t
        WHERE from_regime IS NOT NULL
          AND from_regime != to_regime
        ORDER BY date DESC
        LIMIT 10
    """).df()
    conn.close()
    return df

def get_days_in_current_regime() -> int:
    conn = get_connection()
    result = conn.execute("""
        SELECT DATEDIFF('day', MIN(date), MAX(date)) + 1 as days
        FROM regime_history
        WHERE date >= (
            SELECT MAX(t.date) FROM (
                SELECT * FROM (
                    SELECT date,
                           LAG(regime) OVER (ORDER BY date) as prior_regime,
                           regime
                    FROM regime_history ORDER BY date
                ) s
                WHERE prior_regime != regime
            ) t
        )
    """).fetchone()
    conn.close()
    return result[0] if result and result[0] else 0

def get_cot_df() -> pd.DataFrame:
    conn = get_connection()
    df = conn.execute("""
        SELECT instrument, date, net_spec_pct, z_score_1y
        FROM cot_positioning
        WHERE date = (SELECT MAX(date) FROM cot_positioning)
        ORDER BY z_score_1y DESC NULLS LAST
    """).df()
    conn.close()
    return df


def fmt_delta(val: float, d: "dict | None") -> str:
    if d is None:
        return f"{val:.1f}"
    sign = "+" if d["delta"] > 0 else ""
    return f"{val:.1f}  {d['direction']} {sign}{d['delta']:.1f} (1W)"


# ── Phase 2: Staleness Helper ─────────────────────────────────────────────────

def _staleness(as_of: "date | None", component: str) -> str:
    """Returns 'fresh', 'stale', or 'missing'."""
    if as_of is None:
        return "missing"
    threshold = STALENESS_THRESHOLDS_DAYS[component]
    return "fresh" if (date.today() - as_of).days <= threshold else "stale"


# ── Chart Builders ────────────────────────────────────────────────────────────

def build_vix_chart(days: int = 756) -> go.Figure:
    df = get_series_df("vix", days)
    if df.empty:
        return go.Figure().update_layout(**CHART_BASE_LAYOUT, autosize=True)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["value"],
        name="VIX", line=dict(color="#00C851", width=1.5),
        fill="tozeroy", fillcolor="rgba(0,200,81,0.07)",
    ))
    for level, color, label in [
        (15, "rgba(0,200,81,0.3)",   "Low vol"),
        (20, "rgba(255,187,51,0.3)", "Elevated"),
        (25, "rgba(255,68,68,0.3)",  "Stress"),
        (35, "rgba(204,0,0,0.3)",    "Crisis"),
    ]:
        fig.add_hline(
            y=level,
            line=dict(color=color, dash="dot", width=1),
            annotation_text=label,
            annotation_position="top left",
            annotation=dict(
                font=dict(size=9, color=color),
                bgcolor="rgba(0,0,0,0)",
                borderwidth=0,
                xanchor="left",
            ),
        )

    d = get_series_delta("vix")
    title = f"VIX  {fmt_delta(d['current'], d)}" if d else "VIX History"

    fig.update_layout(
        **CHART_BASE_LAYOUT,
        title=title,
        height=360,
        showlegend=False,
        yaxis=dict(title="VIX"),
    )
    fig.update_layout(margin=dict(l=40, r=80, t=40, b=30))
    return fig


def build_hy_spread_chart(days: int = 756) -> go.Figure:
    df = get_series_df("hy_spread", days)
    if df.empty:
        return go.Figure()

    if df["value"].abs().mean() < 20:
        df["value"] = df["value"] * 100

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["value"],
        name="HY Spread", line=dict(color="#ff4444", width=1.5),
        fill="tozeroy", fillcolor="rgba(255,68,68,0.07)",
    ))
    for level, label in [(300, "Tight"), (450, "Normal"), (600, "Wide"), (900, "Crisis")]:
        fig.add_hline(
            y=level,
            line=dict(color="rgba(255,255,255,0.2)", dash="dot"),
            annotation_text=f"{level}bps",
            annotation_position="top left",
            annotation=dict(
                font=dict(size=9, color="rgba(255,255,255,0.5)"),
                bgcolor="rgba(0,0,0,0)",
                borderwidth=0,
                xanchor="left",
            ),
        )

    d = get_series_delta("hy_spread")
    if d:
        d = {**d, "delta": d["delta"] * 100, "current": d["current"] * 100}
    title = f"HY Spread  {fmt_delta(df['value'].iloc[-1], d)}bps" if d else "HY Credit Spread (OAS, bps)"

    fig.update_layout(
        **CHART_BASE_LAYOUT,
        title=title,
        height=360,
        showlegend=False,
    )
    return fig


def build_yield_curve_chart(days: int = 756) -> go.Figure:
    df = get_series_df("yield_curve_10_2", days)
    if df.empty:
        return go.Figure()

    if df["value"].abs().mean() < 5:
        df["value"] = df["value"] * 100

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["value"],
        name="10Y-2Y Spread",
        line=dict(color="#33b5e5", width=1.5),
        fill="tozeroy",
    ))
    fig.add_hline(y=0, line=dict(color="rgba(255,68,68,0.8)", width=1.5),
                  annotation_text="Inversion", annotation_position="right")

    d = get_series_delta("yield_curve_10_2")
    if d:
        crv_current = d["current"] * 100 if abs(d["current"]) < 5 else d["current"]
        title = f"10Y-2Y  {fmt_delta(crv_current, d)}bps"
    else:
        title = "10Y-2Y Yield Spread (bps)"

    fig.update_layout(
        **CHART_BASE_LAYOUT,
        title=title,
        height=360,
        showlegend=False,
    )
    return fig


def build_divergence_history_chart() -> go.Figure:
    """Plot |vol_score - credit_score| over time with threshold line."""
    conn = get_connection()
    df = conn.execute("""
        SELECT date, vol_score, credit_score
        FROM regime_history
        WHERE vol_score IS NOT NULL AND credit_score IS NOT NULL
        ORDER BY date
    """).df()
    conn.close()

    if df.empty:
        return go.Figure().update_layout(**CHART_BASE_LAYOUT, height=360)

    df["date"]      = pd.to_datetime(df["date"])
    df["spread_vc"] = (df["vol_score"] - df["credit_score"]).abs()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["spread_vc"],
        name="|Vol - Credit|",
        line=dict(color="#7c83fd", width=1.5),
        fill="tozeroy", fillcolor="rgba(124,131,253,0.07)",
        hovertemplate="%{x|%b %d %Y}<br>Spread: %{y:.3f}<extra></extra>",
    ))
    fig.add_hline(
        y=DIVERGENCE_THRESHOLD_VC,
        line=dict(color="rgba(255,68,68,0.6)", dash="dot", width=1),
        annotation_text=f"Threshold ({DIVERGENCE_THRESHOLD_VC})",
        annotation_position="top right",
        annotation=dict(
            font=dict(size=9, color="rgba(255,68,68,0.8)"),
            bgcolor="rgba(0,0,0,0)",
            borderwidth=0,
        ),
    )
    fig.update_layout(
        **CHART_BASE_LAYOUT,
        title="|Vol Score − Credit Score| — Divergence History",
        height=360,
        showlegend=False,
        yaxis=dict(title="Spread"),
    )
    return fig


def build_component_scores_chart(result, history_df: pd.DataFrame) -> go.Figure:
    """
    Two-row subplot: current score bars (row 1) + 30d sparklines (row 2).
    Stale bars render at 60% opacity with a ⚠ suffix.
    """
    components = ["Vol", "Credit", "Yield Curve", "Inflation", "Labor", "Positioning"]
    score_cols  = ["vol_score", "credit_score", "curve_score",
                   "inflation_score", "labor_score", "positioning_score"]
    scores      = [result.vol_score, result.credit_score, result.curve_score,
                   result.inflation_score, result.labor_score, result.positioning_score]
    comp_keys   = ["vol", "credit", "curve", "inflation", "labor", "positioning"]
    as_of_vals  = [result.vol_as_of, result.credit_as_of, result.curve_as_of,
                   result.inflation_as_of, result.labor_as_of, result.positioning_as_of]

    staleness = {c: _staleness(a, k)
                 for c, a, k in zip(components, as_of_vals, comp_keys)}
    opacities = [0.6 if staleness[c] != "fresh" else 1.0 for c in components]
    labels    = [f"{c} ⚠" if staleness[c] == "stale" else c for c in components]

    fig = make_subplots(
        rows=2, cols=len(components),
        row_heights=[0.75, 0.25],
        vertical_spacing=0.05,
        shared_xaxes=False,
    )

    # Row 1: current score bars
    for i, (name, score, label, opacity) in enumerate(zip(components, scores, labels, opacities)):
        color = f"rgba(0,200,81,{opacity})" if score >= 0 else f"rgba(255,68,68,{opacity})"
        fig.add_trace(go.Bar(
            x=[label], y=[score],
            name=name,
            marker_color=color,
            text=[f"{score:+.2f}"],
            textposition="outside",
            showlegend=False,
        ), row=1, col=i + 1)

    # Row 2: sparklines
    if not history_df.empty:
        for i, col in enumerate(score_cols):
            if col not in history_df.columns:
                continue
            spark_y = history_df[col].values
            spark_x = list(range(len(spark_y)))
            color   = "#00C851" if scores[i] >= 0 else "#ff4444"
            fig.add_trace(go.Scatter(
                x=spark_x, y=spark_y,
                mode="lines",
                line=dict(color=color, width=1.2),
                showlegend=False,
                hovertemplate="%{y:+.2f}<extra></extra>",
            ), row=2, col=i + 1)
            fig.add_hline(y=0,
                          line=dict(color="rgba(255,255,255,0.2)", width=0.5),
                          row=2, col=i + 1)

    # Hide sparkline axes
    for i in range(1, len(components) + 1):
        fig.update_xaxes(visible=False, row=2, col=i)
        fig.update_yaxes(visible=False, row=2, col=i, range=[-1.2, 1.2])

    fig.update_layout(
        **CHART_BASE_LAYOUT,
        title="Component Scores — bars: current | lines: 30d trend",
        height=320,
        yaxis=dict(range=[-1.4, 1.4]),
        bargap=0.3,
    )
    return fig


def build_regime_history_chart() -> go.Figure:
    df = get_regime_history_df()
    if df.empty:
        return go.Figure().update_layout(**CHART_BASE_LAYOUT, autosize=True)

    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)

    fig = go.Figure()

    regime_blocks = (df["regime"] != df["regime"].shift()).cumsum()
    for _, block in df.groupby(regime_blocks):
        regime = block["regime"].iloc[0]
        color  = REGIME_COLORS.get(regime, "#333333")
        fig.add_vrect(
            x0=block["date"].iloc[0],
            x1=block["date"].iloc[-1],
            fillcolor=color,
            opacity=0.07,
            layer="below",
            line_width=0,
        )

    fig.add_trace(go.Scatter(
        x=df["date"],
        y=df["composite_score"],
        mode="lines",
        line=dict(color="#7c83fd", width=1.5),
        name="Composite Score",
        hovertemplate="%{x|%b %d %Y}<br>Score: %{y:+.2f}<extra></extra>",
    ))
    fig.add_hline(y=0, line=dict(color="rgba(255,255,255,0.15)", width=1))

    transitions = df[df["regime"] != df["regime"].shift(1)].iloc[1:]
    for _, row in transitions.iterrows():
        fig.add_vline(
            x=row["date"].timestamp() * 1000,
            line_width=1,
            line_dash="dot",
            line_color="rgba(255,255,255,0.2)",
        )

    fig.update_layout(
        **CHART_BASE_LAYOUT,
        title="Regime Score History",
        height=280,
        yaxis=dict(range=[-1.2, 1.2], title="Score"),
        xaxis=dict(tickformat="%b %Y", nticks=8),
        showlegend=False,
    )
    return fig


# ── Card / Panel Builders ─────────────────────────────────────────────────────

def build_regime_card(result, history_df: pd.DataFrame) -> dbc.Card:
    """Phase 2: includes regime change probability and freshness row."""
    color = REGIME_COLORS.get(result.regime, "#33b5e5")

    vix_delta = get_series_delta("vix")
    hy_delta  = get_series_delta("hy_spread")
    crv_delta = get_series_delta("yield_curve_10_2")

    snap    = result.snapshot
    vix_val = vix_delta["current"] if vix_delta else snap.vix
    hy_val  = hy_delta["current"]  if hy_delta  else snap.hy_spread
    crv_val = crv_delta["current"] if crv_delta else snap.yield_curve_10_2
    if crv_val is not None:
        crv_val = crv_val * 100 if abs(crv_val) < 5 else crv_val

    reading_rows = []
    if vix_val is not None:
        reading_rows.append(html.Div([
            html.Span("VIX: ", style={"color": "#888", "fontSize": "0.78rem"}),
            html.Span(fmt_delta(vix_val, vix_delta),
                      style={"color": vix_delta["color"] if vix_delta else "#e0e0e0",
                             "fontSize": "0.82rem"}),
        ]))
    if hy_val is not None:
        reading_rows.append(html.Div([
            html.Span("HY Spread: ", style={"color": "#888", "fontSize": "0.78rem"}),
            html.Span(fmt_delta(hy_val, hy_delta),
                      style={"color": hy_delta["color"] if hy_delta else "#e0e0e0",
                             "fontSize": "0.82rem"}),
        ]))
    if crv_val is not None:
        reading_rows.append(html.Div([
            html.Span("10Y-2Y: ", style={"color": "#888", "fontSize": "0.78rem"}),
            html.Span(fmt_delta(crv_val, crv_delta),
                      style={"color": "#e0e0e0", "fontSize": "0.82rem"}),
        ]))

    # Phase 2: regime change probability
    prob_data = result.regime_change_probability(history_df)
    prob_color = (
        "#ff4444" if prob_data["probability"] >= 0.5
        else "#ffbb33" if prob_data["probability"] >= 0.25
        else "#00C851"
    )
    prob_row = html.Div([
        html.Span("Regime change (30d): ", style={"color": "#888", "fontSize": "0.78rem"}),
        html.Span(prob_data["label"],
                  style={"color": prob_color, "fontWeight": "600", "fontSize": "0.85rem"}),
        html.Span(f" → {prob_data['toward'].replace('_', ' ')}",
                  style={"color": "#888", "fontSize": "0.78rem"}),
    ], className="mt-1")

    # Phase 2: per-component freshness row
    comp_keys   = ["vol", "credit", "curve", "inflation", "labor", "positioning"]
    comp_labels = ["Vol", "Crd", "Crv", "Inf", "Lab", "COT"]
    as_of_vals  = [result.vol_as_of, result.credit_as_of, result.curve_as_of,
                   result.inflation_as_of, result.labor_as_of, result.positioning_as_of]

    freshness_spans = [html.Span("Data: ", style={"color": "#888", "fontSize": "0.72rem"})]
    for lbl, key, ao in zip(comp_labels, comp_keys, as_of_vals):
        st = _staleness(ao, key)
        if st == "fresh":
            freshness_spans.append(
                html.Span(f"{lbl} ✓  ", style={"color": "#00C851", "fontSize": "0.72rem"})
            )
        elif st == "stale":
            date_str = ao.strftime("%b %d") if ao else "?"
            freshness_spans.append(
                html.Span(f"{lbl} ⚠ {date_str}  ",
                          style={"color": "#ffbb33", "fontSize": "0.72rem"})
            )
        else:
            freshness_spans.append(
                html.Span(f"{lbl} —  ", style={"color": "#555", "fontSize": "0.72rem"})
            )
    freshness_row = html.Div(freshness_spans, className="mt-1")

    # Phase 4: persistence bar
    try:
        current_days   = get_days_in_current_regime()
        persist_stats  = get_regime_persistence_stats(result.regime)
        persistence_ui = [
            html.Div([
                html.Span("Day ", style={"color": "#888", "fontSize": "0.78rem"}),
                html.Span(str(current_days),
                          style={"color": "#e0e0e0", "fontWeight": "700",
                                 "fontSize": "0.9rem"}),
                html.Span(" of current regime",
                          style={"color": "#888", "fontSize": "0.78rem"}),
            ], className="mt-2"),
            build_persistence_bar(current_days, persist_stats),
        ]
    except Exception:
        persistence_ui = []

    return dbc.Card(
        dbc.CardBody([
            html.H6("CURRENT REGIME", className="text-muted mb-1",
                    style={"fontSize": "0.75rem", "letterSpacing": "0.1em"}),
            html.H2(result.regime.replace("_", " "),
                    style={"color": color, "fontWeight": "800", "fontSize": "1.8rem"}),
            html.Div([
                dbc.Badge(f"Score: {result.composite_score:+.2f}",
                          color="secondary", className="me-2"),
            ]),
            html.Div(reading_rows, className="mt-2"),
            *persistence_ui,
            prob_row,
            freshness_row,
            html.Small(f"As of {result.as_of}", className="text-muted mt-2 d-block"),
        ]),
        style={"background": "#12122a", "border": f"1px solid {color}"},
        className="mb-3",
    )


def build_signals_card(result) -> dbc.Card:
    bull_items = [
        html.Li(s, style={"color": "#00C851", "marginBottom": "3px"})
        for s in result.bullish_signals[:6]
    ]
    bear_items = [
        html.Li(s, style={"color": "#ff4444", "marginBottom": "3px"})
        for s in result.bearish_signals[:6]
    ]
    warn_items = [
        html.Li(s, style={"color": "#ffbb33", "marginBottom": "3px"})
        for s in result.warnings[:4]
    ]

    return dbc.Card(
        dbc.CardBody([
            html.H6("SIGNAL FEED", className="text-muted mb-2",
                    style={"fontSize": "0.75rem", "letterSpacing": "0.1em"}),
            html.Ul(bull_items, style={"listStyleType": "none", "padding": 0,
                                       "margin": 0, "fontSize": "0.82rem"}),
            html.Hr(style={"borderColor": "#333"}),
            html.Ul(bear_items, style={"listStyleType": "none", "padding": 0,
                                       "margin": 0, "fontSize": "0.82rem"}),
            (html.Hr(style={"borderColor": "#333"}) if warn_items else None),
            html.Ul(warn_items, style={"listStyleType": "none", "padding": 0,
                                       "margin": 0, "fontSize": "0.75rem"})
            if warn_items else None,
        ]),
        style={"background": "#12122a", "border": "1px solid #333"},
        className="mb-3",
    )


def build_cot_table(df: pd.DataFrame) -> dbc.Table:
    if df.empty:
        return html.P("No COT data. Run: python systems/data_feeds/macro_feed.py --cot",
                      className="text-muted small")

    rows = []
    for _, row in df.iterrows():
        z = row["z_score_1y"] or 0
        color = "#00C851" if z < -1.5 else "#ff4444" if z > 1.5 else "#ffffff"
        rows.append(html.Tr([
            html.Td(row["instrument"], style={"fontSize": "0.82rem"}),
            html.Td(f"{row['net_spec_pct']:.1f}%", style={"fontSize": "0.82rem"}),
            html.Td(f"{z:.1f}", style={"color": color, "fontSize": "0.82rem"}),
        ]))

    return dbc.Table(
        [
            html.Thead(html.Tr([
                html.Th("Instrument", style={"fontSize": "0.75rem"}),
                html.Th("Net Spec %OI", style={"fontSize": "0.75rem"}),
                html.Th("Z-Score 1Y", style={"fontSize": "0.75rem"}),
            ])),
            html.Tbody(rows),
        ],
        color="dark", striped=False, bordered=False,
        style={"marginBottom": 0},
    )


def build_divergence_banner(result) -> "dbc.Alert | None":
    """Phase 2: render divergence warning banner (HIGH=red, MEDIUM=amber, LOW=grey)."""
    d = result.divergence
    if d is None:
        return None

    color_map  = {"HIGH": "danger", "MEDIUM": "warning", "LOW": "secondary"}
    spread_str = f" (spread: {d['spread']:.2f})" if d.get("spread") else ""

    return dbc.Alert([
        html.Strong(f"⚡ {d['label']}{spread_str}  "),
        html.Span(d["detail"], style={"fontSize": "0.85rem"}),
    ], color=color_map.get(d["severity"], "secondary"),
       style={"marginBottom": "8px", "padding": "8px 12px"})


def build_attribution_panel(result) -> html.Div:
    """Phase 2: driver/contradictor table + flip-watch footer."""
    try:
        attr = result.attribution()
    except Exception:
        return html.Div()

    regime_direction = 1 if result.composite_score >= 0 else -1

    driver_rows = []
    for name, data in attr["drivers"].items():
        footnote = " †" if name == "Yield Curve" else ""
        score_color = "#00C851" if data["score"] > 0 else "#ff4444"
        driver_rows.append(html.Tr([
            html.Td(f"{name}{footnote}", style={"fontSize": "0.82rem"}),
            html.Td(f"{data['score']:+.2f}",
                    style={"fontSize": "0.82rem", "color": score_color}),
            html.Td(f"{data['weight']:.0%}",
                    style={"fontSize": "0.82rem", "color": "#888"}),
            html.Td(f"{data['contribution']:+.4f}",
                    style={"fontSize": "0.82rem"}),
        ]))

    contradictor_rows = []
    for name, data in attr["contradictors"].items():
        footnote    = " †" if name == "Yield Curve" else ""
        score_color = "#00C851" if data["score"] > 0 else "#ff4444"
        contradictor_rows.append(html.Tr([
            html.Td(f"{name}{footnote}",
                    style={"fontSize": "0.82rem",
                           "color": "#ff4444" if regime_direction > 0 else "#00C851"}),
            html.Td(f"{data['score']:+.2f}",
                    style={"fontSize": "0.82rem", "color": score_color}),
            html.Td(f"{data['weight']:.0%}",
                    style={"fontSize": "0.82rem", "color": "#888"}),
            html.Td(f"{data['contribution']:+.4f}",
                    style={"fontSize": "0.82rem"}),
        ]))

    separator = (
        [html.Tr([html.Td("── Contradictors ──", colSpan=4,
                           style={"color": "#888", "fontSize": "0.75rem",
                                  "paddingTop": "6px"})])]
        if contradictor_rows else []
    )

    # Watch for flip footer
    watch = attr["flip_watch"]
    footer_parts = []
    for w in watch:
        direction = "falls" if result.composite_score > 0 else "rises"
        footer_parts.append(
            f"{w['component']} score {direction} by {w['score_change_needed']:.2f}"
        )
    watch_text = (
        f"Watch for flip to {attr['nearest_regime'].replace('_', ' ')}: "
        + " OR ".join(footer_parts)
    ) if footer_parts else None

    children = [
        dbc.Table(
            [
                html.Thead(html.Tr([
                    html.Th("Component", style={"fontSize": "0.75rem"}),
                    html.Th("Score",     style={"fontSize": "0.75rem"}),
                    html.Th("Weight",    style={"fontSize": "0.75rem"}),
                    html.Th("Contrib.",  style={"fontSize": "0.75rem"}),
                ])),
                html.Tbody(driver_rows + separator + contradictor_rows),
            ],
            color="dark", striped=False, bordered=False,
            style={"marginBottom": "4px"},
        ),
        html.Small(
            "† 10Y-2Y and 10Y-3M are highly collinear — Yield Curve represents "
            "one independent signal with a timing offset, not two.",
            style={"color": "#888", "fontSize": "0.72rem",
                   "display": "block", "marginBottom": "4px"},
        ),
    ]

    if watch_text:
        children.append(
            html.P(watch_text,
                   style={"color": "#ffc107", "fontSize": "0.9rem",
                           "marginTop": "8px", "fontWeight": "500"})
        )

    return html.Div(children)


def build_transition_section() -> html.Div:
    """Phase 2: days-in-regime counter + recent transition log."""
    try:
        days = get_days_in_current_regime()
        df   = get_transition_log_df()
    except Exception:
        return html.Div()

    counter = html.Div([
        html.Span("Days in current regime: ",
                  style={"color": "#888", "fontSize": "0.78rem"}),
        html.Span(str(days),
                  style={"color": "#e0e0e0", "fontWeight": "700", "fontSize": "0.9rem"}),
    ], className="mb-2")

    if df.empty:
        table = html.P("No transition history yet.", className="text-muted small")
    else:
        rows = []
        for _, row in df.iterrows():
            rows.append(html.Tr([
                html.Td(str(row["date"])[:10],
                        style={"fontSize": "0.72rem", "color": "#888"}),
                html.Td(str(row["from_regime"]).replace("_", " "),
                        style={"fontSize": "0.72rem", "color": "#888"}),
                html.Td("→", style={"fontSize": "0.72rem", "color": "#555"}),
                html.Td(str(row["to_regime"]).replace("_", " "),
                        style={"fontSize": "0.72rem"}),
            ]))
        table = dbc.Table(
            [
                html.Thead(html.Tr([
                    html.Th("Date", style={"fontSize": "0.7rem"}),
                    html.Th("From", style={"fontSize": "0.7rem"}),
                    html.Th("",    style={"fontSize": "0.7rem"}),
                    html.Th("To",  style={"fontSize": "0.7rem"}),
                ])),
                html.Tbody(rows),
            ],
            color="dark", striped=False, bordered=False,
            style={"marginBottom": 0},
        )

    return html.Div([
        html.H6("REGIME TRANSITIONS", className="text-muted mb-2",
                style={"fontSize": "0.75rem", "letterSpacing": "0.1em"}),
        counter,
        table,
    ])


def build_return_table(current_regime: str) -> html.Div:
    """Phase 2: regime-conditional median return table. Requires compute_regime_return_stats.py."""
    try:
        conn = get_connection()
        df = conn.execute("""
            SELECT regime, asset, asset_label, horizon,
                   median_return, pct_25, pct_75, n_observations
            FROM regime_return_stats
            ORDER BY regime, horizon, asset
        """).df()
        conn.close()
    except Exception:
        return html.P(
            "Run scripts/compute_regime_return_stats.py to populate this table.",
            className="text-muted small",
            style={"padding": "20px"},
        )

    if df.empty:
        return html.P(
            "No return stats computed yet. Run scripts/compute_regime_return_stats.py",
            className="text-muted small",
            style={"padding": "20px"},
        )

    regimes  = df["regime"].unique()
    assets   = df["asset"].unique()
    horizons = ["1M", "3M"]

    header_cells = [html.Th("Regime / Asset", style={"fontSize": "0.75rem"})]
    for h in horizons:
        header_cells += [
            html.Th(f"{h} Median", style={"fontSize": "0.75rem"}),
            html.Th(f"{h} P25/P75", style={"fontSize": "0.75rem"}),
            html.Th(f"{h} N",      style={"fontSize": "0.75rem"}),
        ]

    body_rows = []
    for regime in regimes:
        is_current = regime == current_regime
        regime_bg  = {"backgroundColor": "rgba(255,255,255,0.04)"} if is_current else {}
        body_rows.append(html.Tr([
            html.Td(html.Strong(regime.replace("_", " ")),
                    colSpan=len(header_cells),
                    style={"fontSize": "0.8rem", "color": "#33b5e5",
                           "paddingTop": "8px", **regime_bg}),
        ]))
        for asset in assets:
            cells = [html.Td(asset,
                             style={"fontSize": "0.78rem", "paddingLeft": "14px",
                                    **regime_bg})]
            for h in horizons:
                sub = df[(df["regime"] == regime) & (df["asset"] == asset) & (df["horizon"] == h)]
                if sub.empty:
                    cells += [html.Td("-"), html.Td("-"), html.Td("-")]
                else:
                    r     = sub.iloc[0]
                    n     = int(r["n_observations"])
                    low_n = n < 20
                    sfx   = "*" if low_n else ""
                    med_color = "#888" if low_n else ("#00C851" if r["median_return"] > 0 else "#ff4444")
                    cells += [
                        html.Td(f"{r['median_return']:+.1f}%{sfx}",
                                style={"fontSize": "0.78rem", "color": med_color, **regime_bg}),
                        html.Td(f"{r['pct_25']:+.1f}/{r['pct_75']:+.1f}",
                                style={"fontSize": "0.75rem", "color": "#888", **regime_bg}),
                        html.Td(f"{n}{sfx}",
                                style={"fontSize": "0.75rem",
                                       "color": "#888" if low_n else "#e0e0e0",
                                       **regime_bg}),
                    ]
            body_rows.append(html.Tr(cells))

    return html.Div([
        html.P("Based on 2018–present (one full cycle). "
               "See History tab for regime distribution.",
               style={"fontSize": "0.78rem", "color": "#888", "margin": "8px 0 4px 0"}),
        dbc.Table(
            [html.Thead(html.Tr(header_cells)), html.Tbody(body_rows)],
            color="dark", striped=False, bordered=False,
        ),
        html.Small("* N<20 observations — interpret with caution.",
                   style={"color": "#888", "fontSize": "0.72rem"}),
    ], style={"overflowX": "auto"})


# ── Phase 4: Regime Persistence ───────────────────────────────────────────────

def get_regime_persistence_stats(regime_type: str) -> dict:
    """
    Find all historical episodes of a given regime type and compute duration statistics.
    Excludes the current (incomplete) episode to avoid biasing the distribution.
    Returns a dict with n_episodes=0 and median_days=None if insufficient history.
    """
    conn = get_connection()
    df = conn.execute("""
        SELECT date, regime, episode_id FROM (
            SELECT
                date,
                regime,
                SUM(is_new) OVER (ORDER BY date) AS episode_id
            FROM (
                SELECT
                    date,
                    regime,
                    CASE WHEN regime != LAG(regime) OVER (ORDER BY date)
                              OR LAG(regime) OVER (ORDER BY date) IS NULL
                         THEN 1 ELSE 0 END AS is_new
                FROM regime_history
                WHERE date >= '2018-01-01'
                ORDER BY date
            ) q1
        ) q2
        WHERE regime = ?
    """, [regime_type]).df()
    conn.close()

    if df.empty:
        return {"n_episodes": 0, "median_days": None}

    episodes = df.groupby("episode_id")["date"].count().rename("duration")
    episodes_complete = episodes.iloc[:-1] if len(episodes) > 1 else episodes

    if episodes_complete.empty:
        return {"n_episodes": 0, "median_days": None}

    return {
        "regime":      regime_type,
        "n_episodes":  len(episodes_complete),
        "median_days": int(episodes_complete.median()),
        "mean_days":   int(episodes_complete.mean()),
        "min_days":    int(episodes_complete.min()),
        "max_days":    int(episodes_complete.max()),
        "pct_25":      int(episodes_complete.quantile(0.25)),
        "pct_75":      int(episodes_complete.quantile(0.75)),
    }


def build_persistence_bar(current_days: int, stats: dict) -> html.Div:
    if not stats.get("median_days"):
        return html.Div()

    n = stats.get("n_episodes", 0)
    pct_25 = stats["pct_25"]
    pct_75 = stats["pct_75"]

    if current_days < pct_25:
        bar_color = "#00C851"
    elif current_days < stats["median_days"]:
        bar_color = "#33b5e5"
    elif current_days < pct_75:
        bar_color = "#ffbb33"
    else:
        bar_color = "#ff4444"

    fill_pct = min((current_days / (2 * stats["median_days"])) * 100, 100)

    thin_data_warning = (
        html.Span(" ⚠ thin sample",
                  style={"fontSize": "0.65rem", "color": "#ffaa00"})
        if n < 10 else None
    )

    return html.Div([
        html.Div([
            html.Div(style={
                "width": f"{fill_pct}%",
                "height": "4px",
                "backgroundColor": bar_color,
                "borderRadius": "2px",
                "transition": "width 0.3s ease",
            }),
        ], style={"width": "100%", "height": "4px",
                  "backgroundColor": "#2a2a3e", "borderRadius": "2px",
                  "marginTop": "6px"}),
        html.Div([
            html.Span(
                f"Historical: median {stats['median_days']}d | "
                f"range {stats['min_days']}-{stats['max_days']}d | "
                f"N={n} episodes",
                style={"fontSize": "0.7rem", "color": "#666"},
            ),
            thin_data_warning,
        ], style={"marginTop": "4px"}),
    ])


# ── Phase 4: Macro Calendar Widget ────────────────────────────────────────────

def build_calendar_widget() -> dbc.Card:
    conn = get_connection()
    df = conn.execute("""
        SELECT event_name, event_date, category, importance, component
        FROM macro_calendar
        WHERE event_date >= current_date
        ORDER BY event_date ASC
        LIMIT 5
    """).df()
    conn.close()

    if df.empty:
        return dbc.Card(dbc.CardBody([
            html.H6("MACRO CALENDAR", className="text-muted mb-2",
                    style={"fontSize": "0.75rem", "letterSpacing": "0.1em"}),
            html.P("No upcoming events. Run fetch_calendar_data() to populate.",
                   className="text-muted small"),
        ]), style={"background": "#12122a", "border": "1px solid #333", "marginTop": "8px"})

    rows = []
    for _, row in df.iterrows():
        days_until = (row["event_date"] - date.today()).days
        urgent     = days_until <= 3

        component = row["component"]
        if component is None:
            component_label = "⚡ Multi-component"
            sensitivity_txt = ""
        else:
            component_label = component
            weight = COMPONENT_WEIGHTS.get(component, 0.0)
            max_impact = round(weight * 1.0, 2)
            sensitivity_txt = f"  ±{max_impact:.2f} composite"

        rows.append(dbc.ListGroupItem([
            html.Div([
                html.Span(row["event_name"],
                          style={"fontWeight": "600" if row["importance"] == 1 else "400",
                                 "fontSize": "0.8rem"}),
                html.Span(f"  {days_until}d",
                          style={"color": "#ff4444" if urgent else "#888",
                                 "fontSize": "0.75rem", "marginLeft": "6px"}),
            ]),
            html.Div([
                html.Span(row["event_date"].strftime("%b %d"),
                          style={"fontSize": "0.7rem", "color": "#666"}),
                html.Span(f"  {component_label}{sensitivity_txt}",
                          style={"fontSize": "0.7rem",
                                 "color": "#ffaa00" if component is None else "#555"}),
            ]),
        ], style={"background": "#0d1117", "border": "none",
                  "borderLeft": "3px solid #ff4444" if urgent else "3px solid #333",
                  "padding": "6px 10px", "marginBottom": "2px"}))

    return dbc.Card(dbc.CardBody([
        html.H6("MACRO CALENDAR", className="text-muted mb-2",
                style={"fontSize": "0.75rem", "letterSpacing": "0.1em"}),
        dbc.ListGroup(rows, flush=True),
    ]), style={"background": "#12122a", "border": "1px solid #333", "marginTop": "8px"})


# ── Phase 4: Chart Render Helpers ──────────────────────────────────────────────

def _render_chart_matplotlib(fig: go.Figure, path: str,
                              width: int = 800, height: int = 300) -> None:
    """
    Fallback chart renderer when kaleido is unavailable.
    Renders a text summary panel instead of a visual chart.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig_mpl, ax = plt.subplots(figsize=(width / 100, height / 100))
    fig_mpl.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")
    ax.axis("off")

    lines = [f"Chart: {fig.layout.title.text or 'Regime Data'}"]
    for trace in fig.data:
        if hasattr(trace, "y") and trace.y is not None and len(trace.y) > 0:
            name   = getattr(trace, "name", "Series")
            latest = trace.y[-1]
            lines.append(f"{name}: {latest:+.3f} (latest)")

    text_block = "\n".join(lines)
    ax.text(0.05, 0.5, text_block,
            transform=ax.transAxes,
            fontsize=9, color="#cccccc",
            verticalalignment="center",
            fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="#12122a", alpha=0.8))

    ax.text(0.05, 0.05,
            "[Chart rendering unavailable — kaleido not installed]",
            transform=ax.transAxes, fontsize=7, color="#555")

    plt.tight_layout(pad=0.5)
    plt.savefig(path, dpi=150, bbox_inches="tight",
                facecolor=fig_mpl.get_facecolor())
    plt.close(fig_mpl)


def render_chart_png(fig: go.Figure, path: str, width: int = 800, height: int = 300):
    """Render a Plotly figure to PNG. Falls back to matplotlib text panel on kaleido failure."""
    import logging
    _log = logging.getLogger(__name__)
    try:
        import kaleido  # noqa: F401
        fig.write_image(path, width=width, height=height, scale=2)
    except Exception as e:
        _log.warning(f"kaleido failed ({e}), using matplotlib text fallback")
        _render_chart_matplotlib(fig, path, width, height)


# ── Phase 4: Drawdown Overlay Chart ───────────────────────────────────────────

def build_drawdown_overlay_chart(days: int = 756) -> go.Figure:
    regime_df   = get_regime_history_df()
    drawdown_df = get_series_df("spy_drawdown", days)

    fig = go.Figure()

    if not regime_df.empty:
        regime_df["date"] = pd.to_datetime(regime_df["date"])
        regime_blocks = (regime_df["regime"] != regime_df["regime"].shift()).cumsum()
        for _, block in regime_df.groupby(regime_blocks):
            regime = block["regime"].iloc[0]
            color  = REGIME_COLORS.get(regime, "#333")
            fig.add_vrect(x0=block["date"].iloc[0], x1=block["date"].iloc[-1],
                          fillcolor=color, opacity=0.07, layer="below", line_width=0)

        fig.add_trace(go.Scatter(
            x=regime_df["date"], y=regime_df["composite_score"],
            name="Regime Score", yaxis="y1",
            line=dict(color="#7c83fd", width=1.5),
            hovertemplate="%{x|%b %d %Y}<br>Score: %{y:+.2f}<extra></extra>",
        ))

    if not drawdown_df.empty:
        drawdown_df["date"] = pd.to_datetime(drawdown_df["date"])
        fig.add_trace(go.Scatter(
            x=drawdown_df["date"], y=drawdown_df["value"],
            name="SPX Drawdown", yaxis="y2",
            line=dict(color="rgba(255,100,100,0.7)", width=1.2),
            fill="tozeroy", fillcolor="rgba(255,68,68,0.06)",
            hovertemplate="%{x|%b %d %Y}<br>Drawdown: %{y:.1f}%<extra></extra>",
        ))

    vix_df = get_series_df("VIXCLS", days)
    if vix_df.empty:
        vix_df = get_series_df("vix", days)
    if not vix_df.empty:
        vix_norm = -((vix_df["value"] - vix_df["value"].mean()) /
                      vix_df["value"].std()).clip(-3, 3) / 3
        fig.add_trace(go.Scatter(
            x=pd.to_datetime(vix_df["date"]), y=vix_norm,
            name="VIX Baseline (normalized)", yaxis="y1",
            line=dict(color="rgba(255,200,0,0.4)", width=1, dash="dot"),
            hovertemplate="%{x|%b %d %Y}<br>VIX norm: %{y:+.2f}<extra></extra>",
        ))

    fig.update_layout(
        **CHART_BASE_LAYOUT,
        autosize=True,
        title="Regime Score vs SPX Drawdown — Composite (blue) vs VIX-only baseline (yellow)",
        yaxis=dict(title="Regime Score", range=[-1.2, 1.2], side="left"),
        yaxis2=dict(
            title="SPX Drawdown %",
            overlaying="y", side="right",
            autorange="reversed",
            showgrid=False,
            tickformat=".0f",
            ticksuffix="%",
        ),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    return fig


# ── Layout ────────────────────────────────────────────────────────────────────

app.layout = dbc.Container(
    fluid=True,
    style={"backgroundColor": "#0d0d1f", "minHeight": "100vh", "padding": "12px"},
    children=[
        dcc.Interval(id="refresh-interval",
                     interval=DASHBOARD_REFRESH_SECONDS * 1000,
                     n_intervals=0),
        dcc.Store(id="attribution-open", data=True),
        dcc.Download(id="snapshot-download"),

        # Header
        dbc.Row([
            dbc.Col([
                html.H4("Macro Regime Dashboard",
                        style={"color": "#ffffff", "fontWeight": "700",
                               "marginBottom": "2px"}),
                html.Small(f"Phase 4 | Refreshes every "
                           f"{DASHBOARD_REFRESH_SECONDS // 3600}h",
                           className="text-muted"),
            ], width=8),
            dbc.Col([
                dbc.Button("Export Snapshot", id="export-btn", size="sm",
                           style={"fontSize": "0.75rem", "padding": "3px 10px",
                                  "background": "transparent", "border": "1px solid #444"}),
            ], width=1, className="text-end", style={"paddingTop": "6px"}),
            dbc.Col([
                html.Div(id="last-updated", className="text-end text-muted",
                         style={"fontSize": "0.8rem", "paddingTop": "8px"}),
            ], width=3),
        ], className="mb-2", style={"height": "60px"}),

        # Main content
        dbc.Row([
            # Left column: regime + signals + COT + transition log
            dbc.Col([
                html.Div(id="regime-card"),
                html.Div(id="signals-card"),
                dbc.Card(
                    dbc.CardBody([
                        html.H6("COT POSITIONING", className="text-muted mb-2",
                                style={"fontSize": "0.75rem", "letterSpacing": "0.1em"}),
                        html.Div(id="cot-table"),
                    ]),
                    style={"background": "#12122a", "border": "1px solid #333"},
                    className="mb-3",
                ),
                dbc.Card(
                    dbc.CardBody([
                        html.Div(id="transition-section"),
                    ]),
                    style={"background": "#12122a", "border": "1px solid #333"},
                ),
                html.Div(id="calendar-widget"),
            ], width=3, style={"overflowY": "auto", "maxHeight": "calc(100vh - 80px)"}),

            # Right column: charts + attribution
            dbc.Col([
                # Divergence banner (hidden when no divergence)
                html.Div(id="divergence-banner", className="mb-2"),

                # Top row: component scores + regime history
                dbc.Row([
                    dbc.Col(dcc.Graph(id="component-scores",
                                     config={"displayModeBar": False}), width=6),
                    dbc.Col(dcc.Graph(id="regime-history",
                                     config={"displayModeBar": False}), width=6),
                ], className="mb-2"),

                # Attribution panel (collapsible, default open)
                dbc.Card(
                    dbc.CardBody([
                        dbc.Row([
                            dbc.Col(
                                html.H6("REGIME ATTRIBUTION",
                                        className="text-muted mb-0",
                                        style={"fontSize": "0.75rem",
                                               "letterSpacing": "0.1em"}),
                                width=10,
                            ),
                            dbc.Col(
                                dbc.Button("▲", id="attribution-toggle-btn",
                                           size="sm", color="secondary", outline=True,
                                           style={"fontSize": "0.7rem",
                                                  "padding": "1px 6px"}),
                                width=2, className="text-end",
                            ),
                        ], align="center", className="mb-1"),
                        dbc.Collapse(
                            html.Div(id="attribution-panel"),
                            id="attribution-collapse",
                            is_open=True,
                        ),
                    ]),
                    style={"background": "#12122a", "border": "1px solid #333"},
                    className="mb-2",
                ),

                # Bottom tabbed charts
                dbc.Tabs(
                    [
                        dbc.Tab(
                            dcc.Graph(id="vix-chart",
                                      config={"displayModeBar": False}),
                            label="VIX",
                            tab_id="tab-vix",
                        ),
                        dbc.Tab(
                            dcc.Graph(id="hy-chart",
                                      config={"displayModeBar": False}),
                            label="HY Spreads",
                            tab_id="tab-hy",
                        ),
                        dbc.Tab(
                            dcc.Graph(id="curve-chart",
                                      config={"displayModeBar": False}),
                            label="Yield Curve",
                            tab_id="tab-curve",
                        ),
                        dbc.Tab(
                            dcc.Graph(id="divergence-chart",
                                      config={"displayModeBar": False}),
                            label="Divergence",
                            tab_id="tab-divergence",
                        ),
                        dbc.Tab(
                            html.Div(id="return-table",
                                     style={"maxHeight": "380px", "overflowY": "auto",
                                            "padding": "8px"}),
                            label="Returns",
                            tab_id="tab-returns",
                        ),
                        dbc.Tab(
                            dcc.Graph(id="drawdown-chart",
                                      config={"displayModeBar": False}),
                            label="Validation",
                            tab_id="tab-validation",
                        ),
                    ],
                    id="bottom-chart-tabs",
                    active_tab="tab-vix",
                ),
            ], width=9),
        ]),
    ]
)


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("attribution-collapse",    "is_open"),
    Output("attribution-toggle-btn",  "children"),
    Output("attribution-open",        "data"),
    Input("attribution-toggle-btn",   "n_clicks"),
    State("attribution-open",         "data"),
    prevent_initial_call=True,
)
def toggle_attribution(n_clicks, is_open):
    new_state = not is_open
    return new_state, ("▲" if new_state else "▼"), new_state


@callback(
    Output("regime-card",       "children"),
    Output("signals-card",      "children"),
    Output("component-scores",  "figure"),
    Output("regime-history",    "figure"),
    Output("vix-chart",         "figure"),
    Output("hy-chart",          "figure"),
    Output("curve-chart",       "figure"),
    Output("cot-table",         "children"),
    Output("last-updated",      "children"),
    Output("divergence-banner", "children"),
    Output("attribution-panel", "children"),
    Output("divergence-chart",  "figure"),
    Output("return-table",      "children"),
    Output("transition-section","children"),
    Output("calendar-widget",   "children"),
    Output("drawdown-chart",    "figure"),
    Input("refresh-interval",   "n_intervals"),
)
def refresh_all(_):
    try:
        result     = get_regime_result()
        cot_df     = get_cot_df()
        history_df = get_component_history_df(days=30)

        return (
            build_regime_card(result, history_df),
            build_signals_card(result),
            build_component_scores_chart(result, history_df),
            build_regime_history_chart(),
            build_vix_chart(),
            build_hy_spread_chart(),
            build_yield_curve_chart(),
            build_cot_table(cot_df),
            f"Last refreshed: {datetime.now().strftime('%H:%M:%S')}",
            build_divergence_banner(result),
            build_attribution_panel(result),
            build_divergence_history_chart(),
            build_return_table(result.regime),
            build_transition_section(),
            build_calendar_widget(),
            build_drawdown_overlay_chart(),
        )
    except Exception as e:
        error_card = dbc.Alert(f"Error loading data: {e}", color="danger")
        empty_fig  = go.Figure()
        empty_fig.update_layout(template="plotly_dark",
                                paper_bgcolor="#1a1a2e",
                                plot_bgcolor="#1a1a2e",
                                height=260)
        return (
            error_card, error_card,
            empty_fig, empty_fig, empty_fig, empty_fig, empty_fig,
            "No COT data",
            f"Error at {datetime.now().strftime('%H:%M:%S')}",
            None, html.Div(),
            empty_fig,
            html.P(f"Error: {e}", className="text-muted small"),
            html.Div(),
            html.Div(),
            empty_fig,
        )


@callback(
    Output("snapshot-download", "data"),
    Input("export-btn", "n_clicks"),
    prevent_initial_call=True,
)
def export_snapshot_callback(_):
    from systems.reports.snapshot_generator import generate_snapshot
    pdf_bytes = generate_snapshot(return_bytes=True)
    ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    return dcc.send_bytes(pdf_bytes, filename=f"macro_snapshot_{ts}.pdf")


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n Macro Dashboard starting at http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    print(" Press Ctrl+C to stop.\n")
    app.run(
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        debug=False,
    )
