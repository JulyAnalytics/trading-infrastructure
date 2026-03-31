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
OUTPUTS_DIR = "data/outputs"

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
    "forward_breakeven_5y5y": ("T5YIFR", "5Y5Y Forward Inflation Breakeven", "daily"),

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

# ── Phase 2: Staleness Thresholds ─────────────────────────────────────────────
# Threshold is set on the PRIMARY series for each component.
# Note: Labor threshold uses claims cadence (weekly), not unemployment (monthly).
STALENESS_THRESHOLDS_DAYS = {
    "vol":         3,    # VIX: daily (3d accounts for weekends)
    "credit":      3,    # HY spread: daily
    "curve":       3,    # yield curve: daily
    "inflation":   3,    # breakeven: daily
    "labor":       10,   # claims: weekly (primary signal; faster than unemployment)
    "positioning": 10,   # COT: weekly + ~3-day publication lag
}

# Separate threshold for the unemployment LEVEL within Labor
UNEMPLOYMENT_STALE_DAYS = 45   # monthly with FRED lag

# ── Phase 2: Divergence Detection Thresholds ──────────────────────────────────
# Set a priori — calibrate after backfill using scripts/calibrate_divergence_threshold.py
# Yield Curve collinearity note: 10Y-2Y and 10Y-3M are highly collinear.
# Yield Curve represents one independent signal with a timing offset, not two.
DIVERGENCE_THRESHOLD_VC = 0.6    # Vol/Credit spread
DIVERGENCE_THRESHOLD_VL = 0.7    # Vol/Labor spread
DIVERGENCE_MIN_CREDIT_STRESS = 0.1  # Credit must be <= this for LABOR_LAG_WARNING

# ── Phase 4: Component Weights (mirrors RegimeClassifier.WEIGHTS) ─────────────
# Kept here so dashboard and snapshot generator can read weights without
# importing the classifier (avoids circular imports and heavy deps at startup).
COMPONENT_WEIGHTS = {
    "vol":         0.25,
    "credit":      0.25,
    "curve":       0.20,
    "inflation":   0.10,
    "labor":       0.15,
    "positioning": 0.05,
}

# ── Sarah: Vol Surface Layer ──────────────────────────────────────────────────
# Separate DuckDB for vol surface data (keeps macro.db unmodified)
VOL_DB_PATH = "data/processed/trading.db"

# Tickers for daily vol surface ingestion
VOL_TICKERS = ["SPY", "QQQ", "IWM", "XLE", "GLD"]

# FRED series for DTE-matched risk-free rate (3-month T-bill as default proxy)
FRED_RISK_FREE_SERIES = "DGS3MO"

# Minimum history days before IVR/IVP is considered reliable
VOL_IVR_MIN_HISTORY_DAYS = 60

# ── Sarah: Stage 4 Pre-Trade Dashboard ───────────────────────────────────────
# Catalyst type enum for term structure analysis (replaces direction label)
CATALYST_TYPES = ("macro_slow", "macro_catalyst", "event_specific", "technical")

# Flow observation notes field max length
MAX_FLOW_NOTES_LENGTH = 200

# ── Sarah: Stage 5 Historical Regime Library ─────────────────────────────────
# Minimum history days before analog search results are trusted
ANALOG_MIN_HISTORY_DAYS = 120

# Minimum VVIX history days before VVIX included in feature vector
VVIX_CONFIDENCE_MIN_DAYS = 504  # ~2 years of trading days

# ── Phase 4: FOMC Schedule 2026 ───────────────────────────────────────────────
FOMC_SCHEDULE_2026 = [
    "2026-01-29", "2026-03-18", "2026-05-06",
    "2026-06-17", "2026-07-29", "2026-09-16",
    "2026-10-28", "2026-12-16",
]
