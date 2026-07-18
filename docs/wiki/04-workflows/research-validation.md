# Workflow — Research Validation (Priya)

*From idea to GO/NO_GO without fooling yourself. The pipeline's whole design
is that the honest path is the only path — until the Phase 4 workbench GUI,
this runs from Python (see `scripts/verify_priya_integration.py` for a
complete worked example).*

## 0. Before touching data — register (Gate 1)

Write the hypothesis down: text, dataset id, signal type, and *the
mechanism* — why should this edge exist? Registration is what makes the
later multiple-testing correction honest.

```python
from systems.backtest.hypothesis_registry import ...  # register → hypothesis_id
```

**Discipline that the code can't enforce (yet):** every parameter
configuration you evaluate must call `increment_trial_count(dataset_id)`.
Undercounting trials silently inflates your DSR (audit G4-1; auto-counting
lands in Phase 4).

## 1. Audit the data (Gate 2)

`DataAudit` on the raw frame: survivorship heuristics, look-ahead, gaps,
minimum observations (252/126), option-spread floors. **Blockers stop you;
warnings go in the writeup.**

## 2. Build features & labels

FracDiff for price-derived features (find minimum d that passes ADF —
vol-surface features are usually already stationary, test first);
triple-barrier labels with vol-scaled barriers; uniqueness sample-weights
for overlapping positions.

## 3. Backtest

- **Equity/index**: `VectorizedBacktester` — one-bar execution lag, costs in
  bps, IS/OOS split, `parameter_sweep()` over your grid (this is where trial
  counting matters; the Sharpe-CV flag marks knife-edge parameter peaks).
- **Options**: `OptionsBacktester` — 1,000-path MC delta-hedged P&L, three
  cost levels, Leland break-even; log every simulated trade for the
  shortfall gate.

## 4. Validate (the part most backtests skip)

CPCV over the returns (default 6C2 → 5 paths) → a *distribution* of
Sharpes + PBO. `OverfitDiagnostics` runs the four independent checks.
Regime-conditional analysis: a strategy profitable only in RISK_ON is a
regime bet — the verdict records the per-regime table for Jordan.

## 5. Correct the Sharpe

`SharpeEstimationPipeline`: Ljung-Box → η(q) annualization if autocorrelated
(theta strategies usually are; the naive √252 overstates by up to ~65%) →
Newey-West SE + CI → PSR → **DSR against your true trial count** →
minimum track record → 50% production haircut.

## 6. The verdict

`ResearchPipeline` enforces all 13 gates and writes
`research_verdict.json`. **NO_GO runs are logged too** — the failure
archive (MLflow, tagged `is_failure_archive_entry`) is consulted by Gate 13
so you don't re-run dead ideas. `verdict_override` exists but requires a
written rationale and shows in the log.

## Reading the result

- `dsr < 0.95` with a big literal-vs-N_eff gap → your trials were mostly
  the same idea; the edge didn't survive honest counting.
- `pbo > 0.05` → the in-sample winner doesn't generalize. **Never optimize
  PBO down** — it's a diagnostic.
- `viable_after_haircut = false` at OOS Sharpe < 1.0 → real but too small
  to survive production degradation.
- Gates are `guarded` registry parameters: you *can* relax them
  ([how and why-not](editing-parameters.md#component-specific-cautions)),
  and the verdict will forever carry the hash of the gate-set that passed it.

## After a GO

Nothing is tradeable yet. The verdict goes to
[Jordan's intake](risk-and-sizing.md) — freshness + regime compatibility are
re-checked *at decision time*, not at validation time.
