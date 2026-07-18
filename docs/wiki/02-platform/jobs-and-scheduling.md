# Jobs & Scheduling

**Status:** job core 🟡 unverified · legacy scheduler ✅ live · scheduler v2 ⬜ Phase 6
**Code:** `systems/orchestration/` + legacy `scheduler.py`

## Why jobs are subprocesses

Three constraints, one design:

1. **DuckDB single-writer** — at most one process may write a database file.
   One JobManager worker → one pipeline subprocess at a time → never two
   writers.
2. **Parameter freshness** — `from config import X` binds at import; a fresh
   interpreter per run means every job executes under the registry's
   *current* active versions, hash-stamped at launch.
3. **Blast radius** — a crashing pipeline kills its subprocess, not the API.

## Anatomy of a run

```
POST /api/jobs {name}
  → INSERT jobs row (status=queued, param_hashes=all_active_hashes())
  → worker picks it up → status=running
  → subprocess: python -m systems.orchestration.run_job <name>   (cwd=repo root)
       child prints; writes ONLY its pipeline tables
  → parent captures stdout+stderr (last 4KB → log_tail), exit code
  → status=succeeded / failed (timeout per JOB_SPECS)
```

The parent is the only writer of the `jobs` table and retries its status
updates briefly if the child transiently holds the trading.db lock at
start/end.

## The job menu (`JOB_SPECS` / `run_job.py`)

| Name | What it runs | Writes |
|---|---|---|
| `marcus_classify` | classify + persist + write regime_state.json | macro.db, outputs |
| `fred_incremental` | FRED pull + derived series + COT (network) | macro.db |
| `sarah_daily_vol` | full daily vol pipeline (network; needs fresh regime) | trading.db, outputs |
| `snapshot_pdf` | one-page regime PDF | data/snapshots |
| `backfill_regime_history` | recompute history under ACTIVE params — run after editing Marcus weights/thresholds | macro.db |
| `calibrate_divergence` | divergence-threshold calibration report | — |

Adding a job: one runner function in `run_job.py` + one `JOB_SPECS` entry.

## Today's clock vs Phase 6

The **legacy `scheduler.py`** still provides the timetable (weekdays 18:05
macro → 18:15 snapshot → next-day 08:00 Sarah; Sundays full refresh +
calendar). Its known gaps — no dependency enforcement, no alerting,
run-on-start duplication — are the Phase 6 work: scheduler v2 drives the
job core from `OpsParams` times, blocks Sarah on Marcus success, retries
per policy, and raises macOS notifications + a GUI alert feed on failures
and limit breaches.

Until then it's safe to run both: cron/scheduler for the clock, the Jobs
page for on-demand runs — the single-worker queue serializes whatever the
API triggers, and the staleness gates protect ordering semantically.

## Troubleshooting

- **503 from the API** while a job runs = a reader hit the writer lock;
  it clears when the job finishes.
- **Job failed** → expand its log tail on the Jobs page; the child's full
  print/traceback is there.
- **Edits didn't apply to a run?** Compare the run's `param_hashes` with the
  Parameters page — if the registry was locked mid-run you'll find the
  loud fallback warning in the log tail.
