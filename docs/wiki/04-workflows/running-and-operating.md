---
domain: trading-system
stage: wiki
project: v1-workstation
persona: alex
status: active
---

# Running & Operating the System

## One-time setup

```bash
cd ~/Nextcloud/Trading/trading-infrastructure
# The project venv (Python 3.11.9 via pyenv) — use ITS interpreter, not system python3:
venv/bin/pip install -r requirements.txt
# .env must contain FRED_API_KEY (free key from fred.stlouisfed.org)

# Frontend (one-time)
cd frontend && npm install && cd ..

# Verification gate (see 05-status/verification.md)
bash scripts/run_phase0_gauntlet.sh <scratch_dir>   # golden master + registry suite
venv/bin/python scripts/verify_jordan.py
venv/bin/python scripts/verify_v1_platform.py

# Seed/inspect the registry explicitly (idempotent)
venv/bin/python scripts/migrate_params.py --check
```

> **Interpreter gotcha:** system `python3` has no pandas. Every command in
> this wiki that says `python` means `venv/bin/python`.

## Daily operation — two processes, that's all

```bash
# 1. API — includes the job worker AND scheduler v2.
#    Auto-starts at login: the infra-launcher daemon (launchd
#    com.jun.infra-launcher, KeepAlive) starts `trading-api` automatically —
#    its manifest marks the project `autostart: true` (same mechanism as
#    source-flagger). No panel Start needed after a reboot/login. Manual
#    start (the exact command the launcher runs):
venv/bin/python -m uvicorn systems.api.main:app --host 127.0.0.1 --port 8100
# 2. Workstation (terminal 2)
cd frontend && npm run dev          # → http://localhost:5173
# 3. Journal (separate app, when you're journaling)
~/Nextcloud/Trading/research-capture-system/start.sh   # → :8099
```

**The API comes up automatically at login.** The infra-launcher daemon
(`~/Nextcloud/Tools/infra-launcher/`, `projects.json`) auto-starts
`trading-api` at boot (`"autostart": true`), so the scheduler survives
reboots without a panel click — same as source-flagger. Note that this is
login-scoped: if the MacBook is off or asleep at a scheduled time, the job
fires once on catch-up when the API is next up (the jobs table prevents
double runs). If the launcher daemon is ever unavailable, the manual
command above is the fallback.

**There is no separate scheduler process anymore.** Scheduler v2 runs inside
the API: weekday evenings `fred_incremental → marcus_classify →
snapshot_pdf`, weekday mornings `sarah_daily_vol → jordan_daily_check`
(blocking on Marcus success if the regime is stale), Sunday `fred_full`,
Friday `weekly_review`. Times come from OpsParams and apply live; the
master switch is `ops.scheduler_enabled`. If the API starts after a
scheduled time, the missed job runs once (catch-up) — never twice (the
jobs table is the guard). The legacy `scheduler.py` and the :8050 Dash app
are **retired — do not run them** (`scheduler.py` now exits non-zero if
invoked).

**Only one API process at a time.** Starting the API acquires a PID-file
lock (`data/api.pid`); a second start will SIGTERM the first and take over
automatically, so you don't need to manually kill a stale instance before
restarting. A `kill -9` leaves the PID file stale and the next start
recovers cleanly. If the API ever refuses to start with "PID reuse" — the
file names a process that isn't python/uvicorn — inspect `data/api.pid`
and remove it once you've confirmed it's stale.

On-demand runs: workstation → **Jobs & Health** → run buttons (one at a
time by design). CLI equivalent:
`venv/bin/python -m systems.orchestration.run_job marcus_classify` etc.
(only when the API is not mid-write — prefer the Jobs page).

## Health checklist

`GET :8100/health` (or the Jobs page chips): registry ok · macro.db /
trading.db present · current job · six param hashes. Then the **alerts
feed** — job failures (after retries) and limit breaches land there with a
macOS notification; ack them after acting. Command Deck shows the regime
contract's freshness — **if it's red, run `fred_incremental` then
`marcus_classify` before trusting anything downstream.**

## Common issues

| Symptom | Cause → fix |
|---|---|
| API returns 503 | a pipeline job holds the DB write lock — wait for it to finish (Jobs page) |
| `regime_state.json … stale` errors | evening pipeline didn't run (laptop asleep?) — trigger `fred_incremental` + `marcus_classify`; catch-up handles the current day automatically once the API is up |
| Sarah run hard-fails at start | that's Rule 4 working — fix the regime first |
| Job failed, then succeeded | that's the retry ladder (`retry:<origin>:aN` in *requested by*) — only exhausted retries alert |
| Job failed: `dependency not satisfied` | its prerequisite failed — fix that job; the refusal is the design |
| IVR shows `insufficient` | < 252 days of stored history for that ticker; the number is real but statistically weak |
| Registry warning "FALLING BACK TO CODE DEFAULTS" | trading.db was writer-locked when a run started — re-run it |
| Jobs page buttons disabled | something is queued/running — single-writer serialization |
| `ModuleNotFoundError: pandas` | wrong interpreter — use `venv/bin/python` |
| Weekly review section says "unavailable" | that source produced nothing this week — the review reports it honestly rather than failing |

## Ports

:8100 API (+ scheduler + job worker) · :5173 workstation (dev) ·
:8099 RCS journal. *(Retired: :8050 Dash.)*

## Verification scripts (run after any platform change)

`scripts/verify_v1_platform.py` (34 checks: registry/facade/engine wiring) ·
`scripts/verify_jordan.py` (21: risk math, bridge read-only) ·
`scripts/verify_priya.py` + `verify_priya_integration.py` (research
pipeline, synthetic + real data) · `scripts/golden_master.py` +
`run_phase0_gauntlet.sh` (behavior neutrality).

## Regenerating wiki screenshots

```bash
node scripts/capture_wiki_screenshots.mjs   # needs both servers running
```
