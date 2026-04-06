# Trading Infrastructure — Ground Truth Architecture
**Generated:** 2026-04-06
**Status snapshot against:** zero_dollar_stack_and_build_sequence_1.md

---

## Zero Dollar Stack: Phase Completion Status

| Phase | Description | Status |
|-------|-------------|--------|
| **Phase 0** | Environment + directory structure + database | ✅ Complete |
| **Phase 1** | Marcus: Macro data pipeline + regime classifier + dashboard | ✅ Complete (with Phase 2 enhancements merged in) |
| **Phase 2 (Sarah)** | Vol surface layer — daily run, greeks, scenario engine, pre-trade dashboard, regime library | ✅ Stages 1–5 complete (see Sarah detail below) |
| **Phase 3** | Priya: Research backtesting framework (VectorBT, MLflow, options backtester) | ❌ Not started — `research/strategies/` is empty |
| **Phase 4** | Jordan: Risk layer (Greeks aggregation, risk limits, Grafana) | ❌ Not started — `systems/risk/` exists but is empty |
| **Phase 5** | Kai: Execution layer (IBKR connector, TCA tracker) | ❌ Not started — `systems/execution/` exists but is empty |
| **Phase 6** | Alex: Orchestration / weekly review system | ⚠️ Framework only — scheduler.py exists; no weekly report generator |
| **Phase 7** | Sam: Trade log + P&L attribution + operations layer | ❌ Not started — schema placeholder only in db_init.py |

### Sarah (Phase 2) Stage Detail

| Stage | What it does | Entry point |
|-------|-------------|-------------|
| Stage 1 | Daily vol pipeline: fetch options chains, build term structure, extract skew, compute signals, write to trading.db and vol_signals.json | `systems/sarah/daily_vol_run.py` |
| Stage 2 | Analytic BS greeks (7: delta, gamma, theta, vega, rho, vanna, charm, vomma), mispricing flag, portfolio aggregator | `systems/sarah/greeks_tool.py` |
| Stage 3 | Scenario P&L engine: spot×IV heatmap, stress scenarios (skew-amplified), structure comparison with break-even, kill scenario | `systems/sarah/scenario_engine.py` |
| Stage 4 | Pre-trade dashboard: 5 panels (vol level, term structure, skew, flow, distribution), BL density, structure comparison, writes pretrade_memo.json | `systems/sarah/pretrade_dashboard.py` |
| Stage 5 | Regime library: VVIX feed, normalized analog search (6D feature vector), event library (6 curated events), pre-transition monitor | `systems/sarah/regime_library.py` |

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
├── config.py                          ← Master config (all paths, thresholds, vol params)
├── scheduler.py                       ← Daily/weekly pipeline orchestrator
├── requirements.txt
├── README.md
├── setup.sh
├── CLAUDE.md
├── .env                               ← Not committed; FRED_API_KEY
├── .python-version
│
├── data/
│   ├── processed/
│   │   ├── macro.db                   ← Primary DuckDB: macro series, regime history, COT
│   │   ├── trading.db                 ← Sarah's DuckDB: vol_signals, vol_surface, vvix_daily
│   │   └── main.db.deprecated         ← Phase 0 DuckDB (renamed; not used by pipeline)
│   ├── outputs/
│   │   ├── regime_state.json          ← Written by Marcus (RegimeClassifier.write_output_contract)
│   │   ├── vol_signals.json           ← Written by Sarah Stage 1 (daily_vol_run.py)
│   │   └── pretrade_memo.json         ← Written by Sarah Stage 4 (generate_memo)
│   ├── events/
│   │   └── regime_events.yaml         ← Manually curated event library (6 events)
│   ├── snapshots/                     ← PDF regime snapshots (macro_YYYY-MM-DD_HHMMSS.pdf)
│   ├── raw/                           ← Empty (excluded from git)
│   └── cache/                         ← Empty (excluded from git)
│
├── logs/
│   └── cron.log
│
├── docs/
│   └── architecture/
│       ├── current_state.md           ← This file
│       └── zero_dollar_stack_and_build_sequence_1.md
│
├── reports/                           ← Empty
│
├── research/
│   ├── __init__.py
│   ├── signals/
│   │   ├── __init__.py
│   │   ├── vol_surface.py             ← ATM IV extraction, term structure builder, skew slicer
│   │   └── vol_signals.py             ← TS slopes, VRP proxy, IV context (IVR/IVP)
│   ├── strategies/                    ← Empty — Phase 3 not started
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
    ├── __init__.py
    ├── config_phase0_deprecated.py    ← DEPRECATED — Phase 0 only; do not import
    ├── db_init.py                     ← Phase 0 schema initializer (targets main.db)
    ├── data_feeds/
    │   ├── __init__.py
    │   ├── macro_feed.py              ← FRED, COT, SPY equity, macro calendar
    │   ├── options_feed.py            ← yfinance options chain enrichment (15–20 min delay)
    │   └── cboe_feed.py               ← VIX term structure + VVIX daily fetch
    ├── signals/
    │   ├── __init__.py
    │   └── regime_classifier.py
    ├── dashboard/
    │   ├── __init__.py
    │   ├── macro_dashboard.py         ← Dash app at http://127.0.0.1:8050
    │   └── assets/custom.css
    ├── reports/
    │   ├── __init__.py
    │   └── snapshot_generator.py
    ├── sarah/
    │   ├── __init__.py
    │   ├── daily_vol_run.py           ← Stage 1 orchestrator
    │   ├── vol_db.py                  ← trading.db schema + write helpers
    │   ├── greeks_tool.py             ← Stage 2: analytic greeks engine
    │   ├── scenario_engine.py         ← Stage 3: P&L scenario engine
    │   ├── pretrade_dashboard.py      ← Stage 4: pre-trade analysis + memo
    │   └── regime_library.py          ← Stage 5: analog search + event library
    ├── utils/
    │   ├── __init__.py
    │   ├── db.py
    │   └── pricing.py                 ← BS pricing, greeks, forward price, delta, mispricing
    ├── execution/                     ← Empty — Phase 5 not started
    └── risk/                          ← Empty — Phase 4 not started
```

---

## 2. Component Inventory

### `config.py` (project root)
**What it does:** Master configuration for the full pipeline. Defines all paths, FRED series IDs, regime thresholds, dashboard settings, staleness thresholds, divergence thresholds, component weights, FOMC schedule, and all Sarah vol parameters.

**Exposes (Marcus):** `FRED_API_KEY`, `DUCKDB_PATH`, `OUTPUTS_DIR`, `MACRO_SERIES`, `CFTC_INSTRUMENTS`, `REGIME_THRESHOLDS`, `REGIME_COLORS`, `DASHBOARD_HOST`, `DASHBOARD_PORT`, `DASHBOARD_REFRESH_SECONDS`, `CHART_BASE_LAYOUT`, `LOG_PATH`, `LOG_LEVEL`, `STALENESS_THRESHOLDS_DAYS`, `UNEMPLOYMENT_STALE_DAYS`, `DIVERGENCE_THRESHOLD_VC`, `DIVERGENCE_THRESHOLD_VL`, `DIVERGENCE_MIN_CREDIT_STRESS`, `COMPONENT_WEIGHTS`, `FOMC_SCHEDULE_2026`

**Exposes (Sarah):** `VOL_DB_PATH`, `VOL_TICKERS`, `FRED_RISK_FREE_SERIES`, `VOL_IVR_MIN_HISTORY_DAYS`, `ANALOG_MIN_HISTORY_DAYS`, `VVIX_CONFIDENCE_MIN_DAYS`

**Key Sarah constants:**

| Constant | Value | Purpose |
|----------|-------|---------|
| `VOL_DB_PATH` | `"data/processed/trading.db"` | Sarah's DuckDB |
| `VOL_TICKERS` | `["SPY","QQQ","IWM","XLE","GLD"]` | Daily vol run tickers |
| `FRED_RISK_FREE_SERIES` | `"DGS3MO"` | 3-month T-bill rate |
| `VOL_IVR_MIN_HISTORY_DAYS` | `60` | Minimum history for IVR/IVP |
| `ANALOG_MIN_HISTORY_DAYS` | `120` | Warn threshold for analog search |
| `VVIX_CONFIDENCE_MIN_DAYS` | `504` | ~2 years before VVIX added to feature vector |

---

### `systems/config_phase0_deprecated.py`
**Status:** Deprecated Phase 0 relic. Only referenced by `systems/db_init.py`. Never import from this file.

---

### `systems/utils/db.py`
**What it does:** DuckDB connection management and schema initialization for macro.db. Provides upsert logic with automatic z-score and percentage-change computation on insert.

**Exposes:**
- `get_connection(db_path=None) -> duckdb.DuckDBPyConnection` — used by all components; never call `duckdb.connect()` directly
- `initialize_schema(conn)` — creates all Phase 1 tables (idempotent)
- `upsert_series(conn, series_id, series_name, df)` — insert/replace with computed pct_chg and z-scores
- `get_latest(conn, series_id) -> dict | None`
- `get_series_history(conn, series_id, days=756) -> pd.DataFrame`

**Imports from project:** `config` (root)

---

### `systems/utils/pricing.py`
**What it does:** Shared Black-Scholes pricing utilities used by Sarah's options tools. All analytic formulas — no finite differences.

**Exposes:**
- `forward_price(spot, rate, div_yield, dte) -> float` — F = S × e^((r−q)×t)
- `strike_to_delta(mid, spot, strike, rate, dte, flag, bid) -> float` — two-pass delta via IV
- `log_moneyness(strike, forward) -> float` — ln(K/F)
- `bs_price(flag, spot, strike, t, rate, q, iv) -> float` — Black-Scholes price
- `bs_greeks_full(flag, spot, strike, t, rate, q, iv) -> dict` — 7 greeks: delta, gamma, theta, vega, rho, vanna, charm, vomma
- `bs_mispricing_flag(delta, skew_25d_rr) -> str | None` — flags position if delta is in skewed tail

**External deps:** `numpy`, `py_vollib`

---

### `systems/data_feeds/macro_feed.py`
**What it does:** All macro data ingestion — FRED series, CFTC COT data, macro calendar events, and SPY equity price history.

**Exposes:**
- `build_fred_client() -> Fred`
- `run_fred_pipeline(full_history=False)` — main FRED ingest loop
- `compute_derived_series(conn)` — M2 YoY growth, SPY drawdown from 252d peak
- `fetch_cot_data(conn)` — CFTC positioning via `cot-reports` library
- `fetch_calendar_data(conn)` — FRED release dates + FOMC schedule
- `fetch_equity_data(conn, ticker="SPY", start="2017-01-01")` — via yfinance

---

### `systems/data_feeds/options_feed.py`
**What it does:** Fetches and enriches yfinance options chains for Sarah Stage 1. Data is 15–20 minutes delayed — not suitable for live pre-trade decisions.

**Exposes:**
- `fetch_options_chain(ticker, rate, max_expirations=6) -> dict | None`

**Enrichment added to raw chain:** `iv` (renamed from `impliedVolatility`), `forward` (per-expiration), `log_moneyness`, `delta` (two-pass BS), `mid`, `dte`

**Returns:** `{ticker, spot, div_yield, rate, as_of, data_warning, chains: {'{exp_str}_c': DataFrame, '{exp_str}_p': DataFrame}}`

**External deps:** `yfinance`, `numpy`, `pandas`, `systems.utils.pricing`

---

### `systems/data_feeds/cboe_feed.py`
**What it does:** Fetches VIX term structure (9D/30D/3M/6M) and VVIX daily value from CBOE via yfinance. VVIX is stored to `vvix_daily` table in trading.db.

**Exposes:**
- `fetch_vix_term_structure() -> dict | None` — `{as_of, levels, levels_decimal, spot_vix}`
- `fetch_vvix_daily() -> float | None` — fetches and persists latest VVIX to trading.db

**External deps:** `yfinance`, `loguru`, `systems.utils.db`

---

### `systems/signals/regime_classifier.py`
**What it does:** Converts current macro readings into a discrete regime classification with component scores, confidence level, divergence signals, attribution, and regime change probability. Writes `data/outputs/regime_state.json`.

**Exposes:**
- `MacroSnapshot` (dataclass) — current readings for all regime inputs
- `RegimeResult` (dataclass) — full classification output
- `RegimeClassifier` (class):
  - `classify(persist=True) -> RegimeResult`
  - `classify_from_df(macro_df, cot_df, date) -> RegimeResult` — backfill mode
  - `get_history(days=252) -> pd.DataFrame`
  - `attribution(result) -> dict` — drivers, contradictors, flip-watch
  - `regime_change_probability(result) -> dict` — ~30d transition probability
  - `write_output_contract(result)` — writes `data/outputs/regime_state.json`

**Component scorers (internal):** `_score_vol()` 25%, `_score_credit()` 25%, `_score_curve()` 20%, `_score_labor()` 15%, `_score_inflation()` 10%, `_score_positioning()` 5%

**Regime mapping:** Composite score → `RISK_ON_LOW_VOL` / `RISK_ON_ELEVATED_VOL` / `NEUTRAL` / `CAUTION` / `RISK_OFF_STRESS` / `CRISIS`

---

### `research/signals/vol_surface.py`
**What it does:** Surface construction functions consumed by Sarah Stage 1. Lives in `research/` because these are research-derived signal algorithms, not production systems.

**Exposes:**
- `extract_atm_iv(chain_df, forward, dte) -> float` — forward-based ATM IV extraction
- `build_term_structure(chain_data, spot, rate) -> dict` — per-expiration ATM IVs and forward prices
- `extract_skew_slice(chain_data, target_dte, target_deltas) -> dict` — skew by delta at target DTE

---

### `research/signals/vol_signals.py`
**What it does:** Signal computation functions consumed by Sarah Stage 1.

**Exposes:**
- `term_structure_slopes(atm_iv_by_dte) -> dict` — front slope (30→60d), back slope (60→180d), ts_shape (6-state enum: contango/backwardation/flat/humped/inverted_hump/insufficient_data)
- `backward_vrp_proxy(atm_iv_30d, rv_21d) -> dict` — VRP proxy signal (6-state enum)
- `iv_context(atm_iv_30d, iv_history, min_days) -> dict` — IVR, IVP, confidence level, regime bias

---

### `systems/sarah/vol_db.py`
**What it does:** Schema definitions and write helpers for `trading.db`. All write operations go through `upsert_vol_signals()`.

**Exposes:**
- `initialize_vol_schema(conn)` — creates `vol_signals` and `vol_surface` tables (idempotent)
- `upsert_vol_signals(conn, ticker, date, signals_dict)` — insert/replace in vol_signals
- `VOL_SIGNALS_DDL`, `VOL_SURFACE_DDL` (strings)

---

### `systems/sarah/daily_vol_run.py`
**What it does:** Stage 1 orchestrator. Runs the full daily vol pipeline for all tickers. Reads regime_state.json first (hard prerequisite), fetches options and VIX data, computes all signals, persists to trading.db, and writes vol_signals.json.

**Exposes:**
- `run_daily_vol()` — main entry point (called by scheduler weekdays at 08:00)

**Execution sequence:**
1. Validate `data/outputs/regime_state.json` (age < 80h; hard fail otherwise)
2. Fetch 3-month risk-free rate from FRED (fallback: 0.045)
3. For each ticker in `VOL_TICKERS`: fetch chain → build term structure → extract skew → compute signals → write to trading.db
4. Write `data/outputs/vol_signals.json`

**Staleness limit:** 80 hours (covers Friday→Monday weekend gap)

---

### `systems/sarah/greeks_tool.py`
**What it does:** Stage 2 analytic greeks engine for single positions and portfolio aggregation. No directional labels in output. All computation via analytic BS formulas in `pricing.py`.

**Exposes:**
- `GreeksTool` (class):
  - `analyze_position(ticker, flag, strike, expiration, quantity, long_short, rate=None) -> dict`
  - `analyze_portfolio(positions: list[dict]) -> dict` — aggregates greeks across all positions
- Returns: `{position, market, greeks, greeks_scaled, bs_flag, interpretation}`
- 7 greeks: delta, gamma, theta, vega, rho, vanna, charm, vomma
- `bs_mispricing_flag` used to flag if position delta is in skewed tail

---

### `systems/sarah/scenario_engine.py`
**What it does:** Stage 3 P&L scenario engine. Two modes: grid (flat-vol heatmap) and named stress scenarios (with skew amplification).

**Exposes:**
- `ScenarioEngine` (class):
  - `scenario_pnl_grid(position, spot_vix=None) -> dict` — spot×IV P&L grid at multiple time checkpoints; auto-expands grid range in high-vol mode (VIX > 25)
  - `stress_scenario_pnl(position, scenario_key, use_skew_amplification=True) -> dict` — named scenarios with skew-amplified IV moves
  - `structure_comparison(thesis, structures) -> dict` — compares break-even, max loss, and risk/reward across option structures
  - `kill_scenario(position) -> dict` — worst-case P&L: max adverse move at expiry

**Grid params:** Spot ±15% (±25% high-vol), IV ±10 vpts (±20 high-vol), time checkpoints: [0.25, 0.5, 0.75, 1.0]

---

### `systems/sarah/pretrade_dashboard.py`
**What it does:** Stage 4 pre-trade analysis toolkit. Five analytical panels plus Breeden-Litzenberger risk-neutral density, structure comparison, and JSON memo output.

**Exposes:**
- `TradeThesisInput` (dataclass) — `{ticker, expected_move, thesis_days, catalyst_type, max_loss_budget}`
- `FlowObservation` (dataclass) — optional flow context for flow panel
- `vol_level_panel(thesis, signals) -> dict` — vol level vs. thesis expected move
- `term_structure_panel(thesis, signals) -> dict` — cost of time premium at thesis tenor
- `skew_panel(thesis, signals) -> dict` — skew context for directional thesis
- `flow_panel(flow, current_surface, thesis) -> dict` — flow context overlay
- `breeden_litzenberger_density(chain_df, spot, rate, dte) -> dict` — risk-neutral PDF from options chain
- `generate_structure_comparison(thesis, signals, chain_data) -> dict` — prices and compares structures (long call, long put, vertical spread, calendar, straddle, strangle)
- `generate_memo(thesis, signals, flow_obs=None) -> dict` — produces structured pretrade_memo.json

**Output file:** `data/outputs/pretrade_memo.json`

---

### `systems/sarah/regime_library.py`
**What it does:** Stage 5 historical regime library. Surface state analog search with normalized feature vectors and macro compatibility filtering. Also hosts the VVIX-based pre-transition monitor and the curated event browser.

**Exposes:**
- `build_normalized_feature_vector(snapshot, feature_history, include_vvix=False) -> (ndarray, list)` — 6D (+ optional 7th VVIX) Z-score normalized feature vector
- `surface_similarity(query_vector, candidate_vector) -> float` — Euclidean distance → similarity score [0,1]
- `compute_vix_vvix_signals(vix, vvix, vix_history, vvix_history) -> dict` — VIX z-score, VVIX z-score, VVIX/VIX ratio, pre_transition_flag
- `analog_search(current_snapshot, historical_snapshots, macro_filter, n_results=10, include_vvix=False) -> DataFrame` — two-stage search: surface similarity then macro regime compatibility filter
- `get_historical_snapshots(ticker) -> DataFrame` — load all vol_signals history for ticker
- `get_vvix_history() -> Series` — from vvix_daily in trading.db
- `get_vix_history() -> Series` — from macro_series in macro.db
- `load_event_library(path) -> list[dict]` — load regime_events.yaml
- `event_browser(event_id) -> dict | None` — look up single event by ID
- `list_events() -> list[dict]` — summary of all events in library
- `pre_transition_monitor(vix, vvix, vix_history, vvix_history) -> dict` — flags VVIX elevated while VIX is not

**Feature vector dimensions:** `atm_iv_30d`, `iv_rank`, `ts_front_slope`, `ts_back_slope`, `skew_25d_rr`, `vix_z1y` (+ `vvix_z1y` after 504 trading days of VVIX history)

**Macro compatibility filter:** `exclude_zero_rate_era` (drop pre-2022), `require_regime_match` (drop RISK_OFF_STRESS ↔ RISK_ON_LOW_VOL incompatible pairs)

**Event library:** `data/events/regime_events.yaml` — manually curated, 6 events. Add new events after significant market moves.

---

### `systems/dashboard/macro_dashboard.py`
**What it does:** Interactive Dash web application for the macro regime dashboard. Runs at `http://127.0.0.1:8050`. Read-only visualization over DuckDB data.

**Exposes:** Dash `app` object (entry point only)

**Dashboard sections:**
- Left sidebar: Regime card, signal feed, COT positioning table, regime transitions, macro calendar
- Right content: Divergence banner, component score bars + sparklines, regime history chart, attribution panel, tabbed charts (VIX, HY, curve, divergence, return stats, validation)

**Imports from project:** `config`, `systems.utils.db`, `systems.signals.regime_classifier`

---

### `systems/reports/snapshot_generator.py`
**What it does:** Generates standalone PDF snapshots of the regime state without requiring the Dash server.

**Exposes:** `generate_snapshot(output_path=None, return_bytes=False) -> str | bytes`

**Output location:** `data/snapshots/macro_YYYY-MM-DD_HHMMSS.pdf`

---

### `scheduler.py` (project root)
**What it does:** Daily pipeline orchestrator. Runs immediately on startup, then enters a blocking schedule loop.

**Schedule:**
- Weekdays 08:00: `run_daily_vol()` — Sarah vol surface run (after Marcus writes regime_state.json)
- Weekdays 18:05: `run_daily_pipeline()` — FRED fetch → derived series → regime classify → snapshot
- Daily 18:05: `fetch_equity_data()` (SPY)
- Weekdays 18:15: `run_nightly_snapshot()`
- Sunday 20:00: `run_weekly_full_refresh()` — full FRED history pull
- Sunday 20:05: `fetch_calendar_data()`

---

## 3. Output Contracts

All output files live in `data/outputs/`. All downstream components must validate `regime_state.json` before running (age limit enforced per component).

| File | Written by | Staleness limit | Contents |
|------|-----------|----------------|----------|
| `data/outputs/regime_state.json` | `regime_classifier.py` (`write_output_contract`) | 12h (per CLAUDE.md rule) | Regime state, composite score, component scores, confidence, divergence_type, as_of, missing_inputs, written_at |
| `data/outputs/vol_signals.json` | `daily_vol_run.py` | — | as_of, macro_regime, signals per ticker, summary (elevated_vrp, low_iv_rank, high_put_skew) |
| `data/outputs/pretrade_memo.json` | `pretrade_dashboard.py` (`generate_memo`) | — | ticker, date, thesis_parameters, market_state, structure_comparison, data_warning |
| `data/snapshots/macro_YYYY-MM-DD_HHMMSS.pdf` | `snapshot_generator.py` | — | PDF: regime header, component scores chart, regime history chart, persistence stats, calendar, attribution |

---

## 4. DB Schema

### Database: `data/processed/macro.db` (Phase 1 — active)

#### `macro_series`
```
series_id       VARCHAR   — internal key (e.g. "vix", "hy_spread")
series_name     VARCHAR
date            DATE
value           DOUBLE
pct_chg_1m      DOUBLE
pct_chg_3m      DOUBLE
pct_chg_12m     DOUBLE
z_score_1y      DOUBLE    — 252-day rolling
z_score_5y      DOUBLE    — 1260-day rolling
PRIMARY KEY (series_id, date)
```

#### `regime_history`
```
date                DATE PRIMARY KEY
regime              VARCHAR
composite_score     DOUBLE
confidence          VARCHAR
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
divergence_type     VARCHAR
divergence_severity VARCHAR
```

#### `cot_positioning`
```
instrument      VARCHAR
date            DATE
net_spec        DOUBLE
net_spec_pct    DOUBLE
z_score_1y      DOUBLE
z_score_3y      DOUBLE
PRIMARY KEY (instrument, date)
```

#### `fetch_log`
```
series_id       VARCHAR
fetched_at      TIMESTAMP
rows_updated    INTEGER
status          VARCHAR
error_msg       VARCHAR
```

#### `macro_calendar`
```
event_name      VARCHAR
event_date      DATE
category        VARCHAR
importance      VARCHAR
component       VARCHAR
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

### Database: `data/processed/trading.db` (Sarah — active)
Created and managed by `systems/sarah/vol_db.py`. `vvix_daily` created by `systems/data_feeds/cboe_feed.py`.

#### `vol_signals`
```
ticker              VARCHAR
date                DATE

-- ATM basis (forward-corrected)
spot_price          FLOAT
forward_price       FLOAT
risk_free_rate      FLOAT
div_yield           FLOAT
atm_iv_30d          FLOAT

-- IV context
iv_rank             FLOAT
iv_percentile       FLOAT
ivr_ivp_confidence  VARCHAR   — 'low' | 'medium' | 'standard' | 'insufficient'
ivr_regime_bias     VARCHAR

-- Skew (delta space)
skew_25d_rr         FLOAT     — 25Δ call IV − 25Δ put IV (risk reversal)
skew_25d_put        FLOAT
skew_25d_call       FLOAT
skew_1025_ratio     FLOAT     — 25/10Δ tail steepness

-- Term structure (two slopes)
ts_iv_30d           FLOAT
ts_iv_60d           FLOAT
ts_iv_180d          FLOAT
ts_front_slope      FLOAT     — iv_60d − iv_30d
ts_back_slope       FLOAT     — iv_180d − iv_60d
ts_shape            VARCHAR   — 6-state enum

-- VRP proxy
rv_21d              FLOAT
vrp_proxy_bkwd      FLOAT     — atm_iv_30d − rv_21d
vrp_proxy_signal    VARCHAR   — 6-state enum

-- Macro context
macro_regime        VARCHAR

-- Raw storage
term_structure_json VARCHAR
skew_by_delta_json  VARCHAR
pc_oi_ratio_json    VARCHAR

PRIMARY KEY (ticker, date)
```

#### `vol_surface`
```
ticker          VARCHAR
date            DATE
expiration      DATE
dte             INTEGER
strike          FLOAT
log_moneyness   FLOAT
delta           FLOAT
option_type     VARCHAR
iv              FLOAT
bid             FLOAT
ask             FLOAT
volume          INTEGER
open_interest   INTEGER
```

#### `vvix_daily`
```
date            DATE PRIMARY KEY
vvix            FLOAT
vix             FLOAT
vvix_vix_ratio  FLOAT
source          VARCHAR
```

---

### Database: `data/processed/main.db.deprecated` (Phase 0 — superseded)
Renamed from `main.db`. Not actively written to by any scheduled pipeline. Phase 0 schema only.

---

## 5. Entry Points

| File | What it does when run directly |
|------|-------------------------------|
| `scheduler.py` | Starts the daily/weekly pipeline scheduler loop |
| `systems/dashboard/macro_dashboard.py` | Starts Dash server at http://127.0.0.1:8050 |
| `systems/data_feeds/macro_feed.py` | Runs incremental FRED fetch |
| `systems/signals/regime_classifier.py` | Runs single classification and prints result |
| `systems/sarah/daily_vol_run.py` | Runs full daily vol pipeline for all VOL_TICKERS |
| `systems/sarah/greeks_tool.py` | Analyzes SPY 580C 45DTE position (demo) |
| `systems/reports/snapshot_generator.py` | Generates one PDF snapshot |
| `systems/utils/db.py` | Smoke test — prints "Database ready." |
| `systems/db_init.py` | Initializes main.db with Phase 0 schema |
| `scripts/check_data.py` | Prints data freshness diagnostic |
| `scripts/verify_phase0.py` | Runs Phase 0 verification checklist |
| `scripts/backfill_regime_history.py` | Backfills regime_history from 2018-01-01 |
| `scripts/compute_regime_return_stats.py` | Computes regime-conditional return stats |
| `scripts/calibrate_divergence_threshold.py` | Calibrates divergence thresholds |

---

## 6. Known Issues and Notes

### Config split: two databases, two config files
- `config.py` (root): `DUCKDB_PATH = "data/processed/macro.db"`, `VOL_DB_PATH = "data/processed/trading.db"`
- `systems/config_phase0_deprecated.py`: `DB_PATH = "data/processed/main.db"` — deprecated, do not use
- **Risk:** any new code importing from `systems/config_phase0_deprecated.py` will target the wrong database

### COMPONENT_WEIGHTS duplication
- `config.py` (root) and `RegimeClassifier.WEIGHTS` inside `regime_classifier.py` must be kept in sync manually. If they diverge, the dashboard will display different weights than the classifier uses.

### yfinance data delay
- All options data (options_feed.py, cboe_feed.py) is 15–20 minutes delayed. Every output that touches options data carries `data_warning` field propagating this notice. Not suitable for live pre-trade decisions.

### Sarah has no interactive UI
- Stages 2–5 are library functions with no web interface. The Marcus Dash dashboard at :8050 does not currently include any Sarah panels.

### Analog search history dependency
- `analog_search` warns at < 120 days of history (`ANALOG_MIN_HISTORY_DAYS`).
- VVIX is only added as a 7th feature after 504 trading days of data (`VVIX_CONFIDENCE_MIN_DAYS` ≈ 2 years).
- Both thresholds will be hit naturally as trading.db accumulates history.

### Empty placeholder directories
- `systems/execution/` — Phase 5 not started
- `systems/risk/` — Phase 4 not started
- `research/strategies/` — Phase 3 not started
- `research/archive/` — empty

---

## 7. config.py Inventory (Sarah additions)

| Constant | Type | Value |
|----------|------|-------|
| `OUTPUTS_DIR` | `str` | `"data/outputs"` |
| `VOL_DB_PATH` | `str` | `"data/processed/trading.db"` |
| `VOL_TICKERS` | `list[str]` | `["SPY", "QQQ", "IWM", "XLE", "GLD"]` |
| `FRED_RISK_FREE_SERIES` | `str` | `"DGS3MO"` |
| `VOL_IVR_MIN_HISTORY_DAYS` | `int` | `60` |
| `ANALOG_MIN_HISTORY_DAYS` | `int` | `120` |
| `VVIX_CONFIDENCE_MIN_DAYS` | `int` | `504` |
