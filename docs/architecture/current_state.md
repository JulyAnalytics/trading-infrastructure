# Trading Infrastructure — Ground Truth Architecture
**Generated:** 2026-03-29
**Status snapshot against:** zero_dollar_stack_and_build_sequence_1.md

---

## Zero Dollar Stack: Phase Completion Status

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 0** | Environment + directory structure + database | ✅ Complete |
| **Phase 1** | Marcus: Macro data pipeline + regime classifier + dashboard | ✅ Complete (with Phase 2 enhancements merged in) |
| **Phase 2** | Sarah: Vol surface layer (options_feed.py, vol_surface.py, vol signals) | ❌ Not started — `systems/data_feeds/` contains only `macro_feed.py`; no options data pipeline |
| **Phase 3** | Priya: Research backtesting framework (VectorBT, MLflow, options backtester) | ❌ Not started — `research/` directories are empty |
| **Phase 4** | Jordan: Risk layer (Greeks aggregation, risk limits, Grafana) | ❌ Not started — `systems/risk/` directory exists but is empty |
| **Phase 5** | Kai: Execution layer (IBKR connector, TCA tracker) | ❌ Not started — `systems/execution/` directory exists but is empty |
| **Phase 6** | Alex: Orchestration / weekly review system | ⚠️ Framework only — scheduler.py exists; no weekly report generator |
| **Phase 7** | Sam: Trade log + P&L attribution + operations layer | ❌ Not started — schema placeholder only in db_init.py |

**Phase 1 depth achieved beyond the build sequence spec:**
- Divergence detection (Vol/Credit/Labor signal tiers) — Phase 2 spec feature
- Attribution analysis (drivers, contradictors, flip-watch)
- Regime change probability scoring
- Data staleness tracking per component
- Regime persistence statistics
- Regime-conditional return statistics (compute_regime_return_stats.py)
- PDF snapshot generation (systems/reports/snapshot_generator.py)
- Macro calendar integration (FOMC schedule, release dates)
- COT positioning data pipeline

---

## 1. Directory Tree

```
trading-infrastructure/
├── config.py                          ← Phase 1 master config (thresholds, series IDs)
├── scheduler.py                       ← Daily/weekly pipeline orchestrator
├── requirements.txt
├── README.md
├── setup.sh
├── CLAUDE.md
├── .env                               ← Not committed; contains FRED_API_KEY
├── .python-version
├── .claude/
│   └── settings.local.json
├── FinFutYY.txt                       ← Unknown — not referenced by any .py file
├── annualof.txt                       ← Unknown — not referenced by any .py file
│
├── data/
│   ├── processed/
│   │   ├── macro.db                   ← Primary DuckDB (used by Phase 1 pipeline)
│   │   └── main.db                   ← Phase 0 DuckDB (created by systems/db_init.py)
│   ├── snapshots/
│   │   ├── macro_2026-03-11_113131.pdf
│   │   ├── macro_2026-03-11_120047.pdf
│   │   ├── macro_2026-03-11_120259.pdf
│   │   └── macro_2026-03-11_120739.pdf
│   ├── raw/                           ← Empty (excluded from git)
│   ├── cache/                         ← Empty (excluded from git)
│   └── [outputs/ does not exist]      ← No data/outputs/ directory
│
├── logs/
│   └── cron.log
│
├── docs/
│   └── architecture/
│       └── current_state.md           ← This file
│
├── reports/                           ← Empty
│
├── research/
│   ├── signals/                       ← Empty — Phase 2/3 work not started
│   ├── strategies/                    ← Empty
│   └── archive/                       ← Empty
│
├── scripts/
│   ├── cron_pipeline.sh
│   ├── cron_weekly.sh
│   ├── check_data.py
│   ├── verify_phase0.py
│   ├── backfill_regime_history.py
│   ├── calibrate_divergence_threshold.py
│   └── compute_regime_return_stats.py
│
└── systems/
    ├── __init__.py                    ← Empty
    ├── config.py                      ← Phase 0 env-var loader (different from root config.py)
    ├── db_init.py                     ← Phase 0 schema initializer (targets main.db)
    ├── data_feeds/
    │   ├── __init__.py
    │   └── macro_feed.py
    ├── signals/
    │   ├── __init__.py
    │   └── regime_classifier.py
    ├── dashboard/
    │   ├── __init__.py
    │   ├── macro_dashboard.py
    │   └── assets/
    │       └── custom.css
    ├── reports/
    │   ├── __init__.py
    │   └── snapshot_generator.py
    ├── utils/
    │   ├── __init__.py
    │   └── db.py
    ├── execution/                     ← Empty — Phase 5 not started
    └── risk/                          ← Empty — Phase 4 not started
```

---

## 2. Component Inventory

### `config.py` (project root)
**What it does:** Master configuration for the Phase 1 pipeline. Defines all FRED series IDs, regime thresholds, dashboard settings, staleness thresholds, divergence thresholds, component weights, and FOMC schedule. All other Phase 1 modules import from this file.

**Exposes:** `FRED_API_KEY`, `DUCKDB_PATH`, `MACRO_SERIES`, `CFTC_INSTRUMENTS`, `REGIME_THRESHOLDS`, `REGIME_COLORS`, `DASHBOARD_HOST`, `DASHBOARD_PORT`, `DASHBOARD_REFRESH_SECONDS`, `CHART_BASE_LAYOUT`, `LOG_PATH`, `LOG_LEVEL`, `STALENESS_THRESHOLDS_DAYS`, `UNEMPLOYMENT_STALE_DAYS`, `DIVERGENCE_THRESHOLD_VC`, `DIVERGENCE_THRESHOLD_VL`, `DIVERGENCE_MIN_CREDIT_STRESS`, `COMPONENT_WEIGHTS`, `FOMC_SCHEDULE_2026`

**Imports from project:** None (only stdlib + dotenv)

**External deps:** `os`, `python-dotenv`

---

### `systems/config.py`
**What it does:** Minimal Phase 0 env-var loader. Exposes API keys and `DB_PATH` (defaults to `data/processed/main.db`). Includes a `validate()` function to check required keys before startup.

**Exposes:** `FRED_API_KEY`, `POLYGON_API_KEY`, `NASDAQ_DATA_LINK_KEY`, `DB_PATH`, `POSTGRES_URL`, `validate()`

**Imports from project:** None

**External deps:** `os`, `python-dotenv`

**⚠️ Inconsistency:** `systems/config.py` defaults `DB_PATH` to `data/processed/main.db`, but the Phase 1 pipeline (via root `config.py`) uses `DUCKDB_PATH = "data/processed/macro.db"`. Both databases exist on disk. Phase 1 code imports from root `config.py`, not `systems/config.py`.

---

### `systems/db_init.py`
**What it does:** Phase 0 database initializer. Creates `main.db` with the Phase 0 table schema (simple `macro_series`, `options_chains`, `vol_signals`, `trade_log`). Entry point via `if __name__ == "__main__"`.

**Exposes:** `init_db(db_path)`

**Imports from project:** `systems/config.py` (for `DB_PATH`)

**External deps:** `os`, `duckdb`, `python-dotenv`

---

### `systems/utils/db.py`
**What it does:** DuckDB connection management and schema initialization for the Phase 1 pipeline. Creates and manages `macro.db`. Provides upsert logic with automatic z-score and percentage-change computation on insert.

**Exposes:**
- `get_connection(db_path) -> duckdb.DuckDBPyConnection`
- `initialize_schema(conn)` — creates all Phase 1 tables (idempotent, uses IF NOT EXISTS + ADD COLUMN IF NOT EXISTS)
- `upsert_series(conn, series_id, series_name, df)` — insert/replace with computed pct_chg and z-scores
- `get_latest(conn, series_id) -> dict | None`
- `get_series_history(conn, series_id, days=756) -> pd.DataFrame`

**Imports from project:** `config` (root)

**External deps:** `duckdb`, `pandas`, `numpy`, `loguru`

---

### `systems/data_feeds/macro_feed.py`
**What it does:** All data ingestion for the Phase 1 pipeline — FRED series, CFTC COT data, macro calendar events, and SPY equity price history. Supports incremental (last 90 days) and full-history modes.

**Exposes:**
- `build_fred_client() -> Fred`
- `fetch_series(fred, series_id, full_history=False) -> pd.Series`
- `run_fred_pipeline(full_history=False)` — main FRED ingest loop
- `compute_derived_series(conn)` — M2 YoY growth, SPY drawdown from 252d peak
- `fetch_cot_data(conn)` — CFTC positioning via `cot-reports` library
- `fetch_calendar_data(conn)` — FRED release dates + FOMC schedule (next 45 days)
- `fetch_equity_data(conn, ticker="SPY", start="2017-01-01")` — via yfinance

**Imports from project:** `config` (root), `systems.utils.db`

**External deps:** `fredapi`, `pandas`, `numpy`, `duckdb`, `yfinance`, `cot-reports`, `loguru`, `requests`

---

### `systems/signals/regime_classifier.py`
**What it does:** Converts current macro readings into a discrete regime classification with component scores, confidence level, divergence signals, attribution, and regime change probability. The core analytical engine of the system.

**Exposes:**
- `MacroSnapshot` (dataclass) — current readings for all regime inputs
- `RegimeResult` (dataclass) — full classification output
- `RegimeClassifier` (class):
  - `classify(persist=True) -> RegimeResult` — run classification from DB
  - `classify_from_df(macro_df, cot_df, date) -> RegimeResult` — backfill mode
  - `get_history(days=252) -> pd.DataFrame`
  - `attribution(result) -> dict` — drivers, contradictors, flip-watch
  - `regime_change_probability(result) -> dict` — ~30d transition probability

**Component scorers (internal):**
- `_score_vol()` — VIX level + z-score (weight: 25%)
- `_score_credit()` — HY spread level (weight: 25%)
- `_score_curve()` — yield curve shape (weight: 20%)
- `_score_inflation()` — breakeven + real rates (weight: 10%)
- `_score_labor()` — unemployment + jobless claims (weight: 15%)
- `_score_positioning()` — COT SP500 z-score, contrarian (weight: 5%)

**Regime mapping:** Composite score → `RISK_ON_LOW_VOL` / `RISK_ON_ELEVATED_VOL` / `NEUTRAL` / `CAUTION` / `RISK_OFF_STRESS` / `CRISIS`

**Divergence signals:** `LEADING_STRESS_WARNING`, `ELEVATED_VOL_UNCONFIRMED`, `LABOR_LAG_WARNING`, `BROAD_COMPONENT_DIVERGENCE`

**Imports from project:** `config` (root), `systems.utils.db`

**External deps:** `duckdb`, `pandas`, `numpy`, `loguru`

---

### `systems/dashboard/macro_dashboard.py`
**What it does:** Interactive Dash web application for the macro regime dashboard. Runs at `http://127.0.0.1:8050`. Rebuilds all UI components on a 1-hour interval or on-demand. Full read-only visualization layer over the DuckDB data.

**Exposes:** Dash `app` object; no importable API (entry point only)

**Key internal functions:**
- `get_regime_result() -> RegimeResult`
- `get_regime_history_df(days=756) -> pd.DataFrame`
- `get_component_history_df(days=30) -> pd.DataFrame`
- `get_transition_log_df() -> pd.DataFrame`
- `get_days_in_current_regime() -> int`
- `get_regime_persistence_stats() -> dict`
- `get_cot_df() -> pd.DataFrame`
- `build_vix_chart()`, `build_hy_chart()`, `build_curve_chart()`, `build_divergence_chart()`, `build_regime_history_chart()`, `build_drawdown_chart()`
- `build_regime_card()`, `build_signals_card()`, `build_attribution_panel()`, `build_component_scores_row()`
- `refresh_all()` — master Dash callback

**Dashboard sections:**
- Left sidebar: Regime card, signal feed, COT positioning table, regime transitions, macro calendar
- Right content: Divergence banner, component score bars + sparklines, regime history chart, attribution panel, tabbed charts (VIX, HY, curve, divergence, return stats, validation)

**Imports from project:** `config` (root), `systems.utils.db`, `systems.signals.regime_classifier`

**External deps:** `dash`, `dash-bootstrap-components`, `plotly`, `pandas`, `numpy`, `loguru`

---

### `systems/reports/snapshot_generator.py`
**What it does:** Generates standalone PDF snapshots of the regime state without requiring the Dash server. Used by the nightly scheduler and the dashboard's export button.

**Exposes:**
- `generate_snapshot(output_path=None, return_bytes=False) -> str | bytes`

**PDF contents:** Regime header, component scores chart, regime history chart, persistence stats, upcoming catalysts table, attribution summary, disclaimer footer.

**Output location:** `data/snapshots/macro_YYYY-MM-DD_HHMMSS.pdf`

**Imports from project:** `config` (root), `systems.utils.db`, `systems.signals.regime_classifier`

**External deps:** `reportlab`, `matplotlib`, `pandas`, `numpy`, `loguru`

---

### `scheduler.py` (project root)
**What it does:** Daily pipeline orchestrator using the `schedule` library. Runs immediately on startup, then enters a blocking schedule loop.

**Schedule:**
- Weekdays 18:05 ET: `run_daily_pipeline()` — FRED fetch → derived series → regime classify → snapshot
- Sunday 20:00: `run_weekly_full_refresh()` — full FRED history pull
- Sunday 20:05: `fetch_calendar_data()`
- Daily 18:05: `fetch_equity_data()` (SPY)
- Weekdays 18:15: `run_nightly_snapshot()`

**Imports from project:** `systems.data_feeds.macro_feed`, `systems.signals.regime_classifier`, `systems.reports.snapshot_generator`, `systems.utils.db`, `config`

**External deps:** `schedule`, `loguru`

---

### `scripts/check_data.py`
**What it does:** Diagnostic tool — queries `macro.db` and prints freshness of key series (VIX, HY spread, yield curves, unemployment, SPY). Shows days since last update and last cron run time.

**Entry point:** Yes (`if __name__ == "__main__"`)

**Imports from project:** `config` (root), `systems.utils.db`

---

### `scripts/verify_phase0.py`
**What it does:** Pre-Phase 1 verification checklist. Checks Python 3.11+, required packages importable, database setup, `.env` keys. Exits 0 if all pass, 1 if any fail.

**Entry point:** Yes

**Imports from project:** `config` (root), `systems.utils.db`

---

### `scripts/backfill_regime_history.py`
**What it does:** One-time script to populate `regime_history` for all dates in `macro_series` from 2018-01-01 onwards. Uses `classify_from_df()` to avoid N DB round-trips.

**Entry point:** Yes

**Imports from project:** `config` (root), `systems.utils.db`, `systems.signals.regime_classifier`

---

### `scripts/compute_regime_return_stats.py`
**What it does:** Computes regime-conditional median and percentile forward returns for SPY, TLT, GLD, HYG, UUP at 1M and 3M horizons. Writes results to `regime_return_stats` table. Flags observations < 20 as unreliable.

**Entry point:** Yes

**Imports from project:** `config` (root), `systems.utils.db`

**External deps:** `yfinance`, `pandas`, `numpy`

---

### `scripts/calibrate_divergence_threshold.py`
**What it does:** Cannot fully determine from exploration — referenced in `config.py` comments as the tool to calibrate `DIVERGENCE_THRESHOLD_VC` and `DIVERGENCE_THRESHOLD_VL` thresholds empirically after backfill.

**Entry point:** Likely yes

---

## 3. Output Contracts

**`data/outputs/` does not exist.** The codebase writes to `data/snapshots/` (PDFs) and `data/processed/macro.db` (database tables). There is no `data/outputs/` directory.

**Actual outputs:**

| Location | What writes it | Format | Contents |
|----------|---------------|--------|----------|
| `data/snapshots/macro_YYYY-MM-DD_HHMMSS.pdf` | `snapshot_generator.py` | PDF | Regime state, component scores chart, history chart, persistence stats, calendar, attribution |
| `data/processed/macro.db` | `db.py`, `macro_feed.py`, `regime_classifier.py` | DuckDB | All tables (see Section 4) |
| `logs/cron.log` | `scheduler.py` via loguru | Text | Pipeline run logs with timestamps |

---

## 4. DB Schema

### Database: `data/processed/macro.db` (Phase 1 — active)
Created and managed by `systems/utils/db.py`.

#### `macro_series`
```
series_id       VARCHAR   — internal name key (e.g. "vix", "hy_spread")
series_name     VARCHAR   — human label
date            DATE
value           DOUBLE
pct_chg_1m      DOUBLE    — computed on upsert
pct_chg_3m      DOUBLE    — computed on upsert
pct_chg_12m     DOUBLE    — computed on upsert
z_score_1y      DOUBLE    — computed on upsert (252-day rolling)
z_score_5y      DOUBLE    — computed on upsert (1260-day rolling)
PRIMARY KEY (series_id, date)
```

#### `regime_history`
```
date                DATE      PRIMARY KEY
regime              VARCHAR   — e.g. "RISK_ON_LOW_VOL"
composite_score     DOUBLE    — -1 to +1
confidence          VARCHAR   — "LOW" / "MEDIUM" / "HIGH"
vol_score           DOUBLE
credit_score        DOUBLE
curve_score         DOUBLE
inflation_score     DOUBLE
labor_score         DOUBLE
positioning_score   DOUBLE
vol_as_of           DATE
credit_as_of        DATE
curve_as_of         DATE
inflation_as_of     DATE
labor_as_of         DATE
positioning_as_of   DATE
divergence_type     VARCHAR   — NULL or divergence signal name
divergence_severity VARCHAR   — NULL / "LOW" / "MEDIUM" / "HIGH"
```

#### `cot_positioning`
```
instrument      VARCHAR
date            DATE
net_spec        DOUBLE    — net speculative contracts
net_spec_pct    DOUBLE    — as % of open interest
z_score_1y      DOUBLE
z_score_3y      DOUBLE
PRIMARY KEY (instrument, date)
```

#### `fetch_log`
```
series_id       VARCHAR
fetched_at      TIMESTAMP
rows_updated    INTEGER
status          VARCHAR   — "ok" / "error"
error_msg       VARCHAR
```

#### `macro_calendar`
```
event_name      VARCHAR
event_date      DATE
category        VARCHAR
importance      VARCHAR
component       VARCHAR   — which regime component this affects
source          VARCHAR
```

#### `regime_return_stats`
```
regime          VARCHAR
asset           VARCHAR   — "SPY" / "TLT" / "GLD" / "HYG" / "UUP"
horizon         VARCHAR   — "1M" / "3M"
median_return   DOUBLE
p25_return      DOUBLE
p75_return      DOUBLE
n_observations  INTEGER
```

---

### Database: `data/processed/main.db` (Phase 0 — superseded)
Created by `systems/db_init.py`. Uses a simpler schema designed before the Phase 1 build. Not actively written to by any scheduled pipeline.

#### `macro_series` (Phase 0 version — different schema)
```
date        DATE NOT NULL
series_name VARCHAR NOT NULL
value       DOUBLE
updated_at  TIMESTAMP DEFAULT current_timestamp
```
*(No series_id, no z-scores, no pct_chg columns — incompatible with Phase 1 schema)*

#### `options_chains`
```
date          DATE
ticker        VARCHAR
expiration    DATE
strike        DOUBLE
option_type   VARCHAR
bid           DOUBLE
ask           DOUBLE
iv            DOUBLE
volume        INTEGER
open_interest INTEGER
```
*(Placeholder for Phase 2 — not yet populated)*

#### `vol_signals`
```
date           DATE
ticker         VARCHAR
atm_iv         DOUBLE
skew_25d       DOUBLE
iv_rank        DOUBLE
iv_percentile  DOUBLE
```
*(Placeholder for Phase 2 — not yet populated)*

#### `trade_log`
```
trade_id        UUID
timestamp       TIMESTAMP
strategy        VARCHAR
contract        VARCHAR
action          VARCHAR
quantity        INTEGER
fill_price      DOUBLE
regime_at_entry VARCHAR
```
*(Placeholder for Phase 7 — not yet populated)*

---

## 5. Entry Points

Files with `if __name__ == "__main__"`:

| File | What it does when run directly |
|------|-------------------------------|
| `scheduler.py` | Starts the daily/weekly pipeline scheduler loop |
| `systems/db_init.py` | Initializes `main.db` with Phase 0 schema |
| `systems/utils/db.py` | Prints `"Database ready."` — smoke test for Phase 1 DB |
| `systems/data_feeds/macro_feed.py` | Runs incremental FRED fetch (or full/single-series with flags) |
| `systems/signals/regime_classifier.py` | Runs single classification and prints result |
| `systems/dashboard/macro_dashboard.py` | Starts Dash server at http://127.0.0.1:8050 |
| `systems/reports/snapshot_generator.py` | Generates one PDF snapshot |
| `scripts/check_data.py` | Prints data freshness diagnostic |
| `scripts/verify_phase0.py` | Runs Phase 0 verification checklist |
| `scripts/backfill_regime_history.py` | Backfills regime_history from 2018-01-01 |
| `scripts/compute_regime_return_stats.py` | Computes regime-conditional return stats |
| `scripts/calibrate_divergence_threshold.py` | Calibrates divergence thresholds (purpose inferred) |

---

## 6. Broken or Incomplete Items

### Import mismatches / missing files

| File | Import | Issue |
|------|--------|-------|
| Any file that does `from config import` | Relies on `sys.path` having project root | Works if run from project root or via scheduler; may fail if run from a subdirectory without the sys.path insert |
| `systems/dashboard/macro_dashboard.py` | `from systems.signals.regime_classifier import RegimeClassifier` | OK if run from project root |

*No imports found that reference files that do not exist.*

### Empty placeholder directories
- `systems/execution/` — no files; Phase 5 not started
- `systems/risk/` — no files; Phase 4 not started
- `research/signals/` — no files
- `research/strategies/` — no files
- `research/archive/` — no files

### Two config.py files with divergent DB paths
- `config.py` (root): `DUCKDB_PATH = "data/processed/macro.db"`
- `systems/config.py`: `DB_PATH = "data/processed/main.db"`
- Both databases exist on disk. Phase 1 code correctly uses root `config.py` → `macro.db`. Phase 0 `db_init.py` uses `systems/config.py` → `main.db`. **Risk:** any new code that imports `from systems.config import DB_PATH` will target the wrong database.

### Two databases with incompatible `macro_series` schemas
- `macro.db` has the Phase 1 schema (series_id, z-scores, pct_chg columns)
- `main.db` has the Phase 0 schema (no series_id, no derived columns)
- They cannot be used interchangeably

### `data/outputs/` does not exist
- No code references this path. Snapshots go to `data/snapshots/`. If downstream tooling expects `data/outputs/`, it will fail.

### `FinFutYY.txt` and `annualof.txt`
- Present at project root; not imported or referenced by any `.py` file found. Purpose unknown.

### TODOs and placeholders found

| File | Location | Note |
|------|----------|------|
| `config.py` (root) | `# "move_index": ("BAMLMOVE", ...)` | MOVE index commented out — "not on FRED" |
| `config.py` (root) | `# "pmi_ism_mfg": ("NAPM", ...)` | ISM PMI commented out — "discontinued on FRED" |
| `config.py` (root) | `DIVERGENCE_THRESHOLD_VC = 0.6` | Comment: "Set a priori — calibrate after backfill" |
| `systems/db_init.py` | `options_chains`, `vol_signals`, `trade_log` tables | Schema placeholders for Phases 2, 3, 7 — not populated |
| Build sequence doc | Phases 2–7 | Full implementation not started |

---

## 7. config.py Inventory (project root)

| Constant | Type | Value |
|----------|------|-------|
| `FRED_API_KEY` | `str` | `os.getenv("FRED_API_KEY", "")` — from `.env` |
| `DUCKDB_PATH` | `str` | `"data/processed/macro.db"` |
| `MACRO_SERIES` | `dict[str, tuple]` | 25 entries — format: `{internal_name: (fred_id, label, frequency)}` |
| `CFTC_INSTRUMENTS` | `list[str]` | `["SP500", "NASDAQ", "EURUSD", "GOLD", "WTI", "BONDS_10Y"]` |
| `REGIME_THRESHOLDS["vix"]["low"]` | `float` | `15.0` |
| `REGIME_THRESHOLDS["vix"]["medium"]` | `float` | `20.0` |
| `REGIME_THRESHOLDS["vix"]["high"]` | `float` | `25.0` |
| `REGIME_THRESHOLDS["vix"]["crisis"]` | `float` | `35.0` |
| `REGIME_THRESHOLDS["hy_spread"]["tight"]` | `int` | `300` (bps) |
| `REGIME_THRESHOLDS["hy_spread"]["normal"]` | `int` | `450` (bps) |
| `REGIME_THRESHOLDS["hy_spread"]["wide"]` | `int` | `600` (bps) |
| `REGIME_THRESHOLDS["hy_spread"]["crisis"]` | `int` | `900` (bps) |
| `REGIME_THRESHOLDS["yield_curve_10_2"]["inverted"]` | `int` | `-10` (bps) |
| `REGIME_THRESHOLDS["yield_curve_10_2"]["flat"]` | `int` | `50` (bps) |
| `REGIME_THRESHOLDS["yield_curve_10_2"]["normal"]` | `int` | `100` (bps) |
| `REGIME_THRESHOLDS["yield_curve_10_2"]["steep"]` | `int` | `200` (bps) |
| `REGIME_THRESHOLDS["unemployment_delta"]["improving"]` | `float` | `-0.3` (pp MoM) |
| `REGIME_THRESHOLDS["unemployment_delta"]["stable"]` | `float` | `0.2` (pp MoM) |
| `REGIME_THRESHOLDS["unemployment_delta"]["deteriorating"]` | `float` | `0.5` (pp MoM) |
| `REGIME_THRESHOLDS["breakeven_10y"]["anchored"]` | `float` | `2.0` (%) |
| `REGIME_THRESHOLDS["breakeven_10y"]["elevated"]` | `float` | `2.5` (%) |
| `REGIME_THRESHOLDS["breakeven_10y"]["unanchored"]` | `float` | `3.0` (%) |
| `REGIME_COLORS["RISK_ON_LOW_VOL"]` | `str` | `"#00C851"` (green) |
| `REGIME_COLORS["RISK_ON_ELEVATED_VOL"]` | `str` | `"#ffbb33"` (amber) |
| `REGIME_COLORS["NEUTRAL"]` | `str` | `"#33b5e5"` (blue) |
| `REGIME_COLORS["CAUTION"]` | `str` | `"#FF8800"` (orange) |
| `REGIME_COLORS["RISK_OFF_STRESS"]` | `str` | `"#ff4444"` (red) |
| `REGIME_COLORS["CRISIS"]` | `str` | `"#CC0000"` (deep red) |
| `DASHBOARD_HOST` | `str` | `"127.0.0.1"` |
| `DASHBOARD_PORT` | `int` | `8050` |
| `DASHBOARD_REFRESH_SECONDS` | `int` | `3600` |
| `CHART_BASE_LAYOUT` | `dict` | plotly_dark template, `#1a1a2e` bg, `#e0e0e0` font |
| `LOG_PATH` | `str` | `"logs/phase1.log"` |
| `LOG_LEVEL` | `str` | `"INFO"` |
| `STALENESS_THRESHOLDS_DAYS["vol"]` | `int` | `3` |
| `STALENESS_THRESHOLDS_DAYS["credit"]` | `int` | `3` |
| `STALENESS_THRESHOLDS_DAYS["curve"]` | `int` | `3` |
| `STALENESS_THRESHOLDS_DAYS["inflation"]` | `int` | `3` |
| `STALENESS_THRESHOLDS_DAYS["labor"]` | `int` | `10` |
| `STALENESS_THRESHOLDS_DAYS["positioning"]` | `int` | `10` |
| `UNEMPLOYMENT_STALE_DAYS` | `int` | `45` |
| `DIVERGENCE_THRESHOLD_VC` | `float` | `0.6` |
| `DIVERGENCE_THRESHOLD_VL` | `float` | `0.7` |
| `DIVERGENCE_MIN_CREDIT_STRESS` | `float` | `0.1` |
| `COMPONENT_WEIGHTS["vol"]` | `float` | `0.25` |
| `COMPONENT_WEIGHTS["credit"]` | `float` | `0.25` |
| `COMPONENT_WEIGHTS["curve"]` | `float` | `0.20` |
| `COMPONENT_WEIGHTS["inflation"]` | `float` | `0.10` |
| `COMPONENT_WEIGHTS["labor"]` | `float` | `0.15` |
| `COMPONENT_WEIGHTS["positioning"]` | `float` | `0.05` |
| `FOMC_SCHEDULE_2026` | `list[str]` | 8 dates: Jan 29, Mar 18, May 6, Jun 17, Jul 29, Sep 16, Oct 28, Dec 16 |

**config.py vs code inconsistencies:**
- `LOG_PATH = "logs/phase1.log"` — scheduler.py creates its own loguru logger at `logs/scheduler.log` (or similar). Whether anything actually writes to `logs/phase1.log` is not confirmed; `cron.log` is what exists on disk.
- `COMPONENT_WEIGHTS` is duplicated between `config.py` and `RegimeClassifier.WEIGHTS` inside `regime_classifier.py`. The comment in config.py says "mirrors RegimeClassifier.WEIGHTS" — these must be kept in sync manually. If they diverge, the dashboard will display different weights than the classifier uses.
