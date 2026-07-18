# Audit 2: Marcus / Macro Layer

**Files audited:**
- `systems/signals/regime_classifier.py`
- `systems/dashboard/macro_dashboard.py`
- `systems/reports/snapshot_generator.py`
- `config.py` (macro constants, weights, thresholds)

---

## DOCUMENT 1: CAPABILITY MAP

---

### Component: RegimeClassifier

**Component name:** RegimeClassifier  
**File path:** [systems/signals/regime_classifier.py](../../systems/signals/regime_classifier.py)  
**Module it belongs to:** Marcus / Macro  

**What it does:**  
Reads the latest macro data from DuckDB, scores six dimensions of the economy (volatility, credit, yield curve, inflation, labor, positioning) each on a -1 to +1 scale, combines those scores using fixed weights, and maps the weighted sum to one of six discrete regime labels. This is the single upstream output that all downstream components (Sarah, Jordan, Kai) must read before running.

**Inputs:**
- `macro_series` table in `macro.db` — FRED time series (VIX, HY spread, yield curve, breakeven inflation, PCE, unemployment, jobless claims, M2, oil, etc.)
- `cot_positioning` table in `macro.db` — CFTC Commitments of Traders data for SP500 futures
- All accessed via `get_latest()` and `get_series_history()` from `systems/utils/db.py`
- Format: individual scalar values and short DataFrames per series

**Outputs:**
- `RegimeResult` dataclass — in-memory Python object containing regime label, composite score, six component scores, confidence, bullish/bearish signal lists, divergence signal, and per-component data dates
- Persisted to `regime_history` table in `macro.db` when `persist=True` (default)
- Written to `data/outputs/regime_state.json` via `write_output_contract()` — this is the locked output contract all downstream components consume
- Format: dataclass in memory, DuckDB row in DB, JSON file on disk

**Dependencies:**
- `macro_feed.py` must have run first to populate `macro_series` and `cot_positioning` tables
- `systems/utils/db.py` — all DB access
- `config.py` — `REGIME_THRESHOLDS`, `COMPONENT_WEIGHTS`, `DUCKDB_PATH`
- If `regime_history` table is empty, `get_history()` returns an empty DataFrame — the dashboard degrades but does not fail

**What breaks if this fails:**
- `regime_state.json` is not updated → Sarah, Jordan, and Kai are blocked (by rule: they fail loudly if `written_at` is > 12 hours old)
- The dashboard loses its regime card and attribution panel
- `snapshot_generator.py` fails on `RegimeClassifier().classify()`

**Implementation status:** Appears complete

**Gap vs architecture:**
- No gaps vs stated architecture. All six components are scored, weighted, and mapped. Attribution, divergence detection, persistence stats, and regime change probability are all built.
- One nuance: `nfp_3m_avg` is defined in the `MacroSnapshot` dataclass but never populated by `_load_snapshot()` — the field exists, NFP data is in `macro_series`, but the 3-month average is not computed. Labor scoring uses unemployment level + delta + jobless claims z-score instead. This is a minor omission; the current proxies are reasonable.
- Positioning only scores SP500 futures (one instrument). The `CFTC_INSTRUMENTS` list in config.py includes NASDAQ, EURUSD, GOLD, WTI, BONDS_10Y, but only SP500 is used in scoring.

---

### Component: Regime Attribution + Divergence Detection

**Component name:** `attribution()`, `regime_change_probability()`, `_score_divergence()` methods on `RegimeResult` / `RegimeClassifier`  
**File path:** [systems/signals/regime_classifier.py](../../systems/signals/regime_classifier.py) lines 135–243, 645–723  
**Module it belongs to:** Marcus / Macro  

**What it does:**  
Three analytical layers that run after the base classification. Attribution identifies which components are driving vs. contradicting the current regime and estimates how far the score is from flipping to the next regime. Divergence detection flags when two components are sending contradictory signals (e.g., credit stress rising while vol stays calm). Regime change probability gives a 0–85% heuristic estimate of switching regimes within ~30 days.

**Inputs:**
- `RegimeResult` object (output of `classify()`)
- Optionally: 10-row history DataFrame for momentum factor in `regime_change_probability()`
- All inputs are in-memory Python objects — no additional DB calls

**Outputs:**
- `attribution()` → dict with keys: `drivers`, `contradictors`, `flip_watch`, `composite`, `nearest_regime`, `nearest_gap`
- `regime_change_probability()` → dict with keys: `probability` (float 0–1), `label` (string), `toward` (regime name), `drivers` (list of strings)
- `_score_divergence()` → dict with `type`, `severity`, `label`, `detail`, `components`, `spread` — or `None` if no divergence
- Attribution dict is used by `snapshot_generator.py` for the PDF. Divergence is stored in `regime_history` table.

**Dependencies:**
- `COMPONENT_WEIGHTS` and `SCORE_TO_REGIME` thresholds from `config.py`
- `DIVERGENCE_THRESHOLD_VC`, `DIVERGENCE_THRESHOLD_VL` from `config.py`

**Implementation status:** Appears complete

**Gap vs architecture:**
- Divergence thresholds are explicitly marked as "set a priori — calibrate after backfill." The comment in `config.py` references a calibration script (`scripts/calibrate_divergence_threshold.py`) that does not appear to exist in the codebase. The thresholds work but have not been empirically validated against historical data.
- `regime_change_probability()` caps at 85% — this is a deliberate design choice (not a bug) to prevent overconfident signals, but the heuristic weights (0.5, momentum up to 0.4, divergence 0.10–0.20) have no empirical grounding in the current codebase.

---

### Component: Macro Dashboard

**Component name:** Macro Dashboard (Dash app)  
**File path:** [systems/dashboard/macro_dashboard.py](../../systems/dashboard/macro_dashboard.py)  
**Module it belongs to:** Marcus / Macro  

**What it does:**  
A locally-hosted interactive dashboard (Dash/Plotly) that visualizes the current regime state and its history. Displays the current regime label, component score bars with staleness indicators, cross-asset signal charts (VIX, HY spreads, yield curve), regime transition log, divergence history, and regime-conditional return statistics. Auto-refreshes every hour.

**Inputs:**
- `macro.db` via `get_connection()` — reads `regime_history`, `macro_series`, `cot_positioning`, `macro_calendar` tables
- `RegimeClassifier.classify(persist=True)` — runs a fresh classification on each refresh
- Format: DuckDB queries returning pandas DataFrames

**Outputs:**
- Rendered HTML at `http://127.0.0.1:8050` — interactive charts and tables
- No file output (display only)
- PDF export button calls `snapshot_generator.generate_snapshot(return_bytes=True)` for download

**Dependencies:**
- `systems/signals/regime_classifier.py` — runs fresh classify on each page load
- `systems/utils/db.py` — all DB access
- `systems/reports/snapshot_generator.py` — for PDF download
- `config.py` — dashboard layout constants, colors, staleness thresholds, divergence thresholds

**What breaks if this fails:**
- Dashboard is display-only; its failure does not affect any upstream or downstream pipeline components

**Implementation status:** Appears complete

**Gap vs architecture:**
- The `regime_conditional return` tab queries a `regime_return_stats` table. This table is written by a separate script (`compute_regime_return_stats.py`) not visible in the current file list. If that script has never been run, this tab renders empty — not an error, but a silent gap in what the dashboard can show.
- Dashboard runs `classify(persist=True)` on every page load, meaning it writes to `regime_history` on each browser refresh. This could produce duplicate rows if refreshed multiple times on the same day. The `INSERT OR REPLACE` logic in `_persist()` handles this by keying on `date`, so duplicates overwrite rather than multiply — but it means dashboard refreshes are silently writing to the DB.

---

### Component: Snapshot Generator

**Component name:** PDF Snapshot Generator  
**File path:** [systems/reports/snapshot_generator.py](../../systems/reports/snapshot_generator.py)  
**Module it belongs to:** Marcus / Macro  

**What it does:**  
Generates a one-page PDF report summarizing the current macro regime: label, composite score, confidence, component score chart, regime history chart, persistence statistics, upcoming macro calendar events, and attribution breakdown. Can be triggered from the dashboard, a scheduler, or the command line.

**Inputs:**
- `RegimeClassifier().classify(persist=False)` — fresh classification (does not write to DB)
- `get_days_in_current_regime()` and `get_regime_persistence_stats()` — from `macro_dashboard.py`
- `macro_calendar` table in `macro.db`
- Format: Python objects and DuckDB queries

**Outputs:**
- PDF file at `data/snapshots/macro_YYYY-MM-DD_HHMMSS.pdf` (auto-named)
- Or PDF bytes returned in-memory for dashboard download
- Format: binary PDF

**Dependencies:**
- `reportlab`, `plotly` — external rendering libraries
- `systems/signals/regime_classifier.py`
- `systems/dashboard/macro_dashboard.py` — reuses chart builder functions
- `config.py` — `REGIME_COLORS`

**Implementation status:** Appears complete

**Gap vs architecture:**
- No gaps. This is a reporting/export utility with no architectural role in the pipeline.

---

## DOCUMENT 2: OUTPUT LITERACY

---

### Output: `regime_state` (regime label)

**Output name:** Regime label  
**What it represents:** A six-category summary of the current macro environment, from best conditions for taking risk to worst. Think of it as the market's "weather forecast" — it tells you whether conditions broadly favor holding risk positions or reducing them.

**Unit/format:** String, one of: `RISK_ON_LOW_VOL`, `RISK_ON_ELEVATED_VOL`, `NEUTRAL`, `CAUTION`, `RISK_OFF_STRESS`, `CRISIS`

**Typical range:** In a normal market, you'd expect to spend most time in `RISK_ON_LOW_VOL`, `RISK_ON_ELEVATED_VOL`, or `NEUTRAL`. `CAUTION` is elevated stress. `RISK_OFF_STRESS` and `CRISIS` correspond to periods like late 2022 or March 2020.

**How to read it:** `RISK_ON_LOW_VOL` means the macro backdrop is broadly favorable — volatility is contained, credit markets are calm, the yield curve isn't flashing recession warnings, and inflation is under control. `CAUTION` means enough components are deteriorating that you should reduce exposure or tighten risk parameters. `CRISIS` means system-level stress; historically this maps to VIX > 35 and HY spreads near or above 900bps simultaneously.

**Green flag:** Label changes slowly (weeks, not days) and matches the intuitive read of financial news. If conditions look fine and you're seeing `RISK_OFF_STRESS`, something is wrong in the data pipeline.

**Red flag:** Label oscillates between two categories on consecutive daily runs without a clear market event. This suggests a component score is right at a threshold boundary — look at the composite score; if it's hovering near +0.25 or -0.10, small data revisions will flip the label back and forth.

**Depends on:** VIX (vol component, 25% weight) and HY spread (credit component, 25% weight) dominate. If either of these inputs is stale or missing, the regime label is unreliable.

**Limitation to know:** This is a lagging-to-coincident indicator, not a predictive one. It tells you what the macro environment looks like *right now*, not where it's going. The `regime_change_probability` output attempts to address this but is a heuristic, not a forecast.

---

### Output: `composite_score`

**Output name:** Composite score  
**What it represents:** A single number summarizing the overall macro environment on a scale from -1 (crisis) to +1 (ideal risk-on). It's the weighted average of six component scores and is the direct input to the regime label mapping.

**Unit/format:** Float, range approximately -1.0 to +1.0 (can slightly exceed bounds before clamping at the regime mapping stage)

**Typical range:** -0.4 to +0.8 during normal conditions. Values below -0.4 indicate meaningful stress. Values above +0.6 indicate genuinely favorable conditions.

**How to read it:** `+0.42` means the macro backdrop is modestly risk-on — conditions favor risk positions but not at the extreme. `−0.30` means conditions are deteriorating but not yet at full stress levels. The thresholds that map scores to regime labels are: ≥+0.60 → RISK_ON_LOW_VOL, ≥+0.25 → RISK_ON_ELEVATED_VOL, ≥-0.10 → NEUTRAL, ≥-0.40 → CAUTION, ≥-0.65 → RISK_OFF_STRESS, below that → CRISIS.

**Green flag:** Score is stable day-to-day (moving <0.05 per day absent a major event). Score and regime label are directionally consistent with what you'd read in financial news.

**Red flag:** Score moves more than 0.15 in a single day without a major market event. This almost always means a data revision arrived (FRED revises historical data), not a real regime shift. Check the `missing_inputs` field — if a key series dropped out, the score may have shifted because a component defaulted to 0.

**Depends on:** All six components, but Vol (25%) and Credit (25%) dominate. A missing VIX or HY spread reading will cause the composite to drift toward 0 (the default for a missing component), which can artificially improve or worsen the score.

**Limitation to know:** The component weights (25/25/20/10/15/5) are set a priori in `config.py` and have not been empirically calibrated against historical regime returns. The weights reflect a reasonable expert view but are not derived from data.

---

### Output: Component scores (`vol_score`, `credit_score`, `curve_score`, `inflation_score`, `labor_score`, `positioning_score`)

**Output name:** Six component scores  
**What it represents:** Each score answers one question about a specific dimension of the macro environment. Vol: "Is market fear elevated?" Credit: "Are corporate borrowers stressed?" Curve: "Is the yield curve signaling recession?" Inflation: "Is inflation putting pressure on Fed policy?" Labor: "Is the job market deteriorating?" Positioning: "Are speculative investors overcrowded in one direction?"

**Unit/format:** Float, range -1.0 to +1.0 per component (clamped). Positive = bullish/supportive, negative = bearish/stressful.

**Typical range:** Most components sit in the -0.5 to +0.8 range during normal conditions. A component hitting -1.0 or +1.0 indicates an extreme reading on that dimension.

**How to read them:**
- Vol score `+0.60`: VIX is below 15 (very low fear), trend is neutral → strong tailwind
- Credit score `-0.70`: HY spreads are wide (above 600bps) → credit markets are stressed
- Curve score `-0.80`: yield curve is inverted (10Y-2Y below -10bps) → historical recession signal
- Inflation score `-0.30`: 10Y breakeven is elevated (2.5-3.0%) → inflation is a headwind for Fed
- Labor score `+0.40`: unemployment is below 4% and claims are stable → labor market strong
- Positioning score `-0.20`: SP500 specs are slightly net long → mild crowding, modest headwind

**Green flag:** Components that logically should agree (vol and credit, or labor and curve) point in the same direction. High confidence (`HIGH`) typically requires 4 of 5 non-positioning components to agree.

**Red flag:** Vol and credit strongly disagree (one at +0.8, other at -0.8). This triggers the `LEADING_STRESS_WARNING` or `ELEVATED_VOL_UNCONFIRMED` divergence signal. This is worth investigating manually — it usually means either a technical vol spike or early-stage credit deterioration that hasn't yet shown up in vol.

**Depends on:** Each component has its own primary series. Vol depends on VIX (daily), credit depends on HY spread (daily), curve depends on 10Y-2Y spread (daily), inflation depends on 10Y breakeven (daily), labor depends on jobless claims (weekly, primary) and unemployment (monthly, secondary), positioning depends on CFTC COT data (weekly).

**Limitation to know:** Component scores use hard thresholds (e.g., VIX > 25 → score = -0.6), not continuous functions. This means a VIX reading of 24.9 and 25.1 produce very different scores. This "cliff" behavior can cause the composite score to jump discontinuously when a series crosses a threshold boundary.

---

### Output: `confidence`

**Output name:** Confidence level  
**What it represents:** How much the six component scores agree with each other. High confidence means most components are telling the same story. Low confidence means the components are mixed — some bullish, some bearish — making the regime label less reliable.

**Unit/format:** String — `HIGH`, `MEDIUM`, or `LOW`

**Typical range:** `MEDIUM` is most common in normal conditions. `HIGH` appears at extremes (clear risk-on or clear stress). `LOW` appears during transitions.

**How to read it:** `HIGH` confidence + `RISK_ON_LOW_VOL` means at least 4 of 5 main components are positive, and you can reasonably trust the label. `LOW` confidence + `NEUTRAL` means the regime label is almost meaningless — components are split and the composite just landed in the neutral bucket by averaging out.

**Green flag:** Confidence is `HIGH` and matches your intuitive read of the market. `MEDIUM` is normal and expected.

**Red flag:** `HIGH` confidence on a `NEUTRAL` label is structurally impossible given the implementation (NEUTRAL requires a mix of positive and negative components). If you see it, there may be a bug. `LOW` confidence at an extreme regime (`RISK_OFF_STRESS` or `CRISIS`) is also unusual and worth investigating.

**Depends on:** How the 5 non-positioning component scores distribute across positive/negative. Positioning is excluded from the confidence calculation (it's contrarian and often disagrees directionally).

**Limitation to know:** Confidence is a count of agreeing components, not a measure of signal strength. Five weakly positive scores (+0.1 each) produce `HIGH` confidence even though the underlying signals are barely above zero.

---

### Output: Divergence signal

**Output name:** Divergence signal  
**What it represents:** A flag that fires when two major components are sending contradictory signals — specifically when volatility and credit markets disagree about how stressed conditions are. The most actionable version is `LEADING_STRESS_WARNING`: credit spreads are widening while vol is still calm, which historically precedes a vol spike.

**Unit/format:** Dict with `type` (string), `severity` (`HIGH`/`MEDIUM`/`LOW`), `label` (short description), `detail` (explanation), `components` (list), `spread` (float). Returns `None` when no divergence is detected.

**Typical range:** This signal fires infrequently. In stable regimes, `_score_divergence()` returns `None`. Expect it to fire during transition periods, geopolitical shocks, or early-stage credit deterioration.

**How to read it:**
- `LEADING_STRESS_WARNING` (HIGH): Credit is deteriorating but vol hasn't reacted yet. This is the most actionable signal — credit often leads vol by days to weeks. Worth reviewing your current exposure.
- `ELEVATED_VOL_UNCONFIRMED` (MEDIUM): Vol is elevated but credit is calm. Usually a technical spike — geopolitical event, short squeeze, positioning unwind. Lower probability of regime transition than Config A.
- `LABOR_LAG_WARNING` (MEDIUM): Both vol and credit are stressed but labor data (unemployment) still looks fine. Unemployment is a lagging indicator; the warning is that the stress is real and labor hasn't caught up yet.
- `BROAD_COMPONENT_DIVERGENCE` (LOW): More than 1.2 points separate the highest and lowest component scores. Background noise signal — elevated uncertainty, not an actionable alert on its own.

**Green flag:** Returns `None` in stable regimes.

**Red flag:** `LEADING_STRESS_WARNING` is active and you are holding large short-vol positions. Credit market deterioration while vol is calm is a classic setup before sudden vol spikes.

**Depends on:** VIX and HY spread data quality above all else. If either is stale or missing, the component scores will be 0 (missing → neutral default), making the divergence spread artificially small and suppressing the signal.

**Limitation to know:** Divergence thresholds (0.6 for Vol/Credit, 0.7 for Vol/Labor) were set by judgment, not calibrated against historical data. The code comments acknowledge this explicitly: "Threshold set a priori — calibrate against backfill." A calibration script is referenced but does not currently exist. Treat these thresholds as directionally reasonable but not validated.

---

### Output: `regime_change_probability`

**Output name:** Regime change probability  
**What it represents:** A heuristic estimate of the probability that the current regime will change within approximately 30 days. Combines three factors: how close the composite score is to the nearest regime boundary, whether the score is trending toward that boundary, and whether a divergence signal is active.

**Unit/format:** Float 0.05 to 0.85 (hard-capped), also returned as a percentage string (e.g., `"~34%"`)

**Typical range:** 5–30% is normal when the regime is stable. 50%+ means the score is near a threshold and/or moving toward it. The maximum is 85% — the system is designed to never say "certain."

**How to read it:** `~34%` means: given current score position, momentum, and divergence state, there's roughly a 1-in-3 chance the regime label changes in the next month. This is a rough heuristic, not a calibrated probability. Use it as a prompt to review your exposure, not as a precise forecast.

**Green flag:** Probability is low (5–15%) and the regime has been stable for many days. This is the "nothing to see here" reading.

**Red flag:** Probability above 50% combined with an active `LEADING_STRESS_WARNING` divergence. That combination means the score is close to a worse regime boundary and credit is already flagging deterioration.

**Depends on:** `attribution()` output (for threshold gap), the last 10 days of `regime_history` (for momentum), and the active divergence signal.

**Limitation to know:** This is not a backtested probability. The formula (`proximity_factor * 0.5 + momentum + divergence_boost`) was designed by hand and has not been validated against historical regime transitions. Treat the number as a useful heuristic for attention-allocation, not a reliable forecast.

---

### Output: `regime_state.json` (output contract)

**Output name:** `data/outputs/regime_state.json`  
**What it represents:** The locked file that Marcus writes and every downstream component reads. It is the integration point between the macro layer and everything else in the system.

**Unit/format:** JSON file with fields: `regime_state` (string), `composite_score` (float), `component_scores` (dict of 6 floats), `confidence` (string), `divergence_type` (string or null), `as_of` (date string), `missing_inputs` (list of strings), `written_at` (ISO timestamp)

**Typical range:** See individual field descriptions above.

**How to read it:** `written_at` is the most important field for downstream components — this is what the 12-hour staleness check compares against. `missing_inputs` tells you which FRED series didn't load; an empty list is the healthy state.

**Green flag:** `missing_inputs` is `[]`, `written_at` is within the last 12 hours, `confidence` is `MEDIUM` or `HIGH`.

**Red flag:** `missing_inputs` contains `vix` or `hy_spread` — the two highest-weight components. If both are missing, the composite score will drift toward 0 and the regime label may be meaningless. This should also appear in `warnings` when you run `classify()` directly.

**Depends on:** `macro_feed.py` having run successfully and written current data to `macro.db`. If the feed fails, `regime_state.json` goes stale and all downstream components fail loudly within 12 hours.

**Limitation to know:** `write_output_contract()` must be called explicitly — it is not called automatically inside `classify()`. Callers (scheduler, daily pipeline) are responsible for calling it. If the scheduler fails to call it, `regime_state.json` goes stale even though the DB is being updated correctly.

---

## Known Gaps and Validation Notes

| Gap | Severity | Notes |
|-----|----------|-------|
| `nfp_3m_avg` field never populated | Low | NFP data exists in DB; 3-month average not computed. Labor scoring uses unemployment + claims instead. |
| COT positioning uses only SP500 | Low | NASDAQ, EURUSD, GOLD, WTI, BONDS_10Y defined in config but not scored. |
| Divergence thresholds not calibrated | Medium | Set a priori. Calibration script referenced in config.py comments but does not exist. |
| `regime_change_probability` not backtested | Medium | Heuristic formula, no empirical validation. |
| `regime_return_stats` table may be empty | Low | Dashboard tab renders silently empty if `compute_regime_return_stats.py` has never been run. |
| Dashboard writes to DB on every page refresh | Low | `classify(persist=True)` on page load; `INSERT OR REPLACE` handles idempotency, but this is unexpected behavior for a display layer. |

**Data you'd need to validate the implementation:**
- At least 1 year of daily `regime_history` rows to validate that the score-to-regime mapping is producing labels consistent with historical market conditions (e.g., March 2020 should produce `CRISIS`)
- A historical backfill comparing `regime_state` labels against known risk-on / risk-off periods to calibrate divergence thresholds
- Live FRED data to confirm all 20+ series are populating without gaps
