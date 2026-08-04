---
domain: trading-system
stage: wiki
project: v1-workstation
persona: alex
status: active
---

# Jobs & Scheduling

**Status:** ✅ job core + scheduler v2 + retries + alerts live (Phase 6, 2026-07-18) · legacy `scheduler.py` retired
**Code:** `systems/orchestration/` (`jobs.py`, `scheduler_v2.py`, `alerts.py`, `run_job.py`)

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
POST /api/jobs {name, depends_on?, args?}   (or scheduler v2 submits)
  → INSERT jobs row (status=queued, param_hashes=all_active_hashes(),
                     args=<json>)
  → worker picks it up
  → depends_on set? prerequisite must be status=succeeded,
       else this job FAILS ("dependency not satisfied") + warning alert
  → status=running
  → subprocess: python -m systems.orchestration.run_job <name>   (cwd=repo root)
       JOB_ARGS_JSON=<args> in the environment when args were given
       child prints; writes ONLY its pipeline tables
  → parent captures stdout+stderr (last 4KB → log_tail), exit code
  → succeeded, or failed → retry ladder:
       up to ops.job_max_retries resubmits (requested_by=retry:<origin>:aN,
       args carried forward), ops.job_retry_wait_seconds apart;
       exhausted → error alert (trading.db:alerts + macOS notification)
```

The parent is the only writer of the `jobs` table and retries its status
updates briefly if the child transiently holds the trading.db lock at
start/end.

**Per-run arguments.** `args` travels as an environment variable rather than
argv, so the child's interface stays `run_job <name>` and every existing
caller is unaffected. A runner that never reads `JOB_ARGS_JSON` behaves
exactly as before. Today only `sarah_daily_vol` reads it:

```json
{"tickers": ["AAOI"], "source": "rcs_intake",
 "rcs_trade_ulids": ["01KZ4AKE…"], "skip_regime_check": false}
```

`tickers` switches the run into **batch mode** — same pipeline, same
`vol_signals`/`vol_surface` writes, but `data/outputs/vol_signals.json` is
*not* overwritten (that file is the daily run's context snapshot; a two-ticker
intake batch must not stand in for the day's full-universe picture).

## The job menu (`JOB_SPECS` / `run_job.py`)

| Name | What it runs | Writes |
|---|---|---|
| `marcus_classify` | classify + persist + write regime_state.json | macro.db, outputs |
| `fred_incremental` | FRED pull + derived series + COT + macro calendar (network) | macro.db |
| `fred_full` | full-history FRED refresh + COT + calendar (Sundays) | macro.db |
| `sarah_daily_vol` | full daily vol pipeline incl. vol_surface + VVIX (network; needs fresh regime). `args.tickers` → ad-hoc batch instead of the daily universe | trading.db, outputs |
| `jordan_daily_check` | price the book, evaluate limits, alert on breach | trading.db (alerts) |
| `snapshot_pdf` | one-page regime PDF | data/snapshots |
| `weekly_review` | the Friday review (md + PDF) | reports/weekly |
| `backfill_regime_history` | recompute history under ACTIVE params — run after editing Marcus weights/thresholds | macro.db |
| `backfill_vvix_history` | one-time U5.1 VVIX bootstrap (idempotent) | trading.db |
| `calibrate_divergence` | divergence-threshold calibration report | — |

Adding a job: one runner function in `run_job.py` + one `JOB_SPECS` entry.

## Scheduler v2 — the clock

`scheduler_v2.py` runs a daemon loop inside the API process (60s tick).
Every tick reads OpsParams **live**, so schedule edits apply within a
minute; the master switch is `ops.scheduler_enabled`.

| When (OpsParams) | Chain |
|---|---|
| weekdays `daily_pipeline_time` (18:05) | `fred_incremental` → `marcus_classify` → `snapshot_pdf` (each `depends_on` the previous) |
| weekdays `vol_run_time` (08:00) | `sarah_daily_vol` → `jordan_daily_check`; if the regime is stale, a `marcus_classify` is inserted first and **Sarah blocks on its success** |
| Sunday `weekly_refresh_time` (20:00) | `fred_full` |
| Friday `weekly_review_time` (17:00) | `weekly_review` |
| every `sarah.intake_poll_minutes` (5), **every day** | RCS trade intake poll — reads `entity_events` read-only, upserts `sarah_trade_inputs`, submits one coalesced `sarah_daily_vol` batch, **and re-reads every trade it already tracks** (RCS emits no event for leg capture, so this is the only way a leg added after the first intake lands) |

**The intake poll is a poll, not a job.** It does no vol writes itself: it
reads RCS, writes a little intake metadata, and submits onto the same single
job queue, so it serialises with everything else. Its durable position is the
`sarah_intake_watermark` row, not memory — a restart re-polls harmlessly, and
a cycle that fails part-way replays rather than dropping a trade. It runs at
weekends too (a trade can be committed any day; a weekend vol pull is
screening, not execution, so a stale regime relaxes the gate there only).
See [Sarah — RCS trade intake](../01-components/sarah-vol-workspace.md#rcs-trade-intake).

**Catch-up-on-start, never double-run:** anything due today with no
jobs-table entry today is submitted once at startup. The guard is the
persisted jobs table — a restart cannot duplicate a run, and missed days
are *not* backfilled (yesterday's vol run on today's prices would be worse
than no row). Status surface: `GET /api/ops/schedule` / the Jobs page card.

**One API instance at a time** (`systems/orchestration/instance.py`): the
scheduler and the job worker both live as daemon threads inside the API
process, so two instances would mean two schedulers *and* two DuckDB
writers. On startup the API acquires `data/api.pid`; if a prior instance is
alive it gets SIGTERM'd (grace) then SIGKILL, and a stale PID from a
`kill -9` is recovered on next start. The PID-reuse guard refuses to kill a
process whose command line isn't python/uvicorn — if you ever see a refusal,
inspect `data/api.pid` and remove it manually once you've confirmed it's
stale.

Never run the retired root `scheduler.py` — it now refuses to start (exits
non-zero with a deprecation message) and would bypass the job system and
the single-writer discipline even if it didn't.

## Troubleshooting

- **503 from the API** while a job runs = a reader hit the writer lock;
  it clears when the job finishes.
- **Job failed** → expand its log tail on the Jobs page; the child's full
  print/traceback is there.
- **Edits didn't apply to a run?** Compare the run's `param_hashes` with the
  Parameters page — if the registry was locked mid-run you'll find the
  loud fallback warning in the log tail.
