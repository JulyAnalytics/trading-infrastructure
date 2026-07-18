# Running & Operating the System

## One-time setup

```bash
cd ~/Nextcloud/Trading/trading-infrastructure
# The project venv (Python 3.11.9 via pyenv) — use ITS interpreter, not system python3:
venv/bin/pip install -r requirements.txt      # adds fastapi + uvicorn[standard]
# .env must contain FRED_API_KEY (free key from fred.stlouisfed.org)

# Frontend (one-time)
cd frontend && npm install && cd ..

# FIRST: pass the verification gate (see 05-status/verification.md)
bash scripts/run_phase0_gauntlet.sh <scratch_dir>   # golden master + registry suite
venv/bin/python scripts/verify_jordan.py

# Seed/inspect the registry explicitly (idempotent)
venv/bin/python scripts/migrate_params.py --check
```

> **Interpreter gotcha:** system `python3` has no pandas. Every command in
> this wiki that says `python` means `venv/bin/python` (or an activated
> venv). The launch config uses `python3` and should be pointed at the venv
> if the API fails to import pandas.

## Daily operation

```bash
# 1. API (terminal 1)
venv/bin/python -m uvicorn systems.api.main:app --host 127.0.0.1 --port 8100
# 2. Workstation (terminal 2)
cd frontend && npm run dev          # → http://localhost:5173
# 3. The clock (terminal 3 / tmux / launchd) — legacy scheduler until Phase 6
venv/bin/python scheduler.py
# 4. Journal (separate app)
~/Nextcloud/Trading/research-capture-system/start.sh   # → :8099
```

On-demand pipeline runs: workstation → **Jobs & Health** → run buttons
(one at a time by design). CLI equivalents:
`venv/bin/python -m systems.orchestration.run_job marcus_classify` etc.

## Health checklist

`GET :8100/health` (or the Jobs page chips): registry ok · macro.db /
trading.db present · running job · six param hashes. Command Deck shows the
regime contract's freshness — **if it's red, run `fred_incremental` then
`marcus_classify` before trusting anything downstream.**

## Common issues

| Symptom | Cause → fix |
|---|---|
| API returns 503 | a pipeline job holds the DB write lock — wait for it to finish (Jobs page) |
| `regime_state.json … stale` errors | evening pipeline didn't run — trigger `fred_incremental` + `marcus_classify` |
| Sarah run hard-fails at start | that's Rule 4 working — fix the regime first |
| IVR shows `insufficient` | < 252 days of stored history for that ticker; the number is real but statistically weak |
| Registry warning "FALLING BACK TO CODE DEFAULTS" | trading.db was writer-locked when a run started — your GUI edit didn't apply to that run; re-run it |
| Jobs page buttons disabled | something is queued/running — single-writer serialization |
| `ModuleNotFoundError: pandas` | wrong interpreter — use `venv/bin/python` |

## Ports

:8100 API · :5173 workstation (dev) · :8050 legacy Dash (retiring) ·
:8099 RCS journal.

## Verification scripts (run after any platform change)

`scripts/verify_v1_platform.py` (registry/facade/engine wiring, temp DB) ·
`scripts/verify_jordan.py` (risk math, bridge read-only) ·
`scripts/golden_master.py` + `run_phase0_gauntlet.sh` (behavior neutrality) ·
legacy: `verify_phase0.py`, `verify_priya*.py`, `check_data.py`.
