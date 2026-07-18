# Alex — Orchestration & Operations

**Status:** job core 🟡 unverified · legacy scheduler ✅ live · weekly review / alerting / dependency-aware schedule ⬜ Phase 6
**Code:** `systems/orchestration/` (v1.0) + `scheduler.py` (legacy) · **Params:** registry component `ops`

## Job

Make the system run itself on time, tell you when it breaks, and compress
the week into a review. Alex owns *when* things run; the engines own *what*.

## v1.0 job core (built)

- **`jobs.py` — JobManager.** A single worker thread with a queue. Each job
  runs as `python -m systems.orchestration.run_job <name>` in a **fresh
  subprocess**: it imports the latest registry parameters, is the only
  DuckDB writer while it runs, and can crash without touching the API.
  The parent owns all `trading.db:jobs` writes (status, timestamps,
  exit code, 4KB log tail) and stamps each job with
  `param_hashes` — full provenance per run.
- **`run_job.py` — the job menu.** `marcus_classify`, `fred_incremental`,
  `sarah_daily_vol`, `snapshot_pdf`, `backfill_regime_history`,
  `calibrate_divergence`. Adding a job = one runner function + one
  `JOB_SPECS` entry (label, description, timeout, what it writes).
- Trigger from the GUI *Jobs & Health* page or `POST /api/jobs`.

## Legacy scheduler (still the clock today)

`scheduler.py` (blocking loop, `schedule` lib): weekdays 18:05 macro
pipeline → classify → contract; 18:15 snapshot PDF; 08:00 Sarah vol run;
Sundays 20:00 full FRED refresh + 20:05 calendar. Known weaknesses (audit
#1): runs-on-start duplication, no dependency enforcement (a failed evening
Marcus doesn't stop the morning Sarah beyond the staleness check), no
alerting.

## Phase 6 (planned) — scheduler v2

Replace the loop with the job core: schedule times from `OpsParams`
(already defined: `daily_pipeline_time`, `vol_run_time`, …, retries,
`regime_staleness_hours_production`), **dependency enforcement** (Sarah
blocks on Marcus success), catch-up-on-start guard, macOS-notification +
GUI alert feed on failures and limit breaches, and the **weekly review
generator**: regime week + vol summary + research runs (MLflow) + risk
flags + RCS activity (`rcs_bridge.weekly_activity()` already built) →
markdown + PDF + an EV-ranked research queue.

## Inputs · Outputs · API

| | |
|---|---|
| Reads | registry (`ops`), JOB_SPECS |
| Writes | `trading.db:jobs` |
| API | `/api/jobs*`, `/health` ([reference](../02-platform/api-reference.md#jobs--health)) |

## Operating notes

- One job at a time is a feature (single-writer), not a bug — the GUI
  disables run buttons while anything is queued/running.
- A job's `param_hashes` answer "what assumptions produced this run?" —
  match them against the Parameters page history.
