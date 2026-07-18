# Priya — Research Validation Engine

**Status:** engine ✅ complete (v0.5 stages 1–8, verified by `scripts/verify_priya*.py`) · workbench GUI ⬜ Phase 4
**Code:** `systems/backtest/` (15 modules) · **Params:** registry component `priya` (gates are `guarded`)

## Job

Make it *hard to fool yourself*. Priya is not a backtester that finds
strategies; she is a gauntlet that kills bad ones. A strategy only reaches
Jordan with a `GO` verdict after pre-registration, leak-proof validation,
multiple-testing correction, cost realism, and a production haircut.

## The eight layers

| # | Module(s) | What it does |
|---|---|---|
| 1 | `hypothesis_registry.py` | Register the hypothesis (text, dataset, rationale) BEFORE touching data; count every parameter trial per dataset — the N that DSR penalizes. Stored in `trading.db:hypothesis_registry`. |
| 2 | `data_audit.py` | Blockers vs warnings: survivorship heuristics, look-ahead, gaps, minimum observations (252 equity / 126 options), option-spread floors (Hilpisch empirical bounds — all registry params). Blockers stop the pipeline. |
| 3 | `feature_engineering.py`, `vol_estimators.py` | FracDiff (minimum-d stationarity with memory retention) + five RV estimators (incl. Yang-Zhang) + vol cones with Hodges-Tompkins correction. |
| 4 | `label_construction.py` | Triple-barrier labels (profit/stop/time, vol-scaled widths — registry multipliers), Mode A (underlying) / Mode B (options P&L), meta-labeling, and uniqueness-based sample weights for overlapping positions. |
| 5 | `vectorized_engine.py`, `options_engine.py` | Equity: signal → 1-bar-lagged, cost-adjusted backtest, parameter sweeps with a Sharpe-CV overfitting flag. Options: 1,000-path Monte Carlo delta-hedged P&L with three cost levels (entry/exit, hedge trades, hedge drag) and Leland break-even spread; GBM fallback documented as tail-optimistic. |
| 6 | `purged_cv.py`, `cpcv.py`, `overfit_statistics.py` | PurgedKFold + embargo; CPCV (default 6 groups choose 2 → 5 paths) giving a Sharpe *distribution* + PBO; four-test overfit verdict (PBO, IS→OOS β, P[OOS loss], stochastic dominance). |
| 7 | `sharpe_pipeline.py`, `strategy_risk.py`, `impl_shortfall.py` | Lo (2002) autocorrelation-corrected annualization (Ljung-Box gated), Newey-West SEs, PSR, DSR (literal-N and N_eff), minimum track record; binomial P[edge ≤ 0]; implementation shortfall gate (P&L ≥ 2× execution costs). |
| 8 | `research_pipeline.py`, `experiment_tracker.py` | `ResearchPipeline` wires it all, enforces the **13 PROCESS_GATES**, logs every run (including NO_GO failures, tagged as failure-archive entries) to MLflow (`data/mlruns`, JSON fallback), and writes the Jordan contract. |

## The 13 process gates

`hypothesis_registration` → `data_audit_clearance` → `bar_type_documented` →
`regime_conditional` → `cpcv_path_distribution` → `pbo_threshold` →
`permutation_test` → `ljung_box_se_method` → `dsr_threshold` →
`oos_degradation` → `production_haircut` → `leland_breakeven` (options) →
`failure_archive_check`.

Gate thresholds (PBO < 0.05, DSR > 0.95, haircut 50%, min viable haircut
Sharpe 0.5, …) are **`guarded` registry parameters**: editable in the GUI,
but every edit is versioned, loudly logged, and stamped onto any verdict
produced under it. `allow_continue=True` bypasses pre-registration and is
for tests only.

## Output

[`research_verdict.json`](../03-contracts/output-contracts.md#research_verdictjson)
— verdict, haircut Sharpe, PBO/DSR, CPCV stats, regime-conditional Sharpe
table, minimum track record. Jordan's intake re-checks freshness and regime
compatibility before anything gets sized (the G4-7 fix).

## Known caveats (audit #4)

- Trial counting is caller-discipline today (auto-increment lands in Phase 4).
- Equity trade-log for implementation shortfall is manually constructed
  (auto-builder lands in Phase 4).
- CPCV default = 5 paths: fine per spec, but `p5_sharpe` is a minimum of 5,
  not a real percentile.
- MC tails are GBM-optimistic without QuantLib Heston.

## Using it (until the Phase 4 GUI)

```python
from systems.backtest.hypothesis_registry import ...   # register first!
from systems.backtest.research_pipeline import ResearchPipeline
# see scripts/verify_priya_integration.py for a full worked example
```
Runs appear in MLflow (`mlflow ui --backend-store-uri data/mlruns`) and the
latest verdict shows on the workstation Command Deck.
