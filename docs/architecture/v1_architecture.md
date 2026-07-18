# v1.0 Architecture — The Workstation
**Status:** build in progress (Phases 0–2 implemented, 3–6 pending)
**Plan of record:** approved v0.5 → v1.0 upgrade plan (2026-07-06)
**Companion docs:** `current_state.md` (v0.5 ground truth), `docs/audit/01–04`,
`Claude/Trading System/Marcus Macro/macro_system_architecture_improvements.md`,
`Claude/Trading System/Sarah vol/sarah_vol_upgrade_path_*`

---

## 1. What v1.0 Is

v0.5 was a headless analytics pipeline: six analyst-components producing JSON
files and DB rows you consumed by running Python. v1.0 turns it into **a desk
you operate**:

1. **Control surfaces, not constants.** Every tunable lives in a versioned
   parameter registry, editable in the GUI, validated, and stamped (by hash)
   onto every run that used it.
2. **A closed decision loop.** Jordan turns GO verdicts + regime context into
   sizes and live limit monitoring over the real book (imported read-only
   from the Research Capture System); Alex turns daily runs into a weekly
   review; every trade links back to the regime/vol/memo context that
   justified it.
3. **One workstation.** React frontend over a FastAPI service layer; the
   fragility-first command deck is the 7am screen; each persona gets a
   workspace with analytics and its parameter panel side by side.

Out of scope for 1.0 (deferred to 1.1+): Kai/IBKR execution, live-capital
deployment (gated on CBOE historical data validation U3.3/U5.2),
regime-conditional weights (Marcus Gap 2), forward scenario layer (Gap 6),
paid data tiers.

---

## 2. Topology

```
Browser (React, vite dev :5173 / built bundle)
   │  REST + polling
FastAPI service layer  :8100   systems/api/
   ├── routes: params, jobs, context, marcus, (sarah, priya, jordan, ops — later phases)
   ├── read-only DuckDB connections (503 on writer-lock, never a stack trace)
   └── JobManager (thread) ──► subprocess: python -m systems.orchestration.run_job <name>
                                  └── the ONLY DuckDB writer while running
Parameter registry             systems/params/   (versions in trading.db)
Engines (v0.5, refactored)     systems/signals · systems/sarah · systems/backtest
Jordan risk layer (Phase 5)    systems/risk/
RCS bridge (Phase 5)           read-only SQLite adapter → ../research-capture-system (:8099)
Legacy Dash app  :8050         retired once the Marcus workspace reaches parity
```

### Single-writer discipline (DuckDB)
- Pipeline writes happen only inside job subprocesses, one at a time
  (JobManager runs a single worker queue).
- API reads use short-lived `read_only=True` connections and return HTTP 503
  if a writer holds the lock.
- The legacy Dash behavior of `classify(persist=True)` on page refresh is
  gone; GET endpoints never write.

### Parameter registry (`systems/params`)
- One dataclass per component (`marcus`, `sarah`, `priya`, `jordan`, `ops`,
  `data`) with `FIELD_SPECS` metadata (label/help/bounds/guarded/recompute)
  that drives the GUI form and validation.
- Versioned storage in `trading.db:parameter_versions`; every save is a new
  version; rollback re-activates an old payload **as a new version** (history
  is never rewritten).
- `get_params(component)` (5s cache) / `set_params` / `get_history` /
  `activate_version` / `all_active_hashes()`.
- Runs stamp `all_active_hashes()` into the jobs table (and, Phase 4, MLflow).
- **Legacy compatibility:** `from config import REGIME_THRESHOLDS` still works
  — config.py resolves tunables through the registry via module __getattr__
  (map: `systems/params/compat.py`). Import-time binding caveat: long-running
  processes see edits on their next fresh process; refactored engines
  (regime_classifier, scenario_engine) read live.
- **Guarded fields** (Priya gates: DSR/PBO/haircut/…): edits allowed but
  flagged, logged loudly, and the producing version hash rides on every
  verdict.
- **Recompute flags**: fields like Marcus weights/thresholds advertise
  `backfill_regime_history` so the GUI can offer the re-run after an edit.
- Registry unavailable (writer lock) ⇒ loud-warning fallback to code defaults;
  a pipeline never crashes because the registry was busy.

### Jobs (`systems/orchestration`)
- `jobs` table in trading.db: id, name, status, param_hashes, timestamps,
  exit_code, log_tail, error.
- Parent (API) owns all jobs-table writes; children print, exit, and write
  only their own pipeline tables. Fresh interpreter per run ⇒ latest params.
- Phase 6 adds: schedule from `OpsParams`, dependency enforcement
  (Sarah blocks on Marcus success), retries, catch-up guard, alerting.

---

## 3. GUI Design Brief (Document 3 of the audit prompt)

**Primary workflows** (max 5, per the audit prompt):
1. *As a trader, I want a fragility-first morning read* — command deck:
   fragility level → regime badge → active divergence + duration →
   30d transition probability → contract freshness → recent jobs.
2. *As a trader, I want to understand what's driving the regime* — Marcus
   workspace: component score bars + staleness, attribution, vol/credit
   conditional interpretations with watch-conditions, state vector +
   historical analogues, regime-conditional return implications with
   reliability flags and configuration caveat.
3. *As an operator, I want to change an assumption and see what it does
   before committing* — Parameters page: typed form from FIELD_SPECS,
   bounds/validation errors inline, **preview-today-under-draft** (Marcus),
   save-as-version with note, history + one-click rollback, guarded-gate and
   recompute warnings.
4. *As an operator, I want to run and monitor pipelines without a terminal* —
   Jobs page: one-click runs, single-writer serialization, live status,
   param-hash provenance per run, log tails, DB/registry health chips.
5. *(Phases 3–5)* pre-trade tools (Sarah), research workbench (Priya), risk
   board (Jordan).

**Implementation priority** honored the audit's validated-outputs rule:
views over validated persisted outputs first (regime history, series,
calendar, COT, return stats), preview/compute views second, aspirational
views (analog search over thin history, VVIX monitor) carry their confidence
fields directly in the UI.

**Known gaps that block GUI features** (from audits, addressed in phases):
`vol_surface` table unpopulated (Phase 3), analytics endpoints for RCS trades
(Phase 5), weekly review artifacts (Phase 6).

---

## 4. Component Delta vs v0.5

| Area | v0.5 | v1.0 change |
|---|---|---|
| config.py | ~60 tunables hardcoded | infrastructure literals only; tunables resolve through the registry facade |
| RegimeClassifier | WEIGHTS duplicated with config; SCORE_TO_REGIME hardcoded | params-injected; weight-sum assertion; `RegimeResult.params` so attribution/preview use the same params that scored |
| ScenarioEngine | grid/stress/kill hardcoded | all from `SarahParams`; stress library user-editable; legacy module constants remain as code-default aliases |
| Dashboard | Dash :8050, display-only, classify-on-refresh | React workstation :5173 / FastAPI :8100; Dash retired at parity |
| Marcus analytics | label-first | `systems/signals/regime_analytics.py`: state vector, geometry, NN analogues, fragility (+ divergence timeline), implications, interpreter MVP |
| Orchestration | scheduler.py blocking loop | JobManager + subprocess runner now; full scheduler replacement in Phase 6 |

New output/infra tables in trading.db: `parameter_versions`, `jobs`
(+ Phase 3 `pretrade_memos`, Phase 5 positions/planned trades).

---

## 5. Verification

- `scripts/golden_master.py` — capture/compare harness proving the registry
  migration is behavior-neutral (config values, full classification incl.
  attribution + transition probability, scenario grid/stress/kill/structures).
- `scripts/verify_v1_platform.py` — registry versioning/validation/rollback,
  facade resolution incl. container types, guarded edits, classifier +
  scenario-engine params wiring, lock-fallback resilience.
- `scripts/migrate_params.py [--check]` — idempotent seeding + legacy-name
  resolution report.
- Phase-gate: golden master green before any Phase ≥1 code touches engines.

## 6. Run

```bash
pip install -r requirements.txt          # adds fastapi + uvicorn
python scripts/migrate_params.py --check
python -m uvicorn systems.api.main:app --port 8100   # or python -m systems.api.main
cd frontend && npm install && npm run dev             # → http://localhost:5173
```
