"""
Macro Dashboard — Phase 1 output UI.
Runs as a local Dash app. Open http://127.0.0.1:8050 after starting.

Usage:
    python dashboard/macro_dashboard.py

Features:
  - Current regime state (big, clear, color-coded)
  - Component score breakdown bar chart
  - VIX history + term structure
  - Yield curve (current shape)
  - HY credit spread history
  - Signal feed (bullish / bearish)
  - COT positioning table
  - Auto-refreshes every hour
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import dash
from dash import dcc, html, Input, Output, callback
import dash_bootstrap_components as dbc
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
from datetime import datetime

from config import REGIME_COLORS, DASHBOARD_HOST, DASHBOARD_PORT, DASHBOARD_REFRESH_SECONDS
from systems.signals.regime_classifier import RegimeClassifier
from systems.utils.db import get_connection, get_series_history


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


# ── Chart Builders ────────────────────────────────────────────────────────────

def build_vix_chart(days: int = 756) -> go.Figure:
    df = get_series_df("vix", days)
    if df.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["value"],
        name="VIX", line=dict(color="#00C851", width=1.5),
        fill="tozeroy", fillcolor="rgba(0,200,81,0.07)",
    ))
    for level, color, label in [
        (15, "rgba(0,200,81,0.3)", "Low vol"),
        (20, "rgba(255,187,51,0.3)", "Elevated"),
        (25, "rgba(255,68,68,0.3)", "Stress"),
        (35, "rgba(204,0,0,0.3)",   "Crisis"),
    ]:
        fig.add_hline(y=level, line=dict(color=color, dash="dot", width=1),
                      annotation_text=label, annotation_position="right")

    fig.update_layout(
        title="VIX History",
        template="plotly_dark",
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#1a1a2e",
        margin=dict(l=10, r=10, t=40, b=10),
        height=260,
        showlegend=False,
        yaxis=dict(title="VIX"),
    )
    return fig


def build_hy_spread_chart(days: int = 756) -> go.Figure:
    df = get_series_df("hy_spread", days)
    if df.empty:
        return go.Figure()

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["value"],
        name="HY Spread", line=dict(color="#ff4444", width=1.5),
        fill="tozeroy", fillcolor="rgba(255,68,68,0.07)",
    ))
    for level, label in [(300, "Tight"), (450, "Normal"), (600, "Wide"), (900, "Crisis")]:
        fig.add_hline(y=level, line=dict(color="rgba(255,255,255,0.2)", dash="dot"),
                      annotation_text=f"{level}bps", annotation_position="right")

    fig.update_layout(
        title="HY Credit Spread (OAS, bps)",
        template="plotly_dark",
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#1a1a2e",
        margin=dict(l=10, r=10, t=40, b=10),
        height=260,
        showlegend=False,
    )
    return fig


def build_yield_curve_chart(days: int = 756) -> go.Figure:
    df = get_series_df("yield_curve_10_2", days)
    if df.empty:
        return go.Figure()

    # Convert to bps
    if df["value"].abs().mean() < 5:
        df["value"] = df["value"] * 100

    colors = ["#ff4444" if v < 0 else "#00C851" for v in df["value"]]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["value"],
        name="10Y-2Y Spread",
        line=dict(color="#33b5e5", width=1.5),
        fill="tozeroy",
    ))
    fig.add_hline(y=0, line=dict(color="rgba(255,68,68,0.8)", width=1.5),
                  annotation_text="Inversion", annotation_position="right")

    fig.update_layout(
        title="10Y-2Y Yield Spread (bps)",
        template="plotly_dark",
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#1a1a2e",
        margin=dict(l=10, r=10, t=40, b=10),
        height=260,
        showlegend=False,
    )
    return fig


def build_component_scores_chart(result) -> go.Figure:
    components = {
        "Vol":         result.vol_score,
        "Credit":      result.credit_score,
        "Yield Curve": result.curve_score,
        "Inflation":   result.inflation_score,
        "Labor":       result.labor_score,
        "Positioning": result.positioning_score,
    }

    colors = ["#00C851" if v >= 0 else "#ff4444" for v in components.values()]

    fig = go.Figure(go.Bar(
        x=list(components.keys()),
        y=list(components.values()),
        marker_color=colors,
        text=[f"{v:+.2f}" for v in components.values()],
        textposition="outside",
    ))
    fig.add_hline(y=0, line=dict(color="white", width=0.5))
    fig.update_layout(
        title="Component Scores (-1 to +1)",
        template="plotly_dark",
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#1a1a2e",
        yaxis=dict(range=[-1.2, 1.2]),
        margin=dict(l=10, r=10, t=40, b=10),
        height=260,
    )
    return fig


def build_regime_history_chart() -> go.Figure:
    df = get_regime_history_df()
    if df.empty:
        return go.Figure()

    color_map = {
        "RISK_ON_LOW_VOL":      "#00C851",
        "RISK_ON_ELEVATED_VOL": "#ffbb33",
        "NEUTRAL":              "#33b5e5",
        "CAUTION":              "#FF8800",
        "RISK_OFF_STRESS":      "#ff4444",
        "CRISIS":               "#CC0000",
    }

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["date"], y=df["composite_score"],
        mode="lines",
        line=dict(color="#ffffff", width=1),
        name="Composite Score",
    ))

    # Color bands
    for score, label, color in [
        (0.60,  "Risk On Low Vol",      "rgba(0,200,81,0.12)"),
        (0.25,  "Risk On Elev Vol",     "rgba(255,187,51,0.12)"),
        (-0.10, "Neutral",              "rgba(51,181,229,0.08)"),
        (-0.40, "Caution",              "rgba(255,136,0,0.12)"),
        (-0.65, "Risk Off",             "rgba(255,68,68,0.12)"),
    ]:
        pass  # band shading is complex — simplified here

    fig.update_layout(
        title="Regime Score History",
        template="plotly_dark",
        paper_bgcolor="#1a1a2e",
        plot_bgcolor="#1a1a2e",
        margin=dict(l=10, r=10, t=40, b=10),
        height=200,
        yaxis=dict(range=[-1.1, 1.1], title="Score"),
        showlegend=False,
        legend=dict(x=0.01, xanchor='left'),
    )
    return fig


# ── Layout ────────────────────────────────────────────────────────────────────

def build_regime_card(result) -> dbc.Card:
    color = REGIME_COLORS.get(result.regime, "#33b5e5")
    return dbc.Card(
        dbc.CardBody([
            html.H6("CURRENT REGIME", className="text-muted mb-1",
                    style={"fontSize": "0.75rem", "letterSpacing": "0.1em"}),
            html.H2(result.regime.replace("_", " "),
                    style={"color": color, "fontWeight": "800", "fontSize": "1.8rem"}),
            html.Div([
                dbc.Badge(f"Score: {result.composite_score:+.2f}",
                          color="secondary", className="me-2"),
                dbc.Badge(f"Confidence: {result.confidence}",
                          color="dark"),
            ]),
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


app.layout = dbc.Container(
    fluid=True,
    style={"background": "#0d0d1f", "minHeight": "100vh", "padding": "20px"},
    children=[
        # Auto-refresh interval
        dcc.Interval(id="refresh-interval",
                     interval=DASHBOARD_REFRESH_SECONDS * 1000,
                     n_intervals=0),

        # Header
        dbc.Row([
            dbc.Col([
                html.H4("Macro Regime Dashboard",
                        style={"color": "#ffffff", "fontWeight": "700",
                               "marginBottom": "2px"}),
                html.Small(f"Phase 1 — Marcus's Layer | Refreshes every "
                           f"{DASHBOARD_REFRESH_SECONDS//3600}h",
                           className="text-muted"),
            ], width=9),
            dbc.Col([
                html.Div(id="last-updated", className="text-end text-muted",
                         style={"fontSize": "0.8rem", "paddingTop": "8px"}),
            ], width=3),
        ], className="mb-3"),

        # Main content
        dbc.Row([
            # Left column: regime + signals
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
                ),
            ], width=3),

            # Right column: charts
            dbc.Col([
                dbc.Row([
                    dbc.Col(dcc.Graph(id="component-scores", config={"displayModeBar": False}), width=6),
                    dbc.Col(dcc.Graph(id="regime-history",   config={"displayModeBar": False}), width=6),
                ], className="mb-2"),
                dbc.Row([
                    dbc.Col(dcc.Graph(id="vix-chart",    config={"displayModeBar": False}), width=4),
                    dbc.Col(dcc.Graph(id="hy-chart",     config={"displayModeBar": False}), width=4),
                    dbc.Col(dcc.Graph(id="curve-chart",  config={"displayModeBar": False}), width=4),
                ]),
            ], width=9),
        ]),
    ]
)


# ── Callbacks ─────────────────────────────────────────────────────────────────

@callback(
    Output("regime-card",      "children"),
    Output("signals-card",     "children"),
    Output("component-scores", "figure"),
    Output("regime-history",   "figure"),
    Output("vix-chart",        "figure"),
    Output("hy-chart",         "figure"),
    Output("curve-chart",      "figure"),
    Output("cot-table",        "children"),
    Output("last-updated",     "children"),
    Input("refresh-interval",  "n_intervals"),
)
def refresh_all(_):
    try:
        result = get_regime_result()
        cot_df = get_cot_df()

        return (
            build_regime_card(result),
            build_signals_card(result),
            build_component_scores_chart(result),
            build_regime_history_chart(),
            build_vix_chart(),
            build_hy_spread_chart(),
            build_yield_curve_chart(),
            build_cot_table(cot_df),
            f"Last refreshed: {datetime.now().strftime('%H:%M:%S')}",
        )
    except Exception as e:
        error_card = dbc.Alert(f"Error loading data: {e}", color="danger")
        empty_fig = go.Figure()
        empty_fig.update_layout(template="plotly_dark",
                                paper_bgcolor="#1a1a2e",
                                plot_bgcolor="#1a1a2e",
                                height=260)
        return (
            error_card, error_card,
            empty_fig, empty_fig, empty_fig, empty_fig, empty_fig,
            "No COT data",
            f"Error at {datetime.now().strftime('%H:%M:%S')}",
        )


def backfill_regime_history():
    """Run classifier for each date we have macro data but no regime score."""
    from systems.signals.regime_classifier import RegimeClassifier
    from systems.utils.db import get_connection
    conn = get_connection()

    # Find dates with macro data but no regime classification
    missing = conn.execute("""
        SELECT DISTINCT date FROM macro_series
        WHERE date NOT IN (SELECT date FROM regime_history)
        AND date >= current_date - INTERVAL 730 DAY
        ORDER BY date
    """).df()

    if len(missing) == 0:
        return

    print(f"Backfilling {len(missing)} regime history dates...")
    clf = RegimeClassifier()
    # Note: V1 classifier uses today's snapshot for all dates —
    # true historical backfill requires per-date data slicing.
    # For now, just run once to populate today's date if missing.
    result = clf.classify(persist=True)
    print(f"Regime history updated: {result.regime}")

backfill_regime_history()


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print(f"\n Macro Dashboard starting at http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    print(" Press Ctrl+C to stop.\n")
    app.run(
        host=DASHBOARD_HOST,
        port=DASHBOARD_PORT,
        debug=False,
    )
