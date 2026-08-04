"""
Root configuration.

v1.0 split:
  - Infrastructure literals (paths, API keys, series definitions, ports,
    chart styling) live HERE and only here.
  - Every TUNABLE (thresholds, weights, windows, gates, scenario libraries,
    schedules) lives in the versioned parameter registry — systems/params.
    Edit them through the GUI / systems.params.set_params(), never in code.

Legacy imports keep working: `from config import REGIME_THRESHOLDS` resolves
through the registry (PEP 562 __getattr__ below) against the ACTIVE version.
Note that `from config import X` binds at the importing module's import time —
long-running processes pick up parameter edits on their next fresh process,
while code that calls systems.params.get_params() directly sees edits live.
The registry seeds itself from code defaults (systems/params/models.py) on
first use, so a fresh checkout behaves exactly like v0.5.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# ── API Keys ──────────────────────────────────────────────────────────────────
FRED_API_KEY = os.getenv("FRED_API_KEY", "")   # free at fred.stlouisfed.org/docs/api

# ── Databases & Paths ─────────────────────────────────────────────────────────
DUCKDB_PATH = "data/processed/macro.db"
VOL_DB_PATH = "data/processed/trading.db"      # Sarah + research + parameter registry
OUTPUTS_DIR = "data/outputs"

# ── FRED Series ───────────────────────────────────────────────────────────────
# Format: { internal_name: (fred_series_id, human_label, update_frequency) }
# Series *definitions* are data plumbing and stay here; per-series enable/disable
# lives in the registry (DataParams.macro_series_disabled).
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
    # NOTE: the LBMA London gold series (GOLDAMGBD228NLBM) was discontinued by
    # FRED and returned "series does not exist" on every fetch. Removed — gold
    # is not consumed by the regime classifier. If gold data is wanted, source
    # it via yfinance (GLD / GC=F) the way SPY equity is (macro_feed.fetch_equity_data).
}

# ── Regime Presentation (colors are styling, not tunables) ───────────────────
REGIME_COLORS = {
    "RISK_ON_LOW_VOL":     "#00C851",   # green
    "RISK_ON_ELEVATED_VOL": "#ffbb33",  # amber
    "NEUTRAL":             "#33b5e5",   # blue
    "CAUTION":             "#FF8800",   # orange
    "RISK_OFF_STRESS":     "#ff4444",   # red
    "CRISIS":              "#CC0000",   # deep red
}

# ── Servers ───────────────────────────────────────────────────────────────────
DASHBOARD_HOST = "127.0.0.1"     # legacy Dash app (retired after Phase 2)
DASHBOARD_PORT = 8050
API_HOST = "127.0.0.1"           # v1.0 FastAPI service layer
API_PORT = 8100
RCS_BASE_URL = "http://localhost:8099"   # Research Capture System (read-only bridge)

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

# ── MLflow / Research infrastructure ─────────────────────────────────────────
from pathlib import Path as _Path

# MLflow — absolute path to prevent fragmentation across working directories
MLFLOW_TRACKING_URI = str(_Path(OUTPUTS_DIR).resolve().parent / "mlruns")
MLFLOW_EXPERIMENT_NAME = "priya_research"

# Hypothesis registry — stored in DuckDB for consistency with all other
# persistent state. Table created in trading.db alongside Sarah's tables.
HYPOTHESIS_REGISTRY_DB = VOL_DB_PATH  # trading.db — shared research DB

# RCS SQLite (read-only from this repo — see systems/risk RCS bridge).
# The live RCS app configures its own DB location in research/.env (the path was
# moved out of the repo to ~/.local/state/rcs/ to avoid Nextcloud generating WAL
# conflict copies). RCS owns its DB location, so follow it: resolve db_path from
# the RCS .env, falling back to the in-repo default if the .env or key is absent.
# Resolving directly to the live path (rather than symlinking the in-repo copy)
# keeps -wal/-shm next to the target and avoids re-creating the Nextcloud sync
# problem that prompted the split in the first place.
def _resolve_rcs_db_path() -> str:
    rcs_env = os.path.expanduser(
        "~/Nextcloud/Trading/research-capture-system/research/.env"
    )
    try:
        from dotenv import dotenv_values

        db_path = dotenv_values(rcs_env).get("db_path")
        if db_path:
            return os.path.expanduser(db_path)
    except Exception:
        pass
    return os.path.expanduser(
        "~/Nextcloud/Trading/research-capture-system/research/data/research.db"
    )


RCS_DB_PATH = _resolve_rcs_db_path()


# ── Tunables — resolved from the parameter registry ──────────────────────────
# REGIME_THRESHOLDS, COMPONENT_WEIGHTS, STALENESS_THRESHOLDS_DAYS,
# DIVERGENCE_*, VOL_TICKERS, CATALYST_TYPES, BACKTEST_*, CPCV_*, SPREAD_FLOOR_*,
# TRIPLE_BARRIER_*, VOL_CONE_*, FRACDIFF_*, SHARPE_*, MC_DEFAULT_N_PATHS,
# FOMC_SCHEDULE_2026, CFTC_INSTRUMENTS, DASHBOARD_REFRESH_SECONDS, …
# Full name → registry field map: systems/params/compat.py

def __getattr__(name):
    from systems.params import REGISTRY_BACKED_NAMES, config_value
    if name in REGISTRY_BACKED_NAMES:
        return config_value(name)
    raise AttributeError(f"module 'config' has no attribute {name!r}")


def __dir__():
    from systems.params import REGISTRY_BACKED_NAMES
    return sorted(list(globals().keys()) + list(REGISTRY_BACKED_NAMES))
