# Audit #3: Sarah / Vol Layer
**Generated:** 2026-04-07
**Scope:** `systems/sarah/` (5 modules) + `research/signals/` (vol surface and signal extraction)

---

## DOCUMENT 1: CAPABILITY MAP

---

### Component: Vol Schema & DB Writer

**File path:** `systems/sarah/vol_db.py`
**Module:** Sarah / vol layer
**What it does:** Defines the database tables for Sarah's output and provides the write function that saves each ticker's daily vol signals to `trading.db`. It is the persistence layer — no calculations happen here.
**Inputs:**
- A `signals` dict produced by `daily_vol_run.py` (one per ticker per day)
- Reads config for `VOL_DB_PATH` — the path to `trading.db`
- Format: Python dict with ~28 named keys

**Outputs:**
- Writes to two tables in `trading.db`:
  - `vol_signals` — one row per (ticker, date) with all signal columns
  - `vol_surface` — raw surface data (strike × expiration grid); currently written as an empty schema (nothing populates strike-level rows in daily_vol_run.py)
- No return value; side-effect only

**Dependencies:**
- `systems/utils/db.py` for `get_connection()`
- `config.py` for `VOL_DB_PATH`

**Implementation status:** Complete for `vol_signals` table. `vol_surface` table is DDL-only — schema exists but no code writes to it.

**Gap vs architecture:**
- `vol_surface` table (the full strike × expiration grid) is defined but never populated. The architecture requires this for full surface visualization. Currently only ATM IV at three tenor points (30/60/180d) and a few skew delta slices are stored.
- `skew_by_delta_json` and `pc_oi_ratio_json` columns are always written as empty dicts `{}` — no code populates them yet.

---

### Component: Daily Vol Pipeline Orchestrator

**File path:** `systems/sarah/daily_vol_run.py`
**Module:** Sarah / vol layer — Stage 1
**What it does:** Runs the full daily vol data collection for all tickers in `VOL_TICKERS`. For each ticker it fetches the options chain, constructs the IV term structure, extracts skew, computes IV rank/percentile, estimates a VRP proxy, then saves everything to `trading.db` and writes `vol_signals.json` to `data/outputs/`.
**Inputs:**
- `data/outputs/regime_state.json` — required prerequisite from Marcus; fails loudly if missing or >80h old
- FRED API (risk-free rate, with fallback to 4.5%)
- yfinance (options chain + spot price history for RV calculation, 15–20 min delayed)
- CBOE feed (VIX term structure, VVIX — written to `vvix_daily` table)
- `trading.db` — reads existing IV history for IVR/IVP calculation
- Format: JSON file, API responses, database query results

**Outputs:**
- `data/outputs/vol_signals.json` — one JSON per run with all tickers' summary signals
- Rows inserted/updated in `trading.db.vol_signals` table
- Returns a summary dict (used if called programmatically from scheduler)

**Dependencies:**
- Marcus pipeline (regime_state.json must exist and be fresh)
- `research/signals/vol_surface.py` — term structure and skew construction
- `research/signals/vol_signals.py` — slope computation, VRP proxy, IV rank/percentile
- `systems/sarah/vol_db.py` — schema init and upsert
- `systems/data_feeds/options_feed.py`, `cboe_feed.py`

**Implementation status:** Complete. The weekend staleness window (80h) is intentional — Friday's regime covers Monday morning.

**Gap vs architecture:**
- P/C open interest ratio (`pc_oi_ratio_json`) is stored as empty dict. Not computed.
- `skew_by_delta_json` is stored as empty dict. Full delta-space skew surface not built.
- Vol regime classification uses spot VIX or ATM IV directly against hardcoded thresholds — not Marcus's regime state labels. This creates two parallel regime classifications that can diverge.

---

### Component: Vol Surface Construction

**File path:** `research/signals/vol_surface.py`
**Module:** Sarah / vol layer (shared signal library)
**What it does:** Takes raw options chain data and extracts the implied volatility at each tenor (ATM IV) and the skew at each wing delta (25Δ, 10Δ). These are the two key building blocks for everything downstream.
**Inputs:**
- `chain_data` dict from `options_feed.fetch_options_chain()` — keys are `{exp_str}_c` and `{exp_str}_p`, values are DataFrames
- Spot price (float) and risk-free rate (float)
- Format: dict of DataFrames

**Outputs:**
- `build_term_structure()` → `{dte_int: atm_iv_float}` — e.g. `{30: 18.3, 60: 19.1, 90: 20.4}` in vol points
- `extract_skew_slice()` → dict with `skew_25d_put`, `skew_25d_call`, `skew_25d_rr`, `skew_1025_ratio`
- Both passed to downstream signal extraction; not stored directly

**Dependencies:**
- `py_vollib` for implied volatility calculation (fallback within ATM extraction)
- `options_feed.py` (upstream) must populate `iv`, `delta`, `forward` columns on each chain DataFrame

**Implementation status:** Complete. ATM extraction averages call and put IVs at the closest-to-forward strike — a robust choice that reduces bid/ask noise.

**Gap vs architecture:**
- Skew uses only 25Δ and 10Δ. The architecture mentions full delta-space skew (every 5Δ from 5Δ to 50Δ). Currently only two delta points extracted.
- No arbitrage checks (calendar spread arbitrage, butterfly arbitrage). A contaminated chain can produce negative spreads and the code will not catch it.

---

### Component: Vol Signal Extraction

**File path:** `research/signals/vol_signals.py`
**Module:** Sarah / vol layer (shared signal library)
**What it does:** Three standalone functions that convert raw term structure and price data into the labeled signals stored in `vol_signals`. Computes term structure shape, the VRP proxy (options premium vs recent realized vol), and IV rank/percentile with confidence flags.
**Inputs:**
- `term_structure_slopes()`: `{dte: atm_iv}` dict from `build_term_structure()`
- `backward_vrp_proxy()`: current ATM IV (float) + price history (pd.Series)
- `iv_context()`: current IV (float) + IV history (pd.Series) + current VIX (float)
- All inputs are Python scalars or Series; no DB access

**Outputs:**
- `term_structure_slopes()` → dict with `iv_30`, `iv_60`, `iv_180`, `front_slope`, `back_slope`, `ts_shape` (6-state enum)
- `backward_vrp_proxy()` → dict with `rv_21d`, `vrp_proxy_bkwd` (spread in vol points), `vrp_proxy_signal` (6-state enum)
- `iv_context()` → dict with `iv_rank`, `iv_percentile`, `history_days`, `confidence` (3 levels), `regime_bias` flag

**Dependencies:**
- None beyond numpy/pandas. Fully self-contained.

**Implementation status:** Complete.

**Gap vs architecture:**
- VRP proxy is backward-looking only: compares 30d ATM IV to 21d *past* realized vol. True VRP requires comparing IV to *matched-maturity forward* realized vol — which cannot be computed in real time. The code documents this limitation explicitly, but it is a meaningful accuracy gap.
- IV Rank uses only the history accumulated since Sarah started running. If Sarah has been running for 90 days, IVR is computed over 90 days, not the 252-day (1-year) standard. The `confidence` field flags this explicitly but the output can be materially misleading in a thin history period.

---

### Component: Greeks Decomposition Tool

**File path:** `systems/sarah/greeks_tool.py`
**Module:** Sarah / vol layer — Stage 2
**What it does:** Given a specific option position (ticker, strike, expiration, quantity, long/short), computes all seven Greeks analytically using Black-Scholes and returns both raw per-contract and scaled per-position values, plus a mispricing flag and a plain-English interpretation block.
**Inputs:**
- User-specified position parameters: ticker (str), flag (call/put), strike (float), expiration (date str), quantity (int), long_short (str)
- Spot price and dividend yield: fetched live from yfinance
- IV: fetched from live options chain first, then stored ATM IV from `trading.db`, then fallback to 18% (always warned)
- Risk-free rate: fetched from FRED, fallback to 4.5%
- 25Δ skew (for mispricing flag): pulled from `trading.db`
- Format: function call with keyword args; returns dict

**Outputs:**
- Dict with keys: `position`, `market`, `greeks` (7 values per contract), `greeks_scaled` (signed × quantity × 100), `bs_flag`, `interpretation` (formatted text block)
- `aggregate_portfolio()`: net greeks across multiple positions + concentration flags for Vanna, Charm, Vomma
- Not stored to DB; returned to caller

**Dependencies:**
- `systems/utils/pricing.py` for `bs_greeks_full`, `bs_mispricing_flag`, `forward_price`
- `yfinance` for spot and live chain
- `trading.db` for stored ATM IV and skew
- `py_vollib` for IV calculation from option price

**Implementation status:** Complete. 7 Greeks computed: Delta, Gamma, Theta, Vega, Vanna, Charm, Vomma.

**Gap vs architecture:**
- No persistence. Greek snapshots are not stored anywhere — they live only in the caller's session. Portfolio aggregation works across a list of dicts passed in one call but has no persistent portfolio state.
- Mispricing flag uses 25Δ skew from stored vol_signals as a proxy for whether the BS model's flat-vol assumption is reasonable. This is a first-order heuristic, not a proper skew-adjusted Greek.
- No Rho (interest rate sensitivity). For short-dated options this is usually negligible, but it is part of the full Greek set.

---

### Component: Scenario P&L Engine

**File path:** `systems/sarah/scenario_engine.py`
**Module:** Sarah / vol layer — Stage 3
**What it does:** Given an analyzed position, produces multiple P&L projections: a spot × IV grid at four time checkpoints, P&L under six named historical stress scenarios (with skew-amplification for downside puts), implied expected move from the live straddle price, and a "kill scenario" showing the worst realistic outcome if spot goes nowhere and vol collapses.
**Inputs:**
- A `position` dict from `GreeksTool.analyze_position()` — contains all market and position parameters
- Optional: chain DataFrames (for implied expected move), spot VIX (for high-vol grid mode)
- Format: dict (position), optional DataFrames

**Outputs:**
- `scenario_pnl_grid()`: dict with DataFrames indexed by spot % change × IV shift (in vol points), one per time checkpoint. Shape: ~24 spot steps × 50 IV steps.
- `stress_scenario_pnl()`: single scenario result with flat-shift and skew-amplified P&L (dollars)
- `implied_expected_move()`: straddle-derived 1-SD move estimate (percent and dollar levels)
- `kill_scenario()`: single dict with max-realistic-loss dollar amount and conditions
- `compare_structures()`: formatted text table comparing multiple trade structures side-by-side
- Not stored to DB

**Dependencies:**
- `systems/utils/pricing.py` for `bs_price` (all P&L computed via BS)
- Upstream `GreeksTool.analyze_position()` output

**Implementation status:** Complete. Six named stress events calibrated with absolute vol point shocks (not percentages — an important distinction the code documents explicitly).

**Gap vs architecture:**
- All P&L uses flat Black-Scholes vol. The grid does not model skew — a 30Δ put in a steep-skew environment will show lower stress loss than reality because the vol expansion at the put wing is not captured (skew amplification is only applied to named stress scenarios, not the continuous grid).
- `compare_structures()` computes break-even at expiration, not at the thesis date. For long-dated positions this is correct; for event trades held to expiration it matters less, but for positions closed mid-way it understates the real break-even range.
- Stress scenarios are endpoint approximations, not path reconstructions. A position that would be stopped out mid-path (e.g. 2022 rate shock over 10 months) may show a smaller loss than reality.

---

### Component: Pre-Trade Intelligence Dashboard

**File path:** `systems/sarah/pretrade_dashboard.py`
**Module:** Sarah / vol layer — Stage 4
**What it does:** Assembles five panels of market context for a specific trade thesis: vol level (cost burden), term structure (expiration alignment), skew (wing cost differential), flow observations (structured entry of unusual activity), and a Bayesian-updated P&L distribution. Also writes a `pretrade_memo.json` contract to `data/outputs/`. The dashboard describes what the market is pricing; it does not recommend a direction.
**Inputs:**
- `TradeThesisInput` dataclass: ticker, expected_move (unsigned magnitude), thesis_days, catalyst_type, max_loss_budget
- Optional `FlowObservation` dataclass(es): structured flow notes (type, execution, size, DTE, delta approximation)
- Latest vol signals from `trading.db` (pulled internally)
- Format: dataclass instances

**Outputs:**
- Per-panel dicts: `vol_level_panel()`, `term_structure_panel()`, `skew_panel()`, `flow_panel()`, Bayesian P&L panel
- `data/outputs/pretrade_memo.json` — locked output contract (schema pinned in CLAUDE.md)
- Not stored to `trading.db`

**Dependencies:**
- `trading.db` (vol_signals table) for all market data
- `systems/utils/pricing.py` for BS approximations within panels
- `data/outputs/vol_signals.json` not read directly — pulls from DB instead

**Implementation status:** Complete across Stages 4 and 5. Five panels built.

**Gap vs architecture:**
- Flow panel (`FlowObservation`) accepts manually entered observations — there is no automated flow data feed. The structured dataclass prevents free-text slop, but the data itself must come from a user watching a platform like Unusual Whales or Cheddar Flow.
- Bayesian P&L distribution uses Black-Scholes for the prior and manual flow input as the update. There is no regime-conditional prior built in — the regime from Marcus is available but not wired into the Bayesian update.
- `catalyst_type` must be one of four hardcoded values (`event_specific`, `macro_catalyst`, `macro_slow`, `technical`). Fine for current use but brittle if the taxonomy expands.

---

### Component: Historical Regime Library & Analog Search

**File path:** `systems/sarah/regime_library.py`
**Module:** Sarah / vol layer — Stage 5
**What it does:** Three related capabilities: (1) builds a normalized 6-dimensional feature vector from today's vol surface state and searches historical `vol_signals` rows for the most similar past dates using Euclidean distance; (2) computes VIX and VVIX z-scores and a pre-transition flag (VVIX elevated while VIX is calm = early warning); (3) loads a hand-curated YAML library of named historical events for reference.
**Inputs:**
- Current vol surface snapshot (dict)
- Historical `vol_signals` rows from `trading.db` (DataFrame)
- VIX history from `macro.db` (pd.Series)
- VVIX history from `vvix_daily` table in `trading.db` (pd.Series)
- Macro compatibility filter (dict: exclude zero-rate era, require regime match)
- Named event library: `data/events/regime_events.yaml`
- Format: dicts, DataFrames, YAML file

**Outputs:**
- `analog_search()`: DataFrame of top-N most similar historical dates with similarity scores and all signal columns
- `compute_vix_vvix_signals()`: dict with `vix_z1y`, `vvix_z1y`, `vvix_vix_ratio`, `pre_transition_flag`
- `pre_transition_monitor()`: dict with warnings list, confidence assessment, and pre-transition flag
- `load_event_library()` / `event_browser()` / `list_events()`: event YAML access functions

**Dependencies:**
- `trading.db` (vol_signals, vvix_daily tables)
- `macro.db` (macro_series table, series_id='vix')
- `data/events/regime_events.yaml` must exist and be curated manually
- 252 days of VVIX history required for reliable z-score; fewer returns `insufficient_history` confidence

**Implementation status:** Complete. The similarity score formula (`1 / (1 + dist)`) is a valid monotonic transformation.

**Gap vs architecture:**
- Analog search is only as good as Sarah's accumulated history. With less than 252 days of `vol_signals` rows, the feature vectors are comparing against a very thin pool. The code logs a warning but proceeds.
- `vix_z1y` is computed from `macro_series` in `macro.db`, which depends on Marcus's data pipeline running. If Marcus hasn't run recently, this feature will use stale or missing VIX data without a loud failure.
- VVIX z-score requires 252 days of `vvix_daily` data. Since VVIX collection only started when Sarah Stage 1 first ran, it will take ~1 year of live operation before this signal is reliable. Until then, the pre-transition monitor will output `insufficient_history` for most users.

---

## DOCUMENT 2: OUTPUT LITERACY

---

**Output name:** ATM IV 30d (`atm_iv_30d`)
**What it represents:** The implied volatility of an at-the-money option expiring in approximately 30 days. Think of it as the market's consensus estimate of how much the underlying will move over the next month, expressed as an annualized percentage.
**Unit/format:** Float, vol points (e.g. 18.3 means 18.3% annualized volatility)
**Typical range:** 10–80 for equity indices and large-cap stocks in normal to stressed markets. SPY in calm periods: 12–18. SPY in stressed periods: 25–80.
**How to read it:** If `atm_iv_30d` = 18.0, the market is pricing in roughly ±18% annualized movement — which translates to approximately ±5.2% over 30 days (18% ÷ √12).
**Green flag:** Value in line with recent history, `ivr_confidence` = 'standard', no `regime_bias` flag.
**Red flag:** Value is 0 or None (chain fetch failed). Value above 100 or below 3 (almost certainly a data error). Value wildly inconsistent with spot VIX for the same date.
**Depends on:** Quality of the options chain from yfinance. If market is closed or yfinance has a feed issue, this will be None for that day.
**Limitation to know:** This is a single number extracted at a single expiration. It does not tell you whether vol is cheap or expensive relative to history — that's what IV Rank and IV Percentile answer.

---

**Output name:** IV Rank (`iv_rank`)
**What it represents:** Where today's ATM IV sits within its own historical range (min to max). A rank of 0.75 means today's IV is 75% of the way between the lowest and highest IV ever recorded in the history window.
**Unit/format:** Float 0–1 (0 = at historical low, 1 = at historical high)
**Typical range:** 0.0–1.0 by definition. In practice, most calm periods cluster 0.1–0.5.
**How to read it:** IV Rank = 0.85 means today's vol is near the top of its historical range — options premium is historically expensive. IV Rank = 0.15 means premium is historically cheap.
**Green flag:** `ivr_confidence` = 'standard' (120+ days of history), `regime_bias` = null.
**Red flag:** `ivr_confidence` = 'insufficient' or 'low' (fewer than 60 or 120 days of history) — the rank is mathematically valid but statistically meaningless. `regime_bias` populated — a systematic skew is present that makes the number misleading.
**Depends on:** Accumulated history in `trading.db`. After launch, IV Rank will be unreliable for 3–6 months. The `confidence` field tells you exactly how much history is behind the number.
**Limitation to know:** IV Rank is sensitive to outliers. One spike event in the history window (e.g. a COVID-style move) will compress all other readings toward 0. This makes IV Rank structurally low for years after a major stress event. IV Percentile is less sensitive to this problem.

---

**Output name:** IV Percentile (`iv_percentile`)
**What it represents:** The fraction of past days where ATM IV was *lower* than today. A percentile of 0.80 means IV was lower than today's level on 80% of historical trading days.
**Unit/format:** Float 0–1
**Typical range:** 0.0–1.0. Differs from IV Rank — can diverge significantly after a stress event.
**How to read it:** IV Percentile = 0.30 means vol is in the lower third of its historical distribution. On 70% of past days, vol was higher than it is today — relatively cheap.
**Green flag:** Consistent with IV Rank (both high or both low). Divergence between IVR and IVP is informative — see limitation below.
**Red flag:** Same confidence caveats as IV Rank. Both suffer equally from thin history.
**Depends on:** Same history accumulation as IV Rank.
**Limitation to know:** IV Rank and IV Percentile diverge after stress events. If there was one major spike two years ago, IVR will show that today's vol is "low" (far from the spike high), while IVP might show it's "moderate" (many days were actually calmer). When they diverge, IVP is usually more representative of typical conditions.

---

**Output name:** VRP Proxy (`vrp_proxy_bkwd`, `vrp_proxy_signal`)
**What it represents:** The "volatility risk premium" — how much more the market is paying for options (implied vol) than what the underlying has actually moved recently (realized vol). A positive VRP means options are priced rich relative to recent movement; selling premium has historically been compensated.
**Unit/format:** `vrp_proxy_bkwd` = float in vol points (e.g. +4.2 means IV is 4.2 vol points above recent RV). `vrp_proxy_signal` = categorical string (6 states: `significantly_elevated`, `moderately_elevated`, `near_parity`, `moderately_compressed`, `compressed`, `inverted`).
**Typical range:** VRP proxy of +1 to +6 is normal for equity indices. Compression toward 0 or inversion is unusual and often precedes vol spikes.
**How to read it:** `vrp_proxy_bkwd` = +5.0, signal = `significantly_elevated`: the market is paying 5 vol points more for options than recent movement justifies. Historically this environment has favored option sellers.
**Green flag:** Signal is `moderately_elevated` or `significantly_elevated` in a calm macro regime — structural premium present.
**Red flag:** Signal is `compressed` or `inverted` — options may be cheap, or recent realized vol has surged and IV hasn't caught up (the latter is more dangerous for sellers).
**Depends on:** 22 days of price history from yfinance (for realized vol), plus a valid `atm_iv_30d`.
**Limitation to know:** This is backward-looking by construction. It compares 30d IV (forward-looking) to 21d *past* realized vol. These windows don't match. A proper VRP calculation requires forward realized vol, which you can only know in hindsight. This proxy can be consistently positive even when options are fairly priced — do not read it as "options are expensive, sell them" without macro context.

---

**Output name:** 25Δ Risk Reversal (`skew_25d_rr`)
**What it represents:** The difference between the implied vol of a 25-delta call and a 25-delta put at the same expiration. A negative number means puts are priced richer than calls — the market is paying more for downside protection. This is called "put skew" or "negative skew."
**Unit/format:** Float in vol points. Typically negative for equity indices (e.g. -3.5 means 25Δ put IV is 3.5 vol points higher than 25Δ call IV).
**Typical range:** -8 to -1 for large-cap equities in normal conditions. Steeper than -8 during stress.
**How to read it:** `skew_25d_rr` = -4.2: put wings are 4.2 vol points richer than call wings. Buying puts is structurally more expensive than buying calls of equivalent delta.
**Green flag:** Value present and in a historically normal range. Consistent with current VIX level.
**Red flag:** Value near 0 or positive (puts cheaper than calls) — unusual and potentially data quality issue for equity indices. Value more negative than -10 without a concurrent VIX spike — check chain quality.
**Depends on:** Quality of delta column in the options chain. Delta must be populated by `options_feed.py`. If delta is missing, skew extraction returns None.
**Limitation to know:** This captures only the 25Δ wing. It does not tell you whether the 10Δ or 5Δ tails are rich or cheap relative to 25Δ — that's what `skew_1025_ratio` addresses. Skew can look normal at 25Δ while the deep tails are extremely expensive (or cheap).

---

**Output name:** Term Structure Shape (`ts_shape`, `ts_front_slope`, `ts_back_slope`)
**What it represents:** Whether vol is higher for near-term or longer-dated options. Normal markets are in "contango" (longer-dated options cost more). Backwardation (near-term more expensive than longer-dated) indicates stress or an anticipated near-term event.
**Unit/format:** `ts_shape` = string enum (6 states). `ts_front_slope` = float in vol points (iv_60 − iv_30). `ts_back_slope` = float in vol points (iv_180 − iv_60).
**Typical range:** Front slope: +1 to +5 in normal contango. Negative (< -1) during stress or pre-event.
**How to read it:** `ts_shape` = `steep_contango`, `ts_front_slope` = +3.5: near-term options are significantly cheaper than longer-dated ones. Favorable for buying short-dated options. `ts_shape` = `humped`, `ts_front_slope` = -2.0, `ts_back_slope` = +1.5: near-term is richest (event premium in front), back-end is normal. Buying through the event expiration is expensive.
**Green flag:** Shape is `mild_contango` or `steep_contango` in a calm regime — normal market structure.
**Red flag:** Shape is `full_backwardation` outside of an obvious stress event — check data quality. Shape is `humped` with no known catalyst — something the market knows that you may not.
**Depends on:** Having at least two valid IV data points at different expirations. If only one expiration has liquid options, term structure calculation returns an error.
**Limitation to know:** The three tenor points (30/60/180d) are interpolated — not necessarily directly observed from listed expirations. If the nearest listed expiration is 45 days out, the "30d" IV is an extrapolation, not a market observation.

---

**Output name:** Kill Scenario (`max_realistic_loss`)
**What it represents:** The maximum realistic loss if the thesis is simply wrong in the most painful way: spot goes nowhere and volatility mean-reverts lower. This is not the absolute worst case (that would be a gap move against you while vol spikes) — it's the worst *realistic* outcome for a long-vol position.
**Unit/format:** Float in dollars (negative = loss per N contracts at quantity specified)
**Typical range:** Depends entirely on position size and premium paid. For a single SPY ATM call, might be -$400 to -$800.
**How to read it:** `max_realistic_loss` = -$620: if spot stays flat and IV compresses 8 vol points over 30 days, this position loses $620 per contract. If this exceeds your `max_loss_budget` from `TradeThesisInput`, the position is too large or the structure is wrong.
**Green flag:** Loss is within the `max_loss_budget` specified in the thesis.
**Red flag:** Loss significantly exceeds `max_loss_budget` — the position sizing or structure needs revisiting before entry.
**Depends on:** The IV compression magnitude (default -8 vol points) and time elapsed (default 30 days). These defaults are reasonable but arbitrary. Adjust for the specific thesis.
**Limitation to know:** This models spot staying exactly flat. A small adverse move combined with vol compression (very common) is not captured here — the actual worst-realistic-case for directional buyers is often a small move the wrong way plus vol crush, not flat spot.

---

**Output name:** Analog Search Results
**What it represents:** The N historical dates where the vol surface looked most similar to today, filtered for macro regime compatibility. Tells you: "the last times the market looked like this, here's what happened next."
**Unit/format:** DataFrame with columns: date, similarity (float 0–1), and all vol_signals columns for that date.
**Typical range:** Similarity scores cluster between 0.3–0.8 for meaningful analogs. A score >0.9 would indicate near-identical surface conditions.
**How to read it:** The top result has similarity = 0.72 and date = 2023-08-15: the vol surface on 2023-08-15 was more similar to today's than any other historical day. You can look up what happened in the following 30 days as a reference, not a forecast.
**Green flag:** Multiple analogs with similarity >0.5, covering different time periods (diverse analogs are more informative than a cluster of consecutive days).
**Red flag:** All analogs cluster within a short date range (means the system has limited diverse history). Similarity scores all below 0.3 (today's surface is unlike anything in the history — useful information, but means analogs are unreliable). `insufficient_history` warning in the log.
**Depends on:** Accumulated history in `trading.db`. Minimum meaningful use requires ~252 days (1 year) of Sarah running daily. In the first year, analogs are drawn from a thin pool.
**Limitation to know:** Analog search tells you what surfaces *looked like* in the past — not what *happened* after them. You must manually research the outcome of each analog date. The system does not compute forward returns from analogs.

---

**Output name:** Pre-Transition Flag (`pre_transition_flag`)
**What it represents:** A binary early-warning signal that fires when vol-of-vol (VVIX — a measure of how uncertain the market is about vol itself) is elevated relative to its history, while VIX (current vol) is not elevated. This pattern has historically preceded regime transitions.
**Unit/format:** Boolean (`true`/`false`) + supporting signals: `vix_z1y` (float), `vvix_z1y` (float), `vvix_vix_ratio` (float), `confidence` (string)
**Typical range:** The flag fires rarely in calm markets. VVIX/VIX ratio: 3.5–6.0 is normal; >6.0 flags elevated uncertainty.
**How to read it:** `pre_transition_flag` = true, `vvix_z1y` = 1.8, `vix_z1y` = 0.2: VVIX is nearly 2 standard deviations above its 1-year average, while VIX is near its average. The market is more uncertain about the *path of volatility* than current vol itself — historically a caution sign.
**Green flag:** Flag is false, confidence is 'reliable', VVIX/VIX ratio below 5.
**Red flag:** Flag is true with 'reliable' confidence and ratio >6.0. Also: confidence = 'insufficient_history' means you cannot trust the flag either way.
**Depends on:** 252 days of VVIX history in `vvix_daily`. Since VVIX collection starts when Sarah first runs, this signal is unavailable for the first ~1 year of operation.
**Limitation to know:** This is a caution flag, not a timing signal. The pattern can persist for weeks or months before a transition occurs, and it can fire and resolve without a transition. Do not use as an entry or exit trigger.

---

## VALIDATION REQUIREMENTS

To verify any of Sarah's outputs are correct, you would need:

1. **To validate ATM IV:** Pull the same ticker's options chain from a second source (e.g. IBKR, CBOE) on the same day and compare the 30d ATM IV. Differences of >0.5 vol points suggest a data quality issue.

2. **To validate IV Rank/Percentile:** Wait until Sarah has accumulated 252 days of data. Before that, the numbers are statistically unreliable by design.

3. **To validate VRP proxy:** Compare `rv_21d` against the actual 21-day annualized return standard deviation for the same ticker over the same period. If they differ by more than 1 vol point, the price history fetch is returning incorrect data.

4. **To validate term structure shape:** On any given day, compare `ts_shape` output to what you observe directly in a listed options chain (e.g. SPY 30d vs 60d vs 90d IV on your broker platform). The shape (contango/backwardation) should be obvious to the eye.

5. **To validate analog search:** Check whether the top analog dates show up in known historical vol research (e.g. known pre-spike periods for VIX). If the system returns random or consecutive dates as top analogs, the feature normalization may be faulty.

6. **To validate pre-transition flag:** Cross-reference VVIX readings with CBOE's published VVIX data directly. The `vvix_z1y` z-score should be verifiable against CBOE's public VVIX history.
