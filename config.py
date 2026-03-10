"""
Phase 1 Configuration
All constants, series IDs, and thresholds in one place.
Update thresholds here — nowhere else.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
FRED_API_KEY = os.getenv("FRED_API_KEY", "")   # free at fred.stlouisfed.org/docs/api

# ── Database ──────────────────────────────────────────────────────────────────
DUCKDB_PATH = "data/processed/macro.db"

# ── FRED Series ───────────────────────────────────────────────────────────────
# Format: { internal_name: (fred_series_id, human_label, update_frequency) }
MACRO_SERIES = {
    # Rates & Yield Curve
    "fed_funds":        ("FEDFUNDS",    "Fed Funds Rate",           "monthly"),
    "treasury_10y":     ("GS10",        "10Y Treasury Yield",       "monthly"),
    "treasury_2y":      ("GS2",         "2Y Treasury Yield",        "monthly"),
    "treasury_3m":      ("GS3M",        "3M Treasury Yield",        "monthly"),
    "yield_curve_10_2": ("T10Y2Y",      "10Y-2Y Yield Spread",      "daily"),
    "yield_curve_10_3": ("T10Y3M",      "10Y-3M Yield Spread",      "daily"),
    "real_rate_10y":    ("DFII10",      "10Y Real Rate (TIPS)",     "daily"),

    # Volatility & Risk
    "vix":              ("VIXCLS",      "VIX (CBOE)",               "daily"),
    # "move_index":     ("BAMLMOVE",    "MOVE Index (bond vol)",    "daily"),  # not on FRED

    # Credit
    "hy_spread":        ("BAMLH0A0HYM2", "HY Credit Spread (OAS)", "daily"),
    "ig_spread":        ("BAMLC0A0CM",   "IG Credit Spread (OAS)", "daily"),

    # Growth / Activity
    "industrial_prod":  ("INDPRO",      "Industrial Production",    "monthly"),
    "retail_sales":     ("RSAFS",       "Retail Sales",             "monthly"),
    # "pmi_ism_mfg":    ("NAPM",        "ISM Manufacturing PMI",    "monthly"),  # discontinued on FRED
    "leading_index":    ("USSLIND",     "Leading Index (CB)",       "monthly"),
    "unemployment":     ("UNRATE",      "Unemployment Rate",        "monthly"),
    "nfp":              ("PAYEMS",      "Nonfarm Payrolls",         "monthly"),
    "jobless_claims":   ("ICSA",        "Initial Jobless Claims",   "weekly"),

    # Inflation
    "cpi_yoy":          ("CPIAUCSL",    "CPI (All Items)",          "monthly"),
    "core_cpi":         ("CPILFESL",    "Core CPI (ex F&E)",        "monthly"),
    "pce":              ("PCE",         "PCE Price Index",          "monthly"),
    "breakeven_10y":    ("T10YIE",      "10Y Breakeven Inflation",  "daily"),

    # Money & Liquidity
    "m2":               ("M2SL",        "M2 Money Supply",          "weekly"),
    "m2_yoy":           ("M2SL",        "M2 YoY Growth",            "weekly"),   # computed
    "bank_credit":      ("TOTBKCR",     "Total Bank Credit",        "weekly"),

    # Housing
    "housing_starts":   ("HOUST",       "Housing Starts",           "monthly"),
    "case_shiller":     ("CSUSHPISA",   "Case-Shiller HPI",         "monthly"),

    # Global / FX Proxy
    "trade_weighted_usd": ("DTWEXBGS",  "Trade-Weighted USD",       "daily"),
    "oil_wti":            ("DCOILWTICO","WTI Crude Oil Price",       "daily"),
    "gold":               ("GOLDAMGBD228NLBM", "Gold Price (London)", "daily"),
}

# CFTC COT — fetched separately via Quandl/direct download
CFTC_INSTRUMENTS = ["SP500", "NASDAQ", "EURUSD", "GOLD", "WTI", "BONDS_10Y"]

# ── Regime Thresholds ─────────────────────────────────────────────────────────
# All in basis points or index points unless noted
REGIME_THRESHOLDS = {
    "vix": {
        "low":    15.0,    # below = low vol / complacency
        "medium": 20.0,    # 15-20 = neutral
        "high":   25.0,    # above = elevated stress
        "crisis": 35.0,    # above = crisis / vol regime
    },
    "hy_spread": {
        "tight":  300,     # bps — historically tight
        "normal": 450,
        "wide":   600,     # stress
        "crisis": 900,     # 2008/2020 territory
    },
    "yield_curve_10_2": {
        "inverted":  -10,  # bps — confirmed inversion
        "flat":       50,  # bps — flattening / warning
        "normal":    100,
        "steep":     200,
    },
    "unemployment_delta": {
        "improving": -0.3,  # MoM change in pp
        "stable":     0.2,
        "deteriorating": 0.5,
    },
    "breakeven_10y": {
        "anchored":   2.0,  # %
        "elevated":   2.5,
        "unanchored": 3.0,
    },
}

# ── Regime Definitions ────────────────────────────────────────────────────────
REGIME_COLORS = {
    "RISK_ON_LOW_VOL":     "#00C851",   # green
    "RISK_ON_ELEVATED_VOL": "#ffbb33",  # amber
    "NEUTRAL":             "#33b5e5",   # blue
    "CAUTION":             "#FF8800",   # orange
    "RISK_OFF_STRESS":     "#ff4444",   # red
    "CRISIS":              "#CC0000",   # deep red
}

# ── Dashboard ─────────────────────────────────────────────────────────────────
DASHBOARD_HOST = "127.0.0.1"
DASHBOARD_PORT = 8050
DASHBOARD_REFRESH_SECONDS = 3600   # 1 hour for EOD data

CHART_BASE_LAYOUT = dict(
    template="plotly_dark",
    paper_bgcolor="#1a1a2e",
    plot_bgcolor="#1a1a2e",
    font=dict(color="#e0e0e0"),
    margin=dict(l=40, r=20, t=40, b=30),
)

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_PATH = "logs/phase1.log"
LOG_LEVEL = "INFO"
