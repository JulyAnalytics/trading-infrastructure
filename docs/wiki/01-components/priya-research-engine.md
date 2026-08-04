---
domain: trading-system
stage: wiki
project: v1-workstation
persona: priya
status: active
---

# Priya — Research Validation Engine & Workbench

**Status:** engine ✅ (stages 1–8, `verify_priya*.py` green) · workbench GUI ✅ live (2026-07-18) · G4 audit fixes ✅ closed
**Code:** `systems/backtest/` (15 modules) · **GUI:** *Priya · Research* page
**API:** `/api/priya/*` · **Params:** registry component `priya` (gates are `guarded`)
**Deeper reference:** [audit #4](../../audit/04_priya_research_layer.md)

## What Priya does, in plain language

Almost every backtest you will ever run looks profitable, and almost none of
that profit is real. It leaks in through look-ahead bias, survivorship,
ignored costs, and — most of all — **multiple testing**: try 40 parameter
combinations and the best one looks brilliant by luck alone.

Priya is not a backtester that finds strategies. She is a **gauntlet that
kills bad ones**. A strategy idea enters as a pre-registered hypothesis and
either dies at a named gate (and is archived as a useful negative result) or
exits with a `GO` verdict that Jordan is allowed to size. The workbench makes
that whole discipline a guided GUI flow.

> **Learning anchor.** The single most important habit Priya teaches:
> **register the hypothesis before touching the data, and count every trial.**
> The Deflated Sharpe Ratio (DSR) explicitly discounts your result by how
> many things you tried — which only works if the count is honest. The
> workbench now counts for you.

## The workspace

![Priya workbench](../images/priya-workbench.png)

Seven surfaces, top to bottom — deliberately in the order the discipline
requires:

| Surface | Gate it implements |
|---|---|
| **Hypothesis registration** | Gate 1 — hypothesis text, dataset ID, signal type, and *rationale* (the economic reason the edge should exist) recorded before any test. Duplicate content returns the existing ID. |
| **Data audit runner** | Gate 2 — blockers (too little data, look-ahead) stop the pipeline; flags (time-bar pathologies) warn. |
| **Backtest configurator** | pick hypothesis + ticker + signal (momentum / mean-reversion) + params or a sweep grid + costs → one click runs Stages 5–8. |
| **Results panels** | verdict banner, gates passed/failed chips, DSR/PBO/haircut table, CPCV path-Sharpe chart, regime-conditional Sharpe table, sweep table. |
| **Current Jordan contract** | the live `research_verdict.json`, including the regime it was validated under. |
| **Gates display** | current guarded thresholds (edit on the Parameters page — every change is versioned and stamped). |
| **Run archive** | every run ever logged, filterable All / GO / **Failure archive** — NO_GO results are kept on purpose. |

## The eight engine layers (what actually runs)

| # | Module(s) | What it does |
|---|---|---|
| 1 | `hypothesis_registry.py` | Pre-registration + per-dataset trial counting (the N that DSR penalizes). `trading.db:hypothesis_registry`. |
| 2 | `data_audit.py` | Blockers vs flags: minimum observations (252 equity / 126 options), look-ahead, gaps, survivorship heuristics, option-spread floors (Hilpisch empirical bounds — registry params). |
| 3 | `feature_engineering.py`, `vol_estimators.py` | FracDiff (minimum-d stationarity that keeps memory) + five RV estimators (Yang-Zhang preferred) + vol cones (Hodges-Tompkins). |
| 4 | `label_construction.py` | Triple-barrier labels (profit/stop/time, vol-scaled — registry multipliers), meta-labeling, uniqueness weights for overlapping samples. |
| 5 | `vectorized_engine.py`, `options_engine.py` | Equity: 1-bar-lagged, cost-adjusted vectorized backtest; **`parameter_sweep(dataset_id=…)` auto-records every combination as a trial (G4-1)**; **`build_trade_log()` turns results into an implementation-shortfall trade log (G4-2)**. Options: 1,000-path MC delta-hedged P&L, three cost levels, Leland break-even; GBM tails documented as optimistic. |
| 6 | `purged_cv.py`, `cpcv.py`, `overfit_statistics.py` | PurgedKFold + embargo; CPCV (6 choose 2 → 5 paths) → Sharpe *distribution* + **PBO** (probability of backtest overfitting); four-test overfit report. |
| 7 | `sharpe_pipeline.py`, `strategy_risk.py`, `impl_shortfall.py` | Lo autocorrelation-corrected Sharpe (Ljung-Box gated), Newey-West SEs, PSR/**DSR**, minimum track record; P[edge ≤ 0]; execution-cost gate (P&L ≥ 2× costs). |
| 8 | `research_pipeline.py`, `experiment_tracker.py` | Orchestrates all gates; **auto-resolves `n_trials` from the registry (G4-1)**; logs every run to MLflow **with the active registry hashes stamped**; writes the Jordan contract **with `regime_at_verdict` (G4-7)**. |

## The statistics, for someone still learning them

| Number | What it really means | Gate |
|---|---|---|
| **Sharpe (annualized)** | return per unit of volatility. Raw Sharpe from a backtest is almost always inflated. | — |
| **IS / OOS split** | in-sample (fit) vs out-of-sample (last 30%, untouched). The **degradation ratio** between them is your first overfitting read. | soft |
| **PBO** | probability that the *best in-sample* config would underperform out-of-sample — computed by re-splitting many ways (CPCV). ~0.5 means your ranking is a coin flip. | **hard: < 0.05** |
| **DSR** | probability the Sharpe is real *after* penalizing for how many trials you ran and non-normal returns. | soft: > 0.95 to pass |
| **Permutation p** | Sharpe vs 1,000 shuffled versions of the returns — could randomness alone produce this? | warn ≥ 0.05 |
| **Production haircut** | assume only 50% of OOS Sharpe survives contact with reality; **viable** means the haircut Sharpe still clears 0.5. | hard-ish (verdict input) |
| **Regime-conditional Sharpe** | the strategy's Sharpe split by Marcus regime — an edge that only exists in RISK_ON is a regime bet, not an edge. | required output |
| **Min track record** | how many years of live trading you'd need before the Sharpe is statistically believable. Humbling on purpose. | — |

**A worked example (the first live workbench run):** SPY momentum, sweep of
4 windows → best config looked fine in-sample, but **PBO came back 0.467**
— the config ranking was a coin flip, i.e. the "edge" was parameter
selection luck. The pipeline stopped at the PBO gate, recorded all 4 trials
against the dataset, and returned a structured `gate_failed`. That outcome
is the product *working*.

## Process flow

```
register hypothesis (gate 1)  →  data audit (gate 2)
        │
POST /api/priya/run
  fetch prices (yfinance) → build signal → parameter_sweep
        │                        (every combo → trial counter, G4-1)
  best config → run_single → build_trade_log (G4-2)
        │
  ResearchPipeline (n_trials auto from registry)
    CPCV → PBO gate → Sharpe pipeline → DSR → permutation → strategy risk
    → implementation shortfall → 13 PROCESS_GATES → verdict
        │
  MLflow run (registry hashes + is_failure_archive_entry tag)
  research_verdict.json (+ regime_at_verdict, staleness guidance)
        ▼
  Jordan verdict intake (freshness + regime re-check before sizing)
```

## Workflows this component serves

- [Research validation](../04-workflows/research-validation.md) — the full guided loop
- [Risk & sizing](../04-workflows/risk-and-sizing.md) — what Jordan does with a GO
- [Editing parameters](../04-workflows/editing-parameters.md) — gate changes are guarded + stamped

## Known caveats (audit #4, current)

- CPCV default = 5 paths: fine per spec, but `p5_sharpe` is a minimum of 5
  observations, not a real percentile.
- MC tails are GBM-optimistic without QuantLib Heston (DD-09).
- The workbench's built-in signals (momentum, mean-reversion) are teaching
  scaffolds — real hypotheses eventually deserve their own signal code.
- `allow_continue=True` bypasses gates and is for tests only (G4-6) — the
  workbench never sets it.
