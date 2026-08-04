---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# Workflow — Editing Parameters Safely

*Changing an assumption is a first-class, audited act. This is the loop that
makes it safe.*

## The general loop (any component)

1. **Parameters page** → pick the component tab. Fields render from their
   specs: scalars as typed inputs with visible bounds, dicts/lists as JSON
   editors (parse errors block saving). Chips warn you up front:
   `research gate` (guarded) and `edit → backfill_regime_history` (recompute).
2. **Edit** — dirty fields highlight amber, each with its own reset.
3. **Preview** *(Marcus only, so far)* — "Preview today under draft"
   classifies the current snapshot under your draft without persisting
   anything and diffs it against active: *"today would be CAUTION (−0.18)
   instead of NEUTRAL (−0.06)"*. If the preview surprises you, stop and
   understand why before saving.
4. **Note** — write *why* ("VC threshold 0.55 per calibrate_divergence run
   of 07-03"). Future-you reads these in the history table.
5. **Save** — validation runs (bounds + cross-field rules like weights
   summing to 1.0); violations come back as a list; success creates and
   activates **version N+1** with a new 12-hex hash.
6. **Act on the response**:
   - `recompute_suggested: [backfill_regime_history]` → go to Jobs and run
     it, or accept that stored history now disagrees with live assumptions.
   - `guarded_fields_changed: […]` → you just moved a research gate; see below.
7. **Verify propagation** — the next job run's `param_hashes` (Jobs page)
   should show the new hash. Long-running processes (legacy scheduler)
   pick edits up on their next fresh subprocess/restart.

## Rollback

Parameters → *Show history* → any version → **activate**. This re-activates
the old payload **as a new version** (the trail is append-only), so
"rollback" is itself audited. To reproduce an old run exactly: match its
`param_hashes` against history hashes, activate, re-run.

## Component-specific cautions

- **Marcus weights/thresholds/score-mapping** — changes redefine what every
  historical regime *would have been*. Always preview; usually re-run
  `backfill_regime_history` so analogues/implications stay coherent; expect
  the regime label to move if today sat near a boundary.
- **Sarah stress library** — you can add scenarios (any key with
  `label/spot_shock/vol_shock_vpts/duration/character`) or re-shock existing
  ones. Remember: `vol_shock_vpts` is ABSOLUTE vol points. Edits immediately
  affect the Scenario lab *and* Jordan's book stress.
- **Priya gates (guarded)** — lowering `backtest_dsr_accept_threshold` or
  the haircut makes it *easier for bad strategies to reach Jordan*. The
  system permits it (research needs flexibility) but logs loudly and stamps
  the verdict with the gate version that approved it. Treat any GO produced
  under relaxed gates as provisional; note the justification.
- **Jordan `nav`** — every limit is %-of-NAV; if NAV is wrong, every check
  is. Update it when capital changes.
- **Ops times & scheduler** — scheduler v2 reads OpsParams **live on every
  tick**: schedule-time edits apply within a minute, no restart. The master
  switch is `ops.scheduler_enabled`. Retry policy
  (`job_max_retries`/`job_retry_wait_seconds`) applies from the next
  failure.

## Programmatic edits

```python
from systems.params import set_params
set_params("jordan", {"nav": 250_000}, note="capital increase 2026-07")
```
Same validation, same versioning, same hashes as the GUI.
