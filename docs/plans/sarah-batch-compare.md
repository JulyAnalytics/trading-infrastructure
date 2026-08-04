# Plan — Sarah batch runs & comparison

Status: draft (2026-08-02)

## Goal

Run the Sarah vol pipeline on-demand for an **arbitrary batch of tickers** (not
just the configured daily universe), and **compare the results side-by-side**
in the UI.

## How it fits the current architecture

Today `sarah_daily_vol` job → subprocess → `run_daily_vol()` in
`systems/sarah/daily_vol_run.py` loops over `VOL_TICKERS` (registry param,
`sarah.vol_tickers`). Jobs carry no arguments (`systems/orchestration/jobs.py`
submits by name only), and the Sarah page has no comparison views beyond the
per-ticker monitor.

Plan, in three parts:

1. Give the pipeline an optional ticker list (`run_daily_vol(tickers=...)`).
2. Plumb per-job args through the existing JobManager → subprocess path (env
   var, no interface break; `scheduler_v2` callers unaffected).
3. Add read-only comparison endpoints (pure DB reads, no network) + a new
   "Batch & compare" tab in the Sarah page.

## Backend changes

### 1. `systems/sarah/daily_vol_run.py`

- `run_daily_vol(tickers: list[str] | None = None)`
  - `None` → `VOL_TICKERS` (daily mode, unchanged for `scheduler_v2`).
  - Provided → uppercase / dedupe, run just that batch.
- Batch mode skips writing `vol_signals.json` (that file is the "last daily
  run" context snapshot for `/api/context/vol-signals`; batch results persist
  to `trading.db`, which is the source of truth for all comparison reads).
  Log clearly.

### 2. `systems/orchestration/jobs.py`

- Add `args VARCHAR` column to `_JOBS_DDL` + `ALTER TABLE jobs ADD COLUMN IF
  NOT EXISTS args VARCHAR` in `_conn()` (same migration pattern as
  `depends_on`). Include `args` in `_row_to_dict`.
- `submit(..., args: dict | None = None)` — persist as JSON.
- `_run_one`: pass `JOB_ARGS_JSON` env var to the subprocess when args present.
- Bump `sarah_daily_vol` `timeout_s` 1800 → 3600 (each batch ticker = yfinance
  options chain + price history fetch).

### 3. `systems/orchestration/run_job.py`

- `_sarah_daily_vol()` reads `JOB_ARGS_JSON`, extracts `tickers`, calls
  `run_daily_vol(tickers=...)`.

### 4. `systems/api/routes/jobs.py`

- `POST /api/jobs` accepts optional `args` → `MANAGER.submit(..., args=...)`.

### 5. `systems/api/routes/sarah.py` — new comparison endpoints

All read-only, no network:

- `GET /api/sarah/compare?tickers=SPY,QQQ,IWM` → latest vol_signals row per
  requested ticker (full `_SIGNAL_COLS` + `term_structure_json`) for the table
  + scatter.
- `GET /api/sarah/charts/term-structure-compare?tickers=...` → Plotly overlay:
  one ATM IV line per ticker (x=DTE, y=IV) from `term_structure_json`.
- `GET /api/sarah/charts/iv-history-compare?tickers=...&days=126` → Plotly
  overlay of ATM IV 30d lines per ticker.
- `GET /api/sarah/charts/scatter-vol-map?tickers=...` → Plotly scatter:
  x = iv_rank, y = vrp_proxy_bkwd, size = atm_iv_30d, color per ticker,
  hover = ticker + metrics.
- 404-style responses for empty/unknown tickers, matching existing endpoint
  conventions.

## Frontend changes

### 6. New `frontend/src/pages/sarah/BatchCompare.tsx`

**Batch run card**

- Textarea for tickers (comma / space / newline separated), normalize +
  validate, "Run batch" button.
- `apiSend("/api/jobs", "POST", { name: "sarah_daily_vol", args: { tickers } })`.
- Poll `GET /api/jobs/{id}` every 3s (JobsPage pattern); status chip + failure
  list on completion.

**Compare card**

- Multi-select ticker chips seeded from `/api/sarah/signals` (auto-selects the
  just-run batch).
- Views (all four requested):
  1. **Ranking table** — sortable columns: Ticker, ATM IV 30d, IV rank,
     IV percentile, VRP + signal, TS shape, 25Δ RR, vol regime, macro regime.
  2. **Term structure overlay** — `PlotlyFig` from the compare endpoint.
  3. **IV history overlay** — `PlotlyFig` from the compare endpoint.
  4. **Vol opportunity scatter** — `PlotlyFig` from the compare endpoint.
- Reload signals + comparison when the batch job succeeds.

### 7. `frontend/src/pages/SarahPage.tsx`

- Add 5th tool tab "Batch & compare".

## Docs

- Update `docs/wiki/01-components/sarah-vol-workspace.md` and
  `docs/wiki/02-platform/jobs-and-scheduling.md` with the batch-run workflow,
  new `args` job parameter, and comparison endpoints.

## Verification

- `python -m compileall` on touched modules + import check.
- Run `run_daily_vol(tickers=["SPY", "QQQ"])` once for real (needs fresh
  `regime_state.json`) — verify DB writes + no vol_signals.json overwrite.
- curl the three new endpoints.
- `npm run build` (tsc) in `frontend/` for type-check.
- Manual check of the new tab against the running API + a live batch submit.

## Notes / defaults

- Batch tickers persist into `vol_signals` / `vol_surface` — they accumulate
  IVR history and appear in the Vol Monitor table (de-facto watchlist).
  Intentional: IV rank and comparisons only get meaningful as history builds.
  Flagging in case batch runs should instead be ephemeral.
- Single job queue (single-writer discipline) is preserved — batch jobs
  serialize with scheduled jobs.
