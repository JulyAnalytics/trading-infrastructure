# Audit #1 — Data Pipeline
**Date:** 2026-04-07
**Scope:** All data ingestion scripts, feed connectors, storage logic
**Files audited:** config.py, scheduler.py, systems/data_feeds/macro_feed.py, systems/data_feeds/cboe_feed.py, systems/data_feeds/options_feed.py, systems/utils/db.py, systems/sarah/daily_vol_run.py, systems/sarah/vol_db.py

---

## DOCUMENT 1: CAPABILITY MAP

---

### Component: Configuration

**Component name:** System Configuration
**File path:** [config.py](../../config.py)
**Module it belongs to:** Shared / all modules
**What it does:** Single source of truth for all paths, API keys, thresholds, series definitions, and component weights. Every other module imports from here. Eliminates hardcoded paths across the codebase.
**Inputs:**
- `.env` file for secrets (`FRED_API_KEY`)
- Hardcoded constants for everything else
**Outputs:**
- Exported constants: `DUCKDB_PATH`, `VOL_DB_PATH`, `OUTPUTS_DIR`, `MACRO_SERIES`, `REGIME_THRESHOLDS`, `COMPONENT_WEIGHTS`, `STALENESS_DAYS`, `VOL_TICKERS`, `FOMC_SCHEDULE_2026`
- Format: Python module-level constants (strings, dicts, lists)
**Dependencies:**
- `.env` for `FRED_API_KEY` — if missing, fredapi calls will fail at runtime
**Implementation status:** Appears complete
**Gap vs architecture:** None identified. Architecture rule #1 (all paths from config.py) is enforced here. One note: `VOL_DB_PATH` is defined here but the CLAUDE.md architecture doc only names `DUCKDB_PATH` in the shared utilities section — minor doc gap, not a code gap.

---

### Component: Database Layer

**Component name:** DuckDB Connection Manager & Schema
**File path:** [systems/utils/db.py](../../systems/utils/db.py)
**Module it belongs to:** Shared / all modules
**What it does:** Provides the single `get_connection()` factory for all DuckDB access, enforcing that no module calls `duckdb.connect()` directly. Also owns schema initialization (CREATE IF NOT EXISTS) and two read helpers.
**Inputs:**
- `db_path` parameter (defaults to `DUCKDB_PATH` = macro.db)
- DataFrames passed to `upsert_series()`
**Outputs:**
- DuckDB connection object
- Upserted rows in `macro_series`, `regime_history`, `cot_positioning`, `fetch_log`, `macro_calendar`
- Read helpers return dict (`get_latest`) or DataFrame (`get_series_history`)
**Dependencies:**
- config.py for `DUCKDB_PATH`
- Called by virtually every module — if this fails, everything fails
**Implementation status:** Appears complete
**Gap vs architecture:**
- `initialize_schema()` only creates macro.db tables. The trading.db schema (vol_signals, vol_surface, vvix_daily) is initialized separately in `vol_db.py`. This split is undocumented in CLAUDE.md and means there are two schema init paths to maintain.
- `upsert_series()` computes z-scores and percent changes at write time, not at read time. This is a design choice but means historical z-scores get silently recalculated if you re-upsert old data.

---

### Component: Macro Data Feed

**Component name:** FRED + COT Data Ingestion
**File path:** [systems/data_feeds/macro_feed.py](../../systems/data_feeds/macro_feed.py)
**Module it belongs to:** Marcus / Macro layer
**What it does:** Fetches 35 macroeconomic time-series from the FRED API (Federal Reserve data) and CFTC COT positioning data (how institutional traders are positioned in futures markets). Writes all data to macro.db and logs every fetch.
**Inputs:**
- FRED API (35 series — rates, spreads, inflation, labor, housing, etc.)
- CFTC Futures-Only COT report via `cot_reports` library (7 instruments)
- yfinance for SPY equity prices
- `FOMC_SCHEDULE_2026` hardcoded list in config.py for calendar events
- Format: all fetched as DataFrames, stored to DuckDB
**Outputs:**
- `macro_series` table: time-series with z-scores and % changes for all 35+ series
- `cot_positioning` table: weekly net speculative positioning with z-scores
- `fetch_log` table: audit trail of every fetch attempt
- `macro_calendar` table: upcoming FOMC dates + key release dates
**Dependencies:**
- config.py (FRED_API_KEY, MACRO_SERIES definitions)
- systems/utils/db.py (get_connection, upsert_series, initialize_schema)
- External: FRED API, CFTC, yfinance
**Implementation status:** Appears complete
**Gap vs architecture:**
- FOMC_SCHEDULE_2026 is hardcoded in config.py. This means it requires a manual config.py update each year — no automatic calendar feed.
- `compute_derived_series()` computes M2 YoY and SPY drawdown but these are computed in Python and re-upserted, not computed at query time. If the underlying series is backfilled, derived series won't automatically update.
- No validation that fetched values are within reasonable bounds (e.g., VIX = 0 or VIX = 500 would both be accepted).

---

### Component: CBOE/VIX Feed

**Component name:** VIX Term Structure & VVIX Feed
**File path:** [systems/data_feeds/cboe_feed.py](../../systems/data_feeds/cboe_feed.py)
**Module it belongs to:** Sarah / Vol layer
**What it does:** Fetches the VIX term structure across four maturities (9-day, 30-day, 3-month, 6-month) and VVIX (the "volatility of VIX" — how unstable VIX itself is). Both come from Yahoo Finance under CBOE tickers.
**Inputs:**
- yfinance tickers: `^VIX9D`, `^VIX`, `^VIX3M`, `^VIX6M`, `^VVIX`
- Format: yfinance download response → dict/DataFrame
**Outputs:**
- `fetch_vix_term_structure()`: dict with VIX levels at 4 tenors (in % and decimal), spot VIX
- `fetch_vvix_daily()`: writes to `vvix_daily` table in trading.db; returns current VVIX float
**Dependencies:**
- systems/utils/db.py (get_connection, for trading.db)
- External: Yahoo Finance (15–20 min delayed)
**Implementation status:** Appears complete
**Gap vs architecture:**
- `^VIX9D` has inconsistent data availability — it's a newer product and may return empty or NaN on some days. The code returns None on failure but there's no fallback or imputation.
- The VIX term structure is not stored to macro.db's `macro_series` table — it exists only as a runtime dict passed to the vol pipeline. No persistent history of the VIX term structure beyond the `vvix_daily` table.

---

### Component: Options Chain Feed

**Component name:** Options Chain Fetcher & Enricher
**File path:** [systems/data_feeds/options_feed.py](../../systems/data_feeds/options_feed.py)
**Module it belongs to:** Sarah / Vol layer
**What it does:** Fetches the full options chain for a given ticker (up to 6 expirations) and enriches each contract with derived fields: forward price, log-moneyness (how far the strike is from current price), and delta (an options Greek — probability proxy of finishing in-the-money).
**Inputs:**
- `ticker` (string), `rate` (risk-free rate float), `max_expirations` (int, default 6)
- yfinance for options chain data and spot price
- Format: yfinance Ticker object
**Outputs:**
- Dict containing spot, div_yield, rate, as_of, data_warning, and `chains` dict (one DataFrame per expiration × option type)
- Each chain DataFrame columns: strike, iv, bid, ask, volume, open_interest, dte, log_moneyness, mid, delta, option_type
**Dependencies:**
- py_vollib for Black-Scholes delta calculation
- External: Yahoo Finance (15–20 min delayed)
**Implementation status:** Appears complete
**Gap vs architecture:**
- The `iv` field comes directly from yfinance's implied vol calculation — it is not independently verified. yfinance IV is known to be unreliable for illiquid strikes and far-dated contracts.
- Delta is computed using simple Black-Scholes (flat IV), not adjusted for the IV smile. This means delta for skewed strikes will be slightly off.
- No filtering of zero-bid or zero-volume options. Illiquid strikes with stale IV will silently pollute the chain.
- `max_expirations=6` is hardcoded as default. No validation that returned expirations are evenly spaced or cover the required tenors (30d, 60d, 180d).

---

### Component: Daily Vol Pipeline

**Component name:** Daily Vol Signal Run (Sarah Stage 1)
**File path:** [systems/sarah/daily_vol_run.py](../../systems/sarah/daily_vol_run.py)
**Module it belongs to:** Sarah / Vol layer
**What it does:** Orchestrates the daily options analysis pipeline. For each of 5 tickers, it builds the IV term structure, extracts skew (the put/call IV asymmetry), computes IV rank/percentile (how elevated vol is vs. its own history), and estimates the VRP (Volatility Risk Premium — whether options are pricing in more vol than the market is actually delivering).
**Inputs:**
- `data/outputs/regime_state.json` — must exist and be <80 hours old (hard stop if not)
- FRED API for current risk-free rate (3M T-bill); falls back to 4.5% if unavailable
- cboe_feed for VIX term structure
- options_feed for options chains
- `vol_signals` table in trading.db for IVR/IVP history
- yfinance for 30-day price history (for realized vol calculation)
**Outputs:**
- Row upserted to `vol_signals` table in trading.db (one row per ticker per day)
- `data/outputs/vol_signals.json` — consolidated signals for all tickers
**Dependencies:**
- Requires regime_state.json written by Marcus (regime_classifier.py)
- systems/data_feeds/cboe_feed.py
- systems/data_feeds/options_feed.py
- systems/utils/db.py (trading.db connection)
- vol_db.py for schema init
**Implementation status:** Appears complete
**Gap vs architecture:**
- Staleness check is 80 hours (not 12 hours as specified in CLAUDE.md Rule #4). This is intentional per architecture notes but is an acknowledged deviation.
- Risk-free rate fallback to 4.5% is hardcoded. In a rate-change environment this could meaningfully distort forward prices and Greek calculations.
- VRP uses 21-day realized vol vs 30-day implied vol (mismatched tenors). Documented but introduces a known imprecision.

---

### Component: Vol Database Schema

**Component name:** trading.db Schema Init
**File path:** [systems/sarah/vol_db.py](../../systems/sarah/vol_db.py)
**Module it belongs to:** Sarah / Vol layer
**What it does:** Initializes the trading.db tables (vol_signals, vol_surface, vvix_daily) if they don't exist. Run at the start of the daily vol pipeline.
**Inputs:** None at runtime (pure schema DDL)
**Outputs:** Creates tables in trading.db if missing
**Dependencies:** systems/utils/db.py
**Implementation status:** Appears complete
**Gap vs architecture:** The schema lives in vol_db.py, not in db.py. This means there are two separate schema init files (db.py owns macro.db, vol_db.py owns trading.db). The architecture doc doesn't explicitly describe this split.

---

### Component: Scheduler

**Component name:** Task Scheduler / Pipeline Orchestrator
**File path:** [scheduler.py](../../scheduler.py)
**Module it belongs to:** Alex (framework layer)
**What it does:** Runs all data pipelines on a time-based schedule using the `schedule` library. Acts as the main entry point for production execution — starts the macro feed, regime classification, and vol pipeline in sequence.
**Inputs:** None (time-driven)
**Outputs:** Triggers all downstream pipelines on schedule
**Schedule:**

| Time (ET) | Frequency | Task |
|-----------|-----------|------|
| 18:05 | Weekdays | FRED incremental fetch + COT + regime classify |
| 20:00 | Sunday | Full FRED history refresh |
| 20:05 | Sunday | Calendar refresh (45d ahead) |
| 18:15 | Weekdays | Nightly snapshot PDF |
| 08:00 | Weekdays | Daily vol pipeline (Sarah Stage 1) |

**Dependencies:** All pipeline modules
**Implementation status:** Appears complete
**Gap vs architecture:**
- Scheduler runs startup task immediately at launch (`run_daily_pipeline()`) regardless of time of day — this could cause duplicate runs if restarted during a scheduled window.
- No health check or alerting if a job fails — errors are logged but no notification mechanism exists.
- No dependency enforcement: if the 18:05 FRED run fails, the 08:00 vol run the next morning will use stale data with no warning beyond the 80h staleness check.

---

## DOCUMENT 2: OUTPUT LITERACY

---

### Output: macro_series (DuckDB table)

**Output name:** `macro_series` — macro time-series with z-scores
**What it represents:** The complete historical record of all 35+ macro indicators the system monitors. Each row is one data point for one series on one date.
**Unit/format:** Mixed — values in native units (%, bps, index level); z-scores are unitless standard deviations
**Typical range:**
- Raw values vary by series (e.g., VIX typically 10–80, HY spread 200–1000 bps, yield curve -100 to +300 bps)
- z_score_1y: typically -3 to +3 (values beyond ±3 indicate extreme conditions)
- pct_chg_1m/3m/12m: expressed as decimal (0.05 = 5%)
**How to read it:** A z_score_1y of +2.1 for HY spread means spreads are 2.1 standard deviations above their 1-year average — an elevated stress reading. A z_score_1y near 0 is normal.
**Green flag:** z-scores clustered near 0; data written_at within the last 1–3 days for daily/weekly series
**Red flag:** z_score_1y values above ±4 (may indicate data error, not genuine extremes); `updated_at` timestamps more than 10 days old for weekly series; NULL values for series that should always have data
**Depends on:** FRED API availability; correctness of MACRO_SERIES definitions in config.py
**Limitation to know:** z-scores are computed over a rolling 1-year or 5-year window. Early in a regime change (first few months), the 1-year window still anchors to the prior regime, making z-scores less meaningful as absolute signals.

---

### Output: cot_positioning (DuckDB table)

**Output name:** `cot_positioning` — CFTC speculative positioning
**What it represents:** How much net "long" or "short" exposure large speculators (hedge funds, CTAs) have in 7 key futures markets. This is a sentiment/crowding indicator — not a price prediction.
**Unit/format:** `net_spec` = contracts long minus contracts short (integer); `net_spec_pct` = net as % of open interest (0–1); `z_score_1y/3y` = standardized (unitless)
**Typical range:**
- z_score_1y: -3 to +3
- net_spec_pct: -0.5 to +0.5 (50% net long to 50% net short is extreme)
**How to read it:** A z_score_1y of -2.5 for S&P500 futures means speculators are more net-short than 97.5% of the past year's readings — a historically extreme bearish positioning. Contrarian interpretation: extreme short positioning can precede rallies.
**Green flag:** z-scores in normal range (±1); data within 10 days (COT is published weekly with ~3-day lag)
**Red flag:** data older than 14 days; z_score values that haven't moved in several weeks (may indicate feed stuck)
**Depends on:** CFTC publication schedule (Fridays, 3:30pm ET); `cot_reports` library correctness; instrument mapping in config.py
**Limitation to know:** COT data is published with a 3-day lag and reports as-of Tuesday. It tells you what large speculators held last week, not today. It's a low-frequency sentiment gauge, not a timing signal.

---

### Output: regime_state.json (file)

**Output name:** `data/outputs/regime_state.json` — current market regime
**What it represents:** A summary classification of current macro conditions into one of 6 risk states, plus individual component scores that drove the classification.
**Unit/format:** JSON file; `regime_state` is a string enum; `composite_score` is float -1 to +1; `component_scores` are floats -1 to +1; `confidence` is LOW/MEDIUM/HIGH
**Typical range:**
- composite_score: +0.3 to +0.7 in normal risk-on markets; -0.3 to -0.7 in stress; near 0 in neutral/transition
- component_scores: each -1 to +1
**How to read it:** `composite_score: 0.42` with `regime_state: RISK_ON_LOW_VOL` means most components are pointing toward a supportive macro environment. A score of 0.42 is moderately positive, not extreme.

Example readings by regime:
| Regime | Typical composite_score |
|--------|------------------------|
| RISK_ON_LOW_VOL | +0.4 to +0.8 |
| RISK_ON_ELEVATED_VOL | +0.1 to +0.4 |
| NEUTRAL | -0.1 to +0.1 |
| CAUTION | -0.2 to -0.4 |
| RISK_OFF_STRESS | -0.4 to -0.7 |
| CRISIS | -0.7 to -1.0 |

**Green flag:** `confidence: HIGH`; all 6 component scores pointing same direction as composite; `written_at` within 24 hours on a weekday
**Red flag:** `confidence: LOW` combined with large spread between component_scores (e.g., vol says crisis, credit says risk-on); `written_at` older than 12 hours on a weekday; `missing_inputs` list is non-empty
**Depends on:** All 35 macro series being populated and fresh; regime_classifier.py component scoring logic
**Limitation to know:** The regime classification is a weighted average of 6 human-defined components with subjectively set weights. The weights (vol: 25%, credit: 25%, curve: 20%, labor: 15%, inflation: 10%, positioning: 5%) have not been backtested for predictive accuracy. This is a rules-based heuristic, not a statistically validated model.

---

### Output: vol_signals (DuckDB table + JSON)

**Output name:** `vol_signals` table / `data/outputs/vol_signals.json`
**What it represents:** Daily snapshot of options market conditions for 5 tickers. Answers: Is implied vol (IV) cheap or expensive? Is the market buying puts (protective hedging)? Is vol term structure in a normal or stressed shape?
**Unit/format:** Decimal for vol values (0.142 = 14.2% annualized vol); iv_rank/iv_percentile are 0–1 floats; skew is decimal; ts_shape and vrp_signal are string labels
**Typical range (SPY in a normal market):**
- atm_iv_30d: 0.10–0.20 (10–20%)
- iv_rank: 0–1 (0.3 = "vol is at the 30th percentile of its 1-year range")
- skew_25d_rr: -0.03 to -0.06 (negative = puts bid above calls, normal for equity)
- vrp_proxy: +0.01 to +0.04 (options typically price in slightly more vol than realized)
- ts_shape: "contango" in normal conditions (far-dated vol > near-dated vol)
**How to read it:** `atm_iv_30d: 0.142, iv_rank: 0.28` means 30-day at-the-money options are implying 14.2% annualized vol, and that's in the bottom 28% of the past year's range — relatively cheap vol. `vrp_signal: "elevated_vrp"` means options are pricing in significantly more vol than the market has been realizing — potentially favorable for option sellers.
**Green flag:** Historical data ≥ 252 days in vol_signals table (enables reliable IVR/IVP); `ivr_ivp_confidence: "standard"`; values plausibly match CBOE's published VIX (within a few points for SPY)
**Red flag:** `ivr_ivp_confidence: "insufficient"` (< 252 days history — IVR/IVP not reliable); `atm_iv_30d` deviating >30% from VIX/100 for SPY (data quality issue); all 5 tickers showing identical skew (feed failure); skew_25d_rr positive for SPY (puts cheaper than calls — almost never happens and indicates bad data)
**Depends on:** Quality of yfinance options chain data (15–20 min delayed); sufficient vol_signals history for IVR/IVP; regime_state.json freshness; stable risk-free rate fetch from FRED
**Limitation to know:** The VRP proxy compares 30-day IV to 21-day realized vol. These are different time windows — the "mismatch" means the VRP estimate includes some forward-looking bias. In a trending vol environment (vol rising or falling fast), this will overstate or understate the true premium. This is a known approximation, not a precise VRP calculation.

---

### Output: atm_iv_30d (key field in vol_signals)

**Output name:** `atm_iv_30d` — 30-day at-the-money implied volatility
**What it represents:** What the options market expects annualized price swings to be over the next 30 days. This is the single most important vol surface input.
**Unit/format:** Decimal (0.142 = 14.2% annualized). Multiply by √(30/252) × 100 to get expected 30-day move %.
**Typical range:** SPY: 0.10–0.25 in normal conditions; 0.30–0.60 during crises (March 2020 peaked near 0.80)
**How to read it:** `atm_iv_30d: 0.18` → expected 30-day move = 0.18 × √(30/252) ≈ 6.2% up or down (1 standard deviation)
**Green flag:** Close to ^VIX value / 100 for SPY (within ±0.02); plausible given current regime
**Red flag:** Zero or near-zero; greater than 0.80; differs from VIX/100 by more than 0.05 for SPY
**Depends on:** yfinance IV data quality for near-ATM strikes
**Limitation to know:** This is interpolated from available strikes. If the 30d maturity falls between two available expirations, a linear interpolation is used — which can distort the value when expirations are sparse.

---

### Output: iv_rank / iv_percentile

**Output name:** `iv_rank` (IVR) and `iv_percentile` (IVP)
**What it represents:** Two different answers to "is current vol cheap or expensive vs. history?" IVR asks where current vol sits in the range (high - low) over the past year. IVP asks what % of days in the past year had lower vol than today.
**Unit/format:** Float 0–1 (0 = historically cheapest, 1 = historically most expensive)
**Typical range:** Both 0–1; values < 0.30 = historically cheap, > 0.70 = historically elevated
**How to read it:** `iv_rank: 0.28` = current vol is 28% of the way from the 1-year low to the 1-year high. `iv_percentile: 0.31` = vol was lower than today on 31% of days in the past year.
**IVR vs IVP difference:** IVR is sensitive to spikes (one crisis day can compress the whole scale). IVP is more stable. Both should roughly agree — large divergence signals a spike year distorting IVR.
**Green flag:** IVR and IVP within ~0.10 of each other; `ivr_ivp_confidence: "standard"` (252+ days history)
**Red flag:** `ivr_ivp_confidence: "insufficient"` — if there are fewer than 252 days of history, these numbers are unreliable and should not be used for trade sizing decisions
**Depends on:** vol_signals table having ≥252 rows of history for each ticker
**Limitation to know:** Both metrics look backward 252 days (1 year). If last year was a low-vol year, "high IVR" today might still be absolute low vol historically. These are relative measures, not absolute.

---

### Output: skew_25d_rr (risk reversal)

**Output name:** `skew_25d_rr` — 25-delta risk reversal (skew)
**What it represents:** The difference in implied vol between 25-delta puts and 25-delta calls. Tells you whether the market is paying a premium for downside protection (put-buying demand) vs. upside calls. "Skew" in common usage.
**Unit/format:** Decimal (e.g., -0.041 = puts trade 4.1 vol points above equivalent calls). Negative = puts bid.
**Typical range (SPY):** -0.02 to -0.08; near zero in complacent markets; more negative in stress
**How to read it:** `skew_25d_rr: -0.041` means 25-delta puts carry 4.1 percentage points more IV than 25-delta calls. The market is paying extra for tail-risk insurance.
**Green flag:** Negative for equity tickers (structural put demand is normal); magnitude consistent with current VIX level
**Red flag:** Positive for SPY (calls more expensive than puts — very unusual, may indicate data error or extreme gamma squeeze conditions); near exactly zero (may indicate missing data or data quality issue)
**Depends on:** Sufficient options chain liquidity at the 25-delta strikes; yfinance chain quality
**Limitation to know:** This is computed from the nearest expiration that has both calls and puts with sufficient data. If that expiration is very short-dated (< 7 days), skew can spike erratically due to gamma effects and should not be compared to longer-dated historical readings.

---

### Output: vrp_proxy_signal (VRP classification)

**Output name:** `vrp_proxy_signal` — Volatility Risk Premium signal label
**What it represents:** Whether options are "expensive" or "cheap" relative to recent realized volatility. The VRP (Volatility Risk Premium) is the spread between what options imply vol will be (IV) and what vol has actually been (realized vol). A positive VRP means option sellers are being compensated. A negative VRP (inverted) means realized vol exceeded what was priced in.
**Unit/format:** String label from set: {significantly_elevated, moderately_elevated, near_parity, moderately_compressed, compressed, inverted}
**Typical range:** `moderately_elevated` or `near_parity` in normal markets; `significantly_elevated` in low-vol regimes; `inverted` during vol spikes
**How to read it:** `vrp_signal: "elevated_vrp"` → options are pricing in materially more vol than has been realized. Historically favorable for option-selling strategies (short vol, covered calls, etc.). `vrp_signal: "inverted"` → the market just experienced more vol than options priced in — option buyers benefited, sellers were hurt.
**Green flag:** Signal label is consistent with regime (e.g., RISK_ON_LOW_VOL + elevated_vrp is a coherent pair)
**Red flag:** `inverted` during a RISK_ON_LOW_VOL regime (should be rare; may indicate data quality issue with realized vol calculation); all tickers showing identical signal on a volatile day
**Depends on:** Quality of 30-day price history from yfinance; atm_iv_30d accuracy
**Limitation to know:** The proxy uses 21-day realized vol vs. 30-day IV. This tenor mismatch means the VRP estimate has a small systematic bias. It will look "elevated" in rising vol environments and "compressed" in falling vol environments purely from the window mismatch, not from true pricing inefficiency.

---

### Output: ts_shape (term structure shape label)

**Output name:** `ts_shape` — vol term structure shape classification
**What it represents:** Whether near-dated options are cheaper or more expensive than far-dated options. In normal markets, longer-dated options carry more uncertainty premium (contango). In stressed markets, short-dated options spike above longer-dated (backwardation).
**Unit/format:** String label from set: {steep_contango, mild_contango, flat, full_backwardation, humped, inverted_back, mixed}
**Typical range:** `mild_contango` or `steep_contango` in normal markets; `full_backwardation` during crises
**How to read it:** `ts_shape: "contango"` means 30d vol < 60d vol < 180d vol — normal market structure. `ts_shape: "full_backwardation"` means 30d vol > 60d vol > 180d vol — market is pricing near-term panic more than longer-term uncertainty.
**Green flag:** `contango` shapes during RISK_ON regimes; `backwardation` during RISK_OFF_STRESS (coherent pair)
**Red flag:** `full_backwardation` during RISK_ON_LOW_VOL regime (incoherent — may indicate data error or fast-moving intraday event); `mixed` shape is normal but if persistent, check that 180d IVs are actually populating
**Depends on:** Having valid IV data at 30d, 60d, and 180d tenors; sufficient expirations in the chain
**Limitation to know:** The shape classification is based on interpolated IV at fixed tenors. If the chain only has 3–4 expirations, the 180d point may require significant extrapolation beyond available data.

---

## KEY GAPS & RISKS SUMMARY

### Gap 1: yfinance Data Quality — High Severity
All options data, vol signals, VIX term structure, and price history come from Yahoo Finance's free, delayed feed. yfinance IV calculations are known to have errors on illiquid strikes and zero-bid options. There is no validation step that compares yfinance IV to an independent source. **You cannot validate these outputs without either: (a) a paid options data provider, or (b) manually checking a few strikes against a broker's platform on the same day.**

### Gap 2: IVR/IVP Reliability — Medium Severity
IV rank and IV percentile require 252 days (1 year) of history in the vol_signals table. If the table was created recently or was cleared, these outputs will show `ivr_ivp_confidence: "insufficient"` and should not be used for trade sizing. **Check the `ivr_ivp_confidence` field before trusting IVR/IVP values.**

### Gap 3: No Alerting on Failures — Medium Severity
The scheduler logs errors but has no alerting mechanism. If the FRED feed fails at 18:05, you won't know until you check logs manually. There is no email, Slack, or push notification on job failure.

### Gap 4: Hardcoded Fallback Rate — Low Severity
If the FRED API is unavailable, the risk-free rate falls back to a hardcoded 4.5%. In a rate-change environment, forward prices and all Greek calculations will be slightly off. This is not logged prominently — it requires checking the run logs to detect.

### Gap 5: No Real-Time Options Data — Architectural Constraint
The architecture explicitly marks the system as "not for live pre-trade decisions." A production deployment requiring live pricing would need Interactive Brokers, Bloomberg, or equivalent. This is by design, not a bug.

### Gap 6: FOMC Calendar Manual Maintenance
`FOMC_SCHEDULE_2026` is a hardcoded list in config.py. Each year requires a manual update. The macro_calendar table will show no future FOMC events after 2026 unless config.py is updated.

---

*Next audit: #2 — Marcus / Macro Layer (regime_classifier.py, snapshot_generator.py, dashboard)*
