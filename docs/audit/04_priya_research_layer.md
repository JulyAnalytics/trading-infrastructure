# Audit #4 — Priya / Research Layer
**Generated:** 2026-04-07
**Scope:** `systems/backtest/` (all 12 modules) + `scripts/verify_priya.py` + `scripts/verify_priya_integration.py`
**Audit sequence position:** 4 of 5

---

## DOCUMENT 1: CAPABILITY MAP

---

### Component: Data Audit
**File path:** `systems/backtest/data_audit.py`
**Module:** Priya / research
**What it does:** Validates a price or options dataset before it enters the pipeline. It checks for survivorship bias, look-ahead contamination, data gaps, missing values, and unrealistic option spreads. Every blocker must be cleared before the pipeline advances; warnings are logged but do not stop execution.
**Inputs:**
- A pandas DataFrame of price or options data
- Metadata: bar type (`time`, `dollar`, `volume`, `tick`), universe start date, `as_of` date, expected frequency, max acceptable gap in days
- Source: caller-supplied; typically pulled from DuckDB via `get_connection()`
**Outputs:**
- Dict with keys `flags` (list of warnings), `blockers` (list of hard stops), `cleared` (bool)
- Not stored to DB; returned to the caller for gate-checking
**Dependencies:**
- No upstream Priya components; operates on raw data
- If this blocks, nothing downstream runs (the pipeline enforces `data_audit_clearance` as Gate 2)
**Implementation status:** Appears complete
**Gap vs architecture:** Matches architecture. One known limitation documented in the code: survivorship bias check is heuristic (dataset start vs universe start) — it cannot detect point-in-time database errors.

---

### Component: Hypothesis Registry
**File path:** `systems/backtest/hypothesis_registry.py`
**Module:** Priya / research
**What it does:** Forces every research hypothesis to be written down and timestamped before any data is examined. This prevents "I found something interesting, let me backtest it" workflows, which inflate false positive rates. It also counts how many parameter configurations have been tried on a dataset — a number required for multiple-testing correction.
**Inputs:**
- Hypothesis text (string), dataset ID, signal type, rationale
- Increments via `increment_trial_count(dataset_id)` on every parameter configuration evaluated
- Source: caller-supplied at pipeline entry
**Outputs:**
- `hypothesis_id` (hash-based string) — primary key for the entire research run
- Trial count (integer) — consumed by `SharpeEstimationPipeline` for DSR computation
- Stored to `hypothesis_registry` table in `trading.db`
**Dependencies:**
- `get_connection()` from `systems/utils/db.py`
- Downstream: `SharpeEstimationPipeline` requires the trial count; `ResearchPipeline` requires a valid `hypothesis_id` before running
**Implementation status:** Appears complete
**Gap vs architecture:** Matches architecture. Trial counting is manual — callers must remember to call `increment_trial_count()` on every sweep iteration. The pipeline does not auto-increment; this is a documentation/discipline gap, not a code gap.

---

### Component: Fractional Differentiation
**File path:** `systems/backtest/feature_engineering.py` — class `FracDiff`
**Module:** Priya / research
**What it does:** Transforms a price series into a stationary feature while preserving as much historical memory as possible. Standard log returns (d=1) are stationary but discard all predictive memory from the price level. Raw prices (d=0) retain memory but fail stationarity tests. FracDiff finds the minimum fractional exponent d between 0 and 1 that just barely passes a stationarity test.
**Inputs:**
- A pandas price series (typically `close`)
- `d` value (float 0–1) or search range for `find_minimum_d()`
- Source: caller-supplied from price data
**Outputs:**
- Fractionally differentiated series (pandas Series) with NaN-leading observations dropped
- `find_minimum_d()` also returns the correlation with the original series (memory retention metric)
- Not stored to DB; returned for use as a model feature
**Dependencies:**
- `statsmodels` for ADF test
- Upstream: requires clean price data (post-DataAudit)
- Downstream: features feed into `TripleBarrierLabeler` and `VectorizedBacktester`
**Implementation status:** Appears complete
**Gap vs architecture:** Minor: the code notes (Gap 7.3) that vol surface features (IV, skew) are already stationary and may not need FracDiff. The caller is responsible for running ADF first on those features — the pipeline does not auto-skip. Not a code defect; a documentation requirement.

---

### Component: Volatility Estimator Suite
**File path:** `systems/backtest/vol_estimators.py` — class `VolEstimatorSuite`
**Module:** Priya / research
**What it does:** Provides five different methods to estimate how much an asset has been moving (realized volatility) from OHLC price bars. Each estimator uses a different mathematical approach with different efficiency and bias tradeoffs. The comparison output is used to select the best estimator for the VRP (volatility risk premium) signal.
**Inputs:**
- OHLC columns (open, high, low, close) as pandas Series
- `window` (lookback in bars), `annualize` (bool)
- Source: caller-supplied from price data
**Outputs:**
- Annualized realized volatility series (pandas Series) per estimator
- `compare_all()` returns a DataFrame with all five side-by-side
- Not stored to DB; returned as features
**Dependencies:**
- No external dependencies beyond pandas/numpy
- Upstream: clean OHLC data (post-DataAudit)
- Downstream: realized vol feeds into VRP calculation; `OptionsBacktester` uses it for delta-hedge vol selection (DD-08)
**Implementation status:** Appears complete
**Gap vs architecture:** Matches architecture.

---

### Component: Volatility Cone
**File path:** `systems/backtest/vol_estimators.py` — class `VolCone`
**Module:** Priya / research
**What it does:** Shows the historical distribution of realized volatility at multiple lookback lengths (e.g., 10-day, 21-day, 63-day). For each window, it computes percentile bands. The current realized vol is then placed within those bands to give context — "vol is at its 80th percentile for 21-day windows" — which informs whether options are cheap or expensive relative to history.
**Inputs:**
- Close price series
- List of window lengths and percentiles
- Source: caller-supplied
**Outputs:**
- DataFrame with columns: `window`, `p5`, `p25`, `p50`, `p75`, `p95`, `current`, `rank` (0–1)
- Not stored to DB; returned for display or feature construction
**Dependencies:**
- `VolEstimatorSuite` (uses Yang-Zhang internally)
- Upstream: clean close prices
**Implementation status:** Appears complete
**Gap vs architecture:** The Hodges-Tompkins overlap correction is implemented and documented. No gaps identified.

---

### Component: Triple-Barrier Labeler
**File path:** `systems/backtest/label_construction.py` — class `TripleBarrierLabeler`
**Module:** Priya / research
**What it does:** Assigns a label (+1, -1, or 0) to each trade entry point based on which of three exit conditions is hit first: a profit target (upper barrier), a stop-loss (lower barrier), or a time limit (vertical barrier). Barrier widths are scaled by the asset's recent volatility so that a "wide stop" in a quiet market is the same distance in vol units as a "wide stop" in a volatile one.
**Inputs:**
- Close price series
- Entry times series and horizon bars (lookforward window)
- Optional: pre-computed EWMA volatility, side (+1 long / -1 short for asymmetric barriers)
- Source: caller-supplied
**Outputs:**
- DataFrame indexed by entry time: `exit_time`, `label` {-1, 0, +1}, `ret` (price return), `barrier_hit` ('upper', 'lower', 'vertical')
- Not stored to DB; feeds directly into model training
**Dependencies:**
- No external dependencies
- Downstream: labels + sample weights feed into cross-validation and `VectorizedBacktester`
**Implementation status:** Appears complete. Mode A (underlying price barriers) and Mode B (options P&L barriers) both implemented.
**Gap vs architecture:** Mode B requires the caller to supply the options P&L path — `OptionsBacktester` must run first. The pipeline does not enforce this ordering; it is a documentation requirement.

---

### Component: Sample Weights
**File path:** `systems/backtest/label_construction.py` — class `SampleWeights`
**Module:** Priya / research
**What it does:** Assigns a weight to each labeled observation based on how much unique information it contributes. When positions overlap in time (e.g., two 10-day trades opened 3 days apart share 7 days of data), the overlapping observations are not independent — a standard ML model would overcount them. Lower uniqueness → lower weight.
**Inputs:**
- `t1` series (exit times indexed by entry times)
- Close price index (for concurrency counting)
- Source: output of `TripleBarrierLabeler`
**Outputs:**
- pandas Series of weights (float, sum ≈ n observations)
- Passed to sklearn `sample_weight` parameter during model training
**Dependencies:**
- Upstream: `TripleBarrierLabeler` output
- Downstream: sklearn classifiers/regressors that accept `sample_weight`
**Implementation status:** Appears complete
**Gap vs architecture:** Matches architecture.

---

### Component: Vectorized Backtest Engine
**File path:** `systems/backtest/vectorized_engine.py` — class `VectorizedBacktester`
**Module:** Priya / research
**What it does:** Runs fast backtests for equity/index signal research. Takes a position signal (+1, -1, 0) and a returns series, applies a one-bar execution lag, deducts transaction costs, and computes performance statistics. Can sweep a grid of parameter combinations and flag when results look suspiciously dependent on the exact parameter values chosen.
**Inputs:**
- `signal`: pandas Series of position weights
- `returns`: pandas Series of asset returns
- `cost_bps`: one-way transaction cost in basis points (default 10 bps)
- `oos_fraction`: fraction of data treated as out-of-sample (default 30%)
- Source: caller-supplied; signal is constructed by the researcher
**Outputs:**
- `run_single()`: dict with ~20 metrics — Sharpe (IS, OOS, annual), drawdown, hit rate, turnover, cost drag, degradation ratio, production haircut, plus full strategy returns and equity curve Series
- `parameter_sweep()`: DataFrame of results sorted by OOS Sharpe
- `regime_conditional_analysis()`: DataFrame of Sharpe stats per regime
- Not stored to DB; results passed to `ResearchPipeline`
**Dependencies:**
- `config.py` for constants (haircut, min viable Sharpe, overfitting thresholds)
- Downstream: results feed into `SharpeEstimationPipeline`, `CPCV`, `ResearchTracker`
**Implementation status:** Appears complete
**Gap vs architecture:** Matches architecture. One important constraint: `parameter_sweep()` requires ≥ `BACKTEST_SWEEP_MIN_POINTS` (from config) results to trigger overfitting warnings — behavior is undefined for very small grids.

---

### Component: Options Backtest Engine with Monte Carlo
**File path:** `systems/backtest/options_engine.py` — class `OptionsBacktester`
**Module:** Priya / research
**What it does:** Backtests options strategies by running 1,000+ simulated price paths and computing the P&L of a delta-hedged position on each path. This answers the question: "given this IV vs realized vol spread, what is the distribution of outcomes if I run this trade 1,000 times?" It also handles three levels of transaction costs: option entry/exit, delta hedge trades, and cumulative hedge drag.
**Inputs:**
- Option parameters: spot, strike, DTE, implied vol, forecast realized vol, option type, position type
- Market execution parameters: slippage bps, min volume, max spread pct
- Source: caller-supplied; typically from `vol_signals.json` or live options chain
**Outputs:**
- `monte_carlo_pnl_distribution()`: dict with mean/median/std/p5/p95 P&L, probability of loss, Kamal-Derman sigma, hedge mode used
- `fill_price()`: execution price with slippage
- `compute_hedge_cost_leland()`: Leland-adjusted vol and breakeven spread
- `log_trade()`: appends to internal `trade_log` for `ImplementationShortfall` consumption
- Not stored to DB directly; `trade_log` passed to `ImplementationShortfall`
**Dependencies:**
- `systems/utils/pricing.py` for analytic BSM fallback
- QuantLib (optional; uses GBM + analytic BS if unavailable)
- Upstream: `vol_signals.json` or options chain data; `regime_state.json` for regime check
- Downstream: `trade_log` → `ImplementationShortfall`; MC output → `ResearchTracker`
**Implementation status:** Appears complete. QuantLib integration implemented with documented GBM fallback (DD-09).
**Gap vs architecture:** Simulation dynamics use GBM (log-normal) unless QuantLib Heston is available. Real options P&L distributions have fatter tails than GBM predicts — this is documented (DD-09) but is a known limitation, not a gap.

---

### Component: Purged K-Fold Cross-Validation
**File path:** `systems/backtest/purged_cv.py` — class `PurgedKFold`
**Module:** Priya / research
**What it does:** A modified version of the standard machine learning train/test split that prevents data leakage for time series with overlapping labels. Standard K-Fold would include observations in training whose "label windows" (the future period used to define +1/-1) overlap with the test period — effectively the model sees the future. PurgedKFold removes (purges) those observations and adds a buffer (embargo) after each test fold.
**Inputs:**
- Feature matrix X, `t1` series (label exit times), `pct_embargo` (buffer fraction)
- Source: output of `TripleBarrierLabeler`
**Outputs:**
- Generator of (train_indices, test_indices) tuples — drop-in replacement for sklearn KFold
**Dependencies:**
- sklearn `_BaseKFold`
- Downstream: feeds into sklearn model fitting; also used internally by `CPCV`
**Implementation status:** Appears complete
**Gap vs architecture:** Matches architecture. Documented constraint: for options strategies with holding periods > T/n_splits, callers must increase `pct_embargo` to match the holding period.

---

### Component: Combinatorial Purged Cross-Validation (CPCV)
**File path:** `systems/backtest/cpcv.py` — class `CPCV`
**Module:** Priya / research
**What it does:** The primary validation method for all research. Instead of a single walk-forward train/test split (which gives one Sharpe estimate that could be lucky or unlucky), CPCV generates all possible ways to split the data into N groups and rotates k groups as test. This produces a distribution of Sharpe ratios across multiple paths, which is a far more reliable estimate of true performance. It also computes PBO — the probability that IS-optimal parameter selection underperforms OOS.
**Inputs:**
- Returns series (T observations)
- Optional `signal_func(train_returns) → signal` for signal-based strategies
- `n_groups` (default 6), `k_test` (default 2), `pct_embargo`
**Outputs:**
- Dict with: `n_paths`, `mean_sharpe`, `median_sharpe`, `std_sharpe`, `p5_sharpe`, `p95_sharpe`, `pct_positive`, `pbo`, `is_oos_correlation`, `path_sharpes` (array), `walk_forward_note`
- Not stored to DB; passed to `ResearchTracker` and `OverfitDiagnostics`
**Dependencies:**
- `PurgedKFold` (uses it internally for each split)
- Downstream: `OverfitDiagnostics`, `SharpeEstimationPipeline`, `ResearchTracker`
**Implementation status:** Appears complete
**Gap vs architecture:** Matches architecture. Note: `n_paths` = φ[N,k] = (k/N)·C(N, N-k). For default N=6, k=2 this is 5 paths — modest but sufficient per architecture spec.

---

### Component: Overfitting Diagnostics
**File path:** `systems/backtest/overfit_statistics.py` — class `OverfitDiagnostics`
**Module:** Priya / research
**What it does:** Aggregates four independent statistical tests that together diagnose whether a backtest result is likely due to genuine edge or parameter tuning luck: (1) PBO from CPCV, (2) regression of OOS Sharpe on IS Sharpe (β < 0 = overfit), (3) probability that OOS returns are negative, and (4) whether IS-optimal selection beats random selection OOS (stochastic dominance via KS test). Tallies signals; returns a verdict.
**Inputs:**
- IS Sharpe array, OOS Sharpe array (from CPCV paths)
- PBO (from CPCV output — not recomputed)
- Optional: OOS-random array for stochastic dominance (defaults to permutation of OOS)
**Outputs:**
- Dict with all four diagnostic results + `overfit_signal_count` (0–4) + `verdict` (NO_OVERFIT_SIGNAL → HIGH_OVERFIT_RISK)
- Passed to `ResearchTracker`
**Dependencies:**
- `scipy.stats` for OLS and KS test
- Upstream: CPCV output
**Implementation status:** Appears complete
**Gap vs architecture:** Matches architecture. PBO is correctly accepted as a completed input rather than recomputed — consistent with DD-11.

---

### Component: Sharpe Estimation Pipeline
**File path:** `systems/backtest/sharpe_pipeline.py` — class `SharpeEstimationPipeline`
**Module:** Priya / research
**What it does:** Takes a return series and computes a fully corrected Sharpe ratio with all required statistical machinery: (1) tests for serial correlation in returns (autocorrelation can inflate the naive Sharpe by ~65%), (2) computes standard error and 95% confidence interval using the appropriate method, (3) applies non-normality correction via PSR, (4) applies multiple-testing correction via DSR, (5) computes minimum track record length, and (6) applies a 50% production haircut.
**Inputs:**
- Returns series (pandas Series)
- `n_trials` (from hypothesis registry — how many parameter configurations were tested)
- `annualization_factor` (default 252)
- Optional `n_eff` (effective number of independent strategies)
**Outputs:**
- Dict with: `sr_raw`, `sr_annual`, `annualization_method`, `se`, `se_method`, `ci_95`, `has_autocorrelation`, `ljung_box_pvalue`, `skewness`, `kurtosis`, `psr`, `dsr_literal`, `dsr_neff`, `dsr_primary`, `n_trials`, `n_eff`, `min_track_record_years`, `production_haircut_sr`, `viable_after_haircut`
- Passed to `ResearchTracker` and `ResearchPipeline` gates
**Dependencies:**
- `statsmodels` for Ljung-Box and Newey-West
- `scipy.stats` for normal CDF
- Upstream: CPCV output (returns series)
- Downstream: Gates 8–11 in `ResearchPipeline`
**Implementation status:** Appears complete — full Lo (2002) + PSR + DSR pipeline with both literal-N and N_eff DSR variants (DD-12).
**Gap vs architecture:** Matches architecture. One nuance: PSR uses the non-annualized period Sharpe (DD-02 enforced). If the caller passes annualized returns, the PSR will be incorrect — caller discipline required.

---

### Component: Strategy Risk
**File path:** `systems/backtest/strategy_risk.py` — class `StrategyRisk`
**Module:** Priya / research
**What it does:** Answers the question: "given this strategy's win rate and win/loss sizes, how likely is it that the true edge is zero or negative?" Uses a binomial model — each trade is a bet with observed precision p. Computes the breakeven precision (minimum hit rate for expected P&L ≥ 0) and the probability that the true precision is below breakeven given the observed sample.
**Inputs:**
- `p`: observed precision (hit rate, 0–1)
- `n`: number of trades
- `pi_neg`: average loss per losing trade (negative float)
- `pi_pos`: average gain per winning trade (positive float)
- Source: extracted from `VectorizedBacktester` or `OptionsBacktester` trade log
**Outputs:**
- `full_report()`: dict with `breakeven_precision`, `prob_failure`, `precision_ci`, `verdict` (ROBUST_EDGE → INSUFFICIENT_EDGE)
- Passed to `ResearchTracker`
**Dependencies:**
- `scipy.stats` for binomial CDF and Wilson interval
- Upstream: completed backtest with win/loss statistics
**Implementation status:** Appears complete — both symmetric (equity) and asymmetric (options) formulas implemented.
**Gap vs architecture:** Matches architecture.

---

### Component: Implementation Shortfall
**File path:** `systems/backtest/impl_shortfall.py` — class `ImplementationShortfall`
**Module:** Priya / research
**What it does:** Measures whether a strategy's gross P&L survives its execution costs. Takes a completed trade log and computes four metrics: broker fees per unit of turnover, slippage per unit of turnover, P&L per unit of turnover, and the ratio of P&L to total execution costs. A ratio below 1.0 means costs exceed profits — the strategy fails at the execution layer regardless of its signal quality.
**Inputs:**
- `trade_log`: list of dicts, each with keys `turnover`, `broker_fee`, `slippage_cost`, `net_pnl`; optional `hedge_cost` for options (Level 3 DD-10)
- Source: `OptionsBacktester.log_trade()` or manually constructed for equity strategies
**Outputs:**
- `compute()`: dict with totals, per-trade averages, per-unit metrics, `return_on_execution_costs`, `interpretation` (plain English)
- `gate_check()`: dict with `passes` (bool), threshold (2.0× default), message
- Passed to `ResearchPipeline` Gate 12 and `ResearchTracker`
**Dependencies:**
- No external dependencies
- Upstream: completed `trade_log`
- Downstream: `ResearchPipeline` Gate 12
**Implementation status:** Appears complete
**Gap vs architecture:** For equity strategies, trade log construction is manual — there is no automated path from `VectorizedBacktester` results to a `trade_log` dict. The equity trade log must be constructed by the researcher from the strategy returns and an assumed cost model. This is a workflow gap (not a code gap), but it creates room for inconsistency.

---

### Component: Experiment Tracker
**File path:** `systems/backtest/experiment_tracker.py` — class `ResearchTracker`
**Module:** Priya / research
**What it does:** Logs every research run — including failed NO_GO runs — to MLflow with a JSON fallback. Stores all 12 non-negotiable outputs as structured artefacts so that future researchers can query what has been tried, what failed, and why. Every run receives a unique ID and is tagged with the engine version.
**Inputs:**
- All 12 non-negotiable outputs (structured dicts from upstream pipeline steps)
- `verdict` ('GO' / 'NO_GO'), `verdict_rationale` (plain text)
- `hypothesis_id`, `run_name`, `params`, `metrics`
- Source: `ResearchPipeline._run()` assembles and passes all inputs
**Outputs:**
- `run_id` (string)
- MLflow experiment entry (or JSON fallback in `mlruns_fallback/`)
- NO_GO runs tagged `is_failure_archive_entry: true`
**Dependencies:**
- `mlflow` (optional; JSON fallback if unavailable)
- Upstream: all pipeline steps must complete before logging
**Implementation status:** Appears complete — MLflow + JSON fallback both implemented.
**Gap vs architecture:** Matches architecture. One operational note: the MLflow fallback writes to `OUTPUTS_DIR/../mlruns_fallback/` — verify this path resolves correctly relative to `OUTPUTS_DIR` in production; the relative path construction could be brittle if `OUTPUTS_DIR` is an unusual path.

---

### Component: Research Pipeline (Orchestrator)
**File path:** `systems/backtest/research_pipeline.py` — class `ResearchPipeline`
**Module:** Priya / research
**What it does:** Wires all eight layers into a single callable. Accepts a registered hypothesis ID and a returns series, runs Stages 5–8 (Stages 0–4 are the caller's responsibility), enforces all 13 process gates, and writes the `research_verdict.json` output contract for Jordan. Supports both equity (10 non-negotiable outputs) and options (12 outputs).
**Inputs:**
- `hypothesis_id` (must exist in registry)
- `returns` series, `trade_log` (list of dicts), `params` (dict)
- Optional: `regime_series`, `additional_metrics`, `verdict_override`, `verdict_rationale_override`
- Options additionally: `mc_pnl` dict from `OptionsBacktester`
- Source: caller-assembled from upstream pipeline steps
**Outputs:**
- Dict with `run_id`, `verdict` (GO/NO_GO), `verdict_rationale`, `suggested_verdict`, `gates_passed`, `gates_failed`, + all non-negotiable output keys
- Side effect: writes `data/outputs/research_verdict.json`
**Dependencies:**
- All 11 other backtest modules
- `config.py` for all thresholds
- `systems/utils/db.py` for hypothesis registry DB access
- `regime_state.json` freshness check (Rule 4 in CLAUDE.md)
**Implementation status:** Appears complete — all 8 stages wired, all 13 gates enforced, Jordan contract written.
**Gap vs architecture:** Matches architecture. One operational constraint: `allow_continue=True` bypasses the pre-registration gate (intended for testing). This flag must be `False` in any production or real research run.

---

## DOCUMENT 2: OUTPUT LITERACY

---

### Output: Regime-Conditional Sharpe Table
**Output name:** `regime_conditional_sharpe`
**What it represents:** Whether the strategy's edge is consistent across all market conditions, or whether it only works in one type of regime (making it a regime bet, not a genuine signal)
**Unit/format:** Dict keyed by regime label (e.g., `RISK_ON_LOW_VOL`), each with Sharpe, n_obs, hit rate, win/loss, pct_of_total, sufficient_obs flag
**Typical range:** Sharpe values from −1.5 to +2.5 per regime; n_obs varies by how often each regime occurs
**How to read it:** If RISK_ON_LOW_VOL shows Sharpe 1.2 and RISK_OFF shows Sharpe −0.8, the strategy makes money only when markets are calm and loses when stressed. That is a regime bet. A strategy with Sharpe 0.6 across all regimes is more trustworthy.
**Green flag:** Positive Sharpe in all regimes that have `sufficient_obs = True`; no single regime driving > 60% of total returns
**Red flag:** Any regime with negative Sharpe and `sufficient_obs = True`; one regime with n_obs < 30 marked `sufficient_obs = False` means you cannot draw conclusions about that regime — this is an explicit data gap, not a signal
**Depends on:** Quality of the regime classification from Marcus; sufficient historical data across all regime types
**Limitation to know:** If your backtest history contains only one or two regime cycles, the conditional Sharpes are unreliable — you may have 500 total bars but only 40 in RISK_OFF. The `sufficient_obs` flag exists to surface this but does not fix it.

---

### Output: Parameter Sensitivity Surface
**Output name:** `parameter_sensitivity_surface` (from `parameter_sweep()`)
**What it represents:** Whether the strategy's results depend critically on the exact parameters chosen, or whether performance is stable across a range of nearby values
**Unit/format:** DataFrame sorted by OOS Sharpe; one row per parameter combination; includes Sharpe CV (coefficient of variation) warning
**Typical range:** Sharpe CV below 0.3 = stable; above 0.5 = suspicious; above 1.0 = results are noise
**How to read it:** If a 20-day lookback gives Sharpe 1.4 but a 19-day lookback gives 0.3 and a 21-day gives 0.1, the result is entirely dependent on that exact parameter — almost certainly a backtest artefact. If 15-day through 25-day all give Sharpe 0.6–0.9, that is robust.
**Green flag:** Top result is not dramatically better than the median result; Sharpe CV < 0.3; the best parameters are "in the middle" of the grid, not at an edge
**Red flag:** Sharpe CV > 0.5 triggers an overfitting warning in the code; results that peak sharply at one parameter value and fall off rapidly; best parameters at the extreme edge of the grid (suggests the true optimum is outside the tested range)
**Depends on:** Grid resolution (coarse grids can hide unstable regions), OOS fraction size
**Limitation to know:** A stable surface on IS data can still overfit if the OOS fraction is too short. This output tells you about parameter sensitivity, not about whether the signal is genuine.

---

### Output: Degradation Ratio
**Output name:** `degradation_ratio`
**What it represents:** How much the strategy's Sharpe declines from in-sample to out-of-sample, expressed as a ratio (IS Sharpe / OOS Sharpe)
**Unit/format:** Float ≥ 0; ratio
**Typical range:** 1.0–2.5 is expected (some degradation is normal); above 3.0 is a concern; above 5.0 is a strong overfit signal
**How to read it:** A ratio of 1.5 means OOS Sharpe is about 67% of IS Sharpe — normal. A ratio of 4.0 means OOS Sharpe is 25% of IS Sharpe — the IS result was largely a backtest artefact.
**Green flag:** Ratio between 1.0 and 2.5; the production haircut (50%) still leaves a viable strategy
**Red flag:** Ratio > 3.0; or OOS Sharpe is negative while IS is positive (ratio is not meaningful but the situation is clearly bad)
**Depends on:** Length and representativeness of the OOS period; whether the OOS period contains different market conditions than IS
**Limitation to know:** A degradation ratio of 1.0 does not mean the strategy has no overfit — it could mean IS and OOS happened to have the same market conditions. CPCV is more reliable than the single IS/OOS split.

---

### Output: Production Haircut Sharpe
**Output name:** `production_haircut_sr`
**What it represents:** A conservative estimate of what the strategy's Sharpe will be in live trading, after accounting for the inevitable gap between a cleaned backtest and messy real-world execution
**Unit/format:** Float; annualized Sharpe ratio (the same unit as regular Sharpe)
**Typical range:** 0.3–1.5 for viable strategies; below 0.5 is the cutoff
**How to read it:** If the OOS Sharpe is 1.2, the haircut Sharpe is 0.6 (50% applied). The threshold is 0.5 — so a strategy needs at least an OOS Sharpe of 1.0 to be considered viable for production. A haircut Sharpe of 0.4 means: even in the best-case backtest scenario, the strategy barely earns its risk.
**Green flag:** `viable_after_haircut = True`; haircut Sharpe ≥ 0.7 (buffer above the 0.5 threshold)
**Red flag:** `viable_after_haircut = False`; haircut Sharpe between 0.5 and 0.6 (technically viable but no margin for error)
**Depends on:** OOS Sharpe accuracy; the 50% haircut is a fixed assumption — the actual degradation from backtest to live may be more or less
**Limitation to know:** The 50% haircut is not derived from empirical data for this specific strategy. It is a conservative rule of thumb. A strategy with unusual characteristics (very high turnover, specific liquidity requirements) may experience more or less degradation than 50%.

---

### Output: Sharpe SE and 95% CI
**Output name:** `se`, `ci_95`, `se_method`
**What it represents:** How precise the Sharpe estimate is. A Sharpe of 0.8 with a CI of [0.2, 1.4] is much less meaningful than a Sharpe of 0.8 with a CI of [0.6, 1.0].
**Unit/format:** Float (SE); tuple of two floats (CI); string label for method ('IID' or 'Newey-West HAC')
**Typical range:** SE of 0.1–0.4 for 2–5 years of daily data; wider CIs for shorter histories or autocorrelated returns
**How to read it:** If SE = 0.25 and SR = 0.8, the CI is roughly [0.3, 1.3]. This means "the true Sharpe could plausibly be anywhere from modest to good." If SE = 0.05 and SR = 0.8, CI is [0.7, 0.9] — much higher confidence.
**Green flag:** CI lower bound comfortably above zero; `se_method = 'IID'` (clean returns, no autocorrelation correction needed)
**Red flag:** CI lower bound below zero (cannot rule out that the true Sharpe is negative); `se_method = 'Newey-West HAC'` and the Newey-West lags show high sensitivity (SE varies a lot between the two reported lag choices)
**Depends on:** Length of the return series (longer = tighter CI); whether returns are serially correlated (options strategies often are — delta-hedged returns autocorrelate)
**Limitation to know:** Standard error assumes the return distribution is stationary. If the strategy's behavior changes over time (regime shifts, market microstructure changes), the SE understates true uncertainty.

---

### Output: Serial Correlation Diagnostic
**Output name:** `has_autocorrelation`, `ljung_box_pvalue`, `annualization_method`
**What it represents:** Whether the strategy's daily returns are independent (each day is a fresh draw) or whether today's return predicts tomorrow's (common in options theta strategies where gains accumulate smoothly). This matters because naive Sharpe annualization (multiplying by √252) assumes independence — serial correlation makes the naive Sharpe ~65% too high for theta-harvesting strategies.
**Unit/format:** `has_autocorrelation`: bool; `ljung_box_pvalue`: float 0–1; `annualization_method`: 'eta_q' (corrected) or 'sqrt_q' (naive)
**Typical range:** p-value > 0.05 = no evidence of autocorrelation (IID assumption holds); p-value < 0.05 = autocorrelation detected, use η(q) correction
**How to read it:** `ljung_box_pvalue = 0.02, annualization_method = 'eta_q'` means autocorrelation was detected and the corrected annualization was applied — the Sharpe you see is already adjusted downward. `ljung_box_pvalue = 0.43, annualization_method = 'sqrt_q'` means returns look independent and the standard annualization was used.
**Green flag:** If equity momentum strategy: `has_autocorrelation = False` is expected and good. If options theta strategy: `has_autocorrelation = True` is expected — the correction being applied is correct behavior, not a problem.
**Red flag:** Options strategy showing `has_autocorrelation = False` — unusual, worth investigating whether the returns are being computed correctly. Equity strategy showing very high autocorrelation — may indicate a look-ahead or smoothing error in return construction.
**Depends on:** How returns are constructed (daily mark-to-market vs trade-close P&L); strategy type (theta harvest vs momentum)
**Limitation to know:** The η(q) correction corrects for autocorrelation in Sharpe estimation but does not correct for it in PSR/DSR calculations (PSR uses non-annualized SR). These are two separate corrections applied sequentially.

---

### Output: DSR (Deflated Sharpe Ratio)
**Output name:** `dsr_primary`, `dsr_literal`, `dsr_neff`
**What it represents:** The probability that the strategy's Sharpe is genuine — above a benchmark that accounts for how many configurations were tested. If you ran 50 parameter combinations and picked the best one, a naive Sharpe of 1.2 is much less impressive than if you ran only 1 combination. DSR penalizes for the number of trials. DSR > 0.95 means: even accounting for how many things you tried, this result is unlikely to be luck.
**Unit/format:** Float 0–1; probability
**Typical range:** 0.90–0.99 for strong results with few trials; can drop below 0.50 if many trials were run with a modest Sharpe result
**How to read it:** `dsr_primary = 0.97` means: after multiple-testing correction, there is a 97% probability this Sharpe is genuine. `dsr_primary = 0.72` means: after correction, only 72% confidence — below the 0.95 gate, this would not advance.
**Green flag:** `dsr_primary > 0.95` (gate threshold); `dsr_primary_source` labels which N was more conservative (literal-N or N_eff) — whichever is reported as primary is the binding constraint
**Red flag:** `dsr_primary < 0.95`; large gap between `dsr_literal` and `dsr_neff` (signals high correlation among the tested parameter configurations — fewer independent trials than the literal count)
**Depends on:** `n_trials` from the hypothesis registry (must be accurate — every parameter combination must be counted); `n_eff` eigenvalue computation requires a Sharpe matrix (only available when multiple strategies are being compared)
**Limitation to know:** DSR assumes the trials were independent. If all tested parameters are variants of the same underlying idea (e.g., 20 slightly different momentum lookbacks), the effective number of independent tests is much lower than the literal count. This is what `n_eff` partially corrects for.

---

### Output: CPCV Path Distribution
**Output name:** `cpcv_results` — specifically `mean_sharpe`, `median_sharpe`, `std_sharpe`, `p5_sharpe`, `p95_sharpe`, `pct_positive`, `path_sharpes`
**What it represents:** A distribution of how the strategy performs across multiple independent walk-forward paths. Instead of "the Sharpe is 0.8", you get "across 5 independent paths, Sharpe ranged from 0.2 to 1.4, median 0.7, 80% of paths were positive." This is a far more honest picture of expected live performance.
**Unit/format:** Floats (Sharpe values); `path_sharpes` is a numpy array; `pct_positive` is a float 0–1
**Typical range:** `std_sharpe` of 0.3–0.8 is normal; wider distribution = higher uncertainty; `pct_positive` ideally > 0.80
**How to read it:** `median_sharpe = 0.6, p5_sharpe = -0.3, p95_sharpe = 1.5, pct_positive = 0.80` means: the strategy works 80% of the time, but there are plausible paths where it loses. `median_sharpe = 0.6, p5_sharpe = 0.3, p95_sharpe = 0.9, pct_positive = 1.0` means: consistent across all paths — stronger evidence.
**Green flag:** `pct_positive > 0.80`; `p5_sharpe > 0` (even the unlucky path is positive); narrow distribution relative to the median
**Red flag:** `pct_positive < 0.60`; `p5_sharpe` significantly negative; high `std_sharpe` relative to `mean_sharpe` (coefficient of variation > 1.5)
**Depends on:** Length of the returns series (CPCV needs enough observations to form N=6 non-trivial groups); strategy turnover (short holding periods leave more valid observations per path)
**Limitation to know:** Default config uses N=6, k=2, giving only 5 paths. This is a small distribution. The architecture spec accepts it as sufficient, but 5 paths cannot reliably estimate tail behavior. `p5_sharpe` from 5 observations is the minimum of the 5 paths, not a true 5th percentile.

---

### Output: PBO and Overfitting Statistics
**Output name:** `pbo`, `overfit_signal_count`, `overfit_verdict`
**What it represents:** Four independent checks for whether the strategy's IS result is real or a fitting artefact:
- PBO: probability that IS-optimal parameter selection underperforms OOS median (pure overfit diagnostic)
- Degradation β: regression slope of OOS on IS Sharpe (negative β = overfit signal)
- P[OOS loss]: fraction of paths with negative OOS Sharpe
- Stochastic dominance: whether IS-optimal selection beats random selection OOS
**Unit/format:** `pbo` float 0–1; `overfit_signal_count` integer 0–4; `overfit_verdict` categorical string
**Typical range:** PBO of 0.01–0.15 for well-behaved strategies; verdict of NO_OVERFIT_SIGNAL or LOW_OVERFIT_SIGNAL to advance
**How to read it:** `pbo = 0.08, overfit_signal_count = 1, verdict = 'LOW_OVERFIT_SIGNAL'` = one of four checks flagged concern, but the overall picture is acceptable. `pbo = 0.40, overfit_signal_count = 3, verdict = 'HIGH_OVERFIT_RISK'` = three of four checks flagged, strong evidence of overfitting.
**Green flag:** `pbo < 0.05`; `overfit_signal_count ≤ 1`; `verdict` in {NO_OVERFIT_SIGNAL, LOW_OVERFIT_SIGNAL}
**Red flag:** `pbo > 0.20`; `overfit_signal_count ≥ 3`; `stochastic_dominance.dominates = False` (IS-optimal selection has no detectable benefit over random)
**Depends on:** Number of CPCV paths (only 5 with default settings — all four diagnostics are more reliable with more paths); whether the parameter sweep grid was dense enough to see variation
**Limitation to know:** PBO is a diagnostic, not a target. The architecture explicitly prohibits using PBO as an optimization objective. Optimizing to minimize PBO will paradoxically produce strategies that look less overfitted while still being meaningless.

---

### Output: MC P&L Distribution (Options Only)
**Output name:** `mc_pnl` — specifically `mean_pnl`, `p5`, `p95`, `prob_loss`, `kamal_derman_sigma`
**What it represents:** The distribution of outcomes from running a delta-hedged options position 1,000 times under simulated market conditions. Answers: "if I put on this trade 1,000 times, what range of P&L outcomes should I expect?" The Kamal-Derman sigma is the theoretical standard deviation of the hedged P&L derived analytically from the position's vega.
**Unit/format:** Dollar P&L values (mean, p5, p95); `prob_loss` is float 0–1; `kamal_derman_sigma` is float in dollar P&L units
**Typical range:** `prob_loss` of 0.30–0.55 for short premium strategies (positive expected value but frequent small losses); `mean_pnl` positive if IV > realized vol
**How to read it:** `mean_pnl = 120, p5 = -800, p95 = 950, prob_loss = 0.38` means: average win is $120, but in the worst 5% of paths you lose $800, and you lose on 38% of individual paths. Short premium is inherently a high-frequency-win / occasional-large-loss profile.
**Green flag:** `mean_pnl > 0` (positive expected value); `prob_loss` consistent with the strategy type (short premium: 30–55% loss rate is expected); `kamal_derman_sigma` close to the simulated `std_pnl` (validates the simulation)
**Red flag:** `mean_pnl < 0` (strategy has negative expected value net of costs — do not proceed); `kamal_derman_sigma` very different from simulated `std_pnl` (simulation may have a calibration issue); `prob_loss > 0.60` for a short premium strategy (suggests the IV/RV spread is insufficient to overcome hedging costs)
**Depends on:** Accuracy of the IV input, accuracy of the forecast realized vol, hedging frequency, whether QuantLib Heston is available (GBM fallback understates fat-tail events)
**Limitation to know:** The simulation uses GBM (log-normal price dynamics) unless QuantLib Heston is configured. Real options markets have fatter tails — the `p5` loss estimate from GBM simulation is likely too optimistic. Treat it as a lower bound on tail risk.

---

### Output: Three-Level Cost Decomposition (Options Only)
**Output name:** `total_fees`, `total_slippage`, `total_hedge_cost`, `return_on_execution_costs`
**What it represents:** Where the transaction costs are coming from across three sources: (1) bid/ask spread and slippage entering/exiting the option position, (2) transaction costs on each delta hedge trade, (3) the cumulative drag from imperfect hedging over the life of the position. `return_on_execution_costs` is the ratio of gross P&L to total execution costs.
**Unit/format:** Dollar amounts (totals and averages); `return_on_execution_costs` is a float ratio
**Typical range:** `return_on_execution_costs` ≥ 2.0 to pass the production gate; 5.0+ is strong; below 1.0 means costs exceed P&L
**How to read it:** `return_on_execution_costs = 3.2` means: for every $1 spent on execution, the strategy earned $3.20 gross. That is adequate margin. `return_on_execution_costs = 0.8` means: costs exceed profits — this strategy cannot survive real-world execution regardless of signal quality.
**Green flag:** `return_on_execution_costs ≥ 2.0` (passes gate); Level 2 (hedge costs) not dominant relative to Level 1 (entry/exit)
**Red flag:** `return_on_execution_costs < 1.0` (hard fail); Level 3 (cumulative hedge drag) unexpectedly large relative to gross P&L — indicates the hedging frequency is too low for the gamma exposure size
**Depends on:** Assumed slippage and commission rates; hedging frequency; option DTE and gamma profile
**Limitation to know:** The cost model uses fixed slippage assumptions. Real slippage varies with liquidity conditions — in stressed markets, bid/ask spreads widen significantly. This cost model does not capture regime-conditional execution costs.

---

### Output: Strategy Risk — P[p < p*]
**Output name:** `prob_failure`, `breakeven_precision`, `verdict` (ROBUST_EDGE → INSUFFICIENT_EDGE)
**What it represents:** Given how many trades were observed and what the win/loss profile looks like, what is the probability that the strategy's true hit rate is below the breakeven level? High `prob_failure` means the observed results could easily be explained by random variation — the edge is too fragile to trust.
**Unit/format:** `prob_failure` float 0–1; `breakeven_precision` float 0–1; `verdict` categorical
**Typical range:** `prob_failure < 0.05` for adequate edge; 0.05–0.10 for fragile but potentially acceptable; above 0.10 is insufficient
**How to read it:** `breakeven_precision = 0.52, observed_precision = 0.56, prob_failure = 0.03, verdict = 'ADEQUATE_EDGE'` means: you need to win 52% of trades to break even, you observed 56%, and given the sample size, there's only a 3% chance the true rate is below 52%. `prob_failure = 0.18` means: 18% chance the edge is zero — too unreliable for production.
**Green flag:** `prob_failure < 0.01` (ROBUST_EDGE); `observed_precision` comfortably above `breakeven_precision` with tight confidence interval
**Red flag:** `prob_failure > 0.10` (INSUFFICIENT_EDGE); small `n` (few trades) with `observed_precision` only slightly above breakeven — even a modest amount of luck could explain the results
**Depends on:** Number of trades `n` (the primary driver — more trades = tighter binomial CI); accuracy of win/loss accounting
**Limitation to know:** This model treats each trade as an independent binary event. Options strategies with path-dependent P&L profiles (spreads, multi-leg structures) are not purely binary — the binomial model is an approximation.

---

### Output: research_verdict.json (Jordan Contract)
**Output name:** `data/outputs/research_verdict.json`
**What it represents:** The summary verdict and key statistics that Jordan (the risk layer, Phase 4) will use to set position sizing, risk limits, and production parameters for a strategy that has passed the research gates
**Unit/format:** JSON file with keys: `verdict` (GO/NO_GO), `production_haircut_sharpe`, `viable_after_haircut`, `pbo`, `dsr`, `regime_conditional_sharpe`, `cpcv_path_count`, `n_trials`, `n_eff`, `min_track_record_years`, `leland_breakeven_spread` (options), `written_at`
**Typical range:** Verdict = GO with `production_haircut_sharpe` ≥ 0.5, `pbo` < 0.05, `dsr` > 0.95
**How to read it:** This file is the handoff document. If `verdict = GO` with these statistics, Jordan knows: (a) the signal has been validated to a specific confidence level, (b) what Sharpe to expect in production, (c) what regime conditions the strategy performs in. If `verdict = NO_GO`, Jordan should not act on this strategy regardless of what the raw Sharpe numbers show.
**Green flag:** All five process gates passed; `viable_after_haircut = True`; `regime_conditional_sharpe` shows positive performance in the current regime
**Red flag:** `verdict = GO` with any gate marked failed (should not happen — `verdict_override` was used; requires explicit rationale in the log); `written_at` is stale relative to when Jordan reads it
**Depends on:** The entire Priya pipeline completing successfully; regime_state.json freshness
**Limitation to know:** This file captures research-time statistics based on historical data. It does not update as market conditions change. A strategy with `regime_conditional_sharpe = {RISK_ON: 1.2, RISK_OFF: -0.4}` that was approved during a RISK_ON period will show a stale and misleading verdict if the regime shifts after approval. Jordan must check the current regime before acting.

---

## GAPS SUMMARY

| # | Gap | Type | Severity |
|---|-----|------|----------|
| G4-1 | Trial counting in `hypothesis_registry` is manual — callers must call `increment_trial_count()` on every sweep iteration; pipeline does not auto-increment | Workflow discipline | Medium — DSR will be understated if trials are undercounted |
| G4-2 | Equity trade log for `ImplementationShortfall` must be constructed manually by the researcher; no automated path from `VectorizedBacktester` results to `trade_log` format | Workflow gap | Medium — creates room for inconsistent cost attribution |
| G4-3 | Options simulation uses GBM (log-normal) unless QuantLib Heston is configured; fat-tail events are underestimated | Known limitation (DD-09) | Low — documented; treat P&L tail estimates as lower-bound |
| G4-4 | CPCV default config (N=6, k=2) produces only 5 paths; `p5_sharpe` is the minimum of 5 observations, not a true 5th percentile | Architecture tradeoff | Low — architecture spec accepts this; worth noting for tail risk interpretation |
| G4-5 | MLflow fallback path (`OUTPUTS_DIR/../mlruns_fallback/`) uses relative path construction that could be brittle if `OUTPUTS_DIR` is not a standard path | Operational risk | Low — verify path resolution in production environment |
| G4-6 | `allow_continue=True` bypasses pre-registration gate; must be `False` in all non-test runs | Operational risk | Medium — no code enforcement; relies on researcher discipline |
| G4-7 | `research_verdict.json` does not auto-expire or flag regime change; a GO verdict approved in RISK_ON remains on disk unchanged if regime shifts to RISK_OFF | Design gap | High — Jordan must independently check current regime before acting on any verdict; this is enforced by CLAUDE.md Rule 4 but not by the research pipeline itself |

---

## VALIDATION REQUIREMENTS

To verify that Priya's outputs are correct (not just that the code runs), you need:

| Output | What you need to validate it |
|--------|------------------------------|
| FracDiff minimum d | A price series where you know the ADF result; verify find_minimum_d() agrees with manual statsmodels ADF call |
| Vol estimators | An S&P 500 OHLC series with a known realized vol period; compare Yang-Zhang output to a published realized vol estimate for the same period |
| Triple-barrier labels | A small hand-checkable series (20–30 observations); verify that label exit times and barrier types match manual calculation |
| CPCV PBO | Synthetic data with a known null (random signal, no edge); PBO should be ~0.50 for a random signal |
| DSR | Fixed n_trials = 1, clean IID returns; verify DSR ≈ PSR (they converge when N=1 and SR* ≈ 0) |
| MC P&L distribution | A known IV/RV spread with analytic breakeven; verify that mean_pnl sign matches the spread direction and that Kamal-Derman sigma matches simulated std_pnl within ~20% |
| research_verdict.json | Run verify_priya_integration.py with real macro.db data and check that the written JSON matches the pipeline output dict |
