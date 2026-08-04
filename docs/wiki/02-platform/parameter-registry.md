---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# Parameter Registry

**Status:** 🟡 unverified · **Code:** `systems/params/` · **GUI:** *Parameters* page
**Decision record:** [ADR-002](../../design_decisions/ADR-002-parameter-registry.md)

The registry is v1.0's central idea made concrete: **every number that
shapes an output is inspectable, editable, validated, versioned, and
stamped onto the runs that used it.** Nothing tunable lives in code
anymore — code carries only the *defaults* that seed version 1.

## The model

Six components, one dataclass each (`systems/params/models.py`):

| Component | Governs | Highlights |
|---|---|---|
| `marcus` | regime classification | weights, threshold families, score→regime floors, divergence + confidence cutoffs, staleness windows |
| `sarah` | vol pipeline + scenario tools + RCS trade intake | tickers, IVR/analog/VVIX windows, catalyst types, full grid geometry, **the stress-scenario library itself**, kill assumptions, break-even search, **`underlier_map`** (position ticker → options-liquid underlier), `intake_poll_minutes`, `intake_fire_on_idea` |
| `priya` | research engine + gates | min observations, spread floors, **gate thresholds (guarded)**, CPCV/MC defaults, Sharpe/vol-estimator/labeling settings, sweep-overfit flags |
| `jordan` | risk limits | NAV, delta/vega/single-position limits, drawdown alert/halt, default risk-per-trade, verdict max age |
| `ops` | schedule + orchestration | run times, production staleness, retry policy |
| `data` | calendars/universes | FOMC dates, COT instruments, series disable-list, dashboard refresh |

Every field has `FIELD_SPECS` metadata — label, help text, numeric
`bounds`, `guarded` (research-gate) and `recompute` (invalidation) flags —
which is what renders the GUI form and enforces validation. Full field
tables: [parameter-schemas.md](../03-contracts/parameter-schemas.md).

## The lifecycle of an edit

```
GUI form (or set_params()) ──► validate (bounds + cross-field rules,
   e.g. weights sum to 1.0, k_test < n_groups, HH:MM times)
        │ reject 422 with every violation listed
        ▼
INSERT parameter_versions (component, version=N+1, payload, hash, note)
   + flip `active` — the previous version is never modified
        ▼
in-process cache invalidated → get_params() serves the new version
        ▼
next job subprocess imports fresh → runs under the new hash
```

- **Rollback** = re-activating an old payload **as a new version** — the
  audit trail is append-only.
- **Guarded fields** (DSR/PBO/haircut/significance/min-viable-Sharpe):
  the save succeeds but logs loudly and the response lists
  `guarded_fields_changed`; any verdict produced under that version carries
  its hash forever.
- **Recompute flags**: editing Marcus weights/thresholds returns
  `recompute_suggested: ["backfill_regime_history"]` — the GUI points you at
  the job that makes history consistent with the new assumptions.
- **Preview** (Marcus): classify *today* under the draft before saving —
  `POST /api/marcus/preview` diffs active vs candidate regime/score/confidence.

## How code consumes it

```python
from systems.params import get_params, all_active_hashes
p = get_params("sarah")          # typed SarahParams, active version, 5s cache
p.stress_scenarios               # live, GUI-edited library
run_record["param_hashes"] = all_active_hashes()   # provenance stamp
```

**Legacy compatibility:** `from config import REGIME_THRESHOLDS` still works
— `config.__getattr__` resolves ~48 legacy names through
`systems/params/compat.py` (returning defensive copies, original container
types restored). But from-imports bind at import time: long-running
processes see edits only on their next fresh process. That's why jobs are
subprocesses, and why engines call `get_params()` at call time
(CLAUDE.md Rule 1).

## Failure behavior

If trading.db is writer-locked when a pipeline asks for parameters, the
registry retries briefly and then **falls back to code defaults with a loud
warning** — a mid-edit GUI can never crash a run, but the log tells you the
edit didn't apply to it.

## Reproducing any past run

1. Find the run's `param_hashes` (jobs table / MLflow).
2. Parameters page → component → *history* → match the hash → *activate*.
3. Re-run the job. Same assumptions, bit-for-bit.
