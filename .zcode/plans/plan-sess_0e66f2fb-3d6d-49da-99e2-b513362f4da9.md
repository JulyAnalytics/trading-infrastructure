# Execute: Sarah Batch Scan & Compare + UW-provenance groundwork

Synthesizing both batch-compare specs (most of the scan half already ships with RCS intake) and folding in the UW-import decisions that are cheap now but expensive-to-impossible after UW writes land (decision #1 `data_source` provenance + #2 contract freeze). The deeper UW decisions (client normalization, IVR derivation, conflict semantics, quota ledger) are captured as constraints/comments, not pre-built.

## Files & changes

### 1. `systems/sarah/vol_db.py`
- **DDL**: add `next_earnings_date DATE` (after `macro_regime`) and `data_source VARCHAR DEFAULT 'yfinance'` (after the JSON columns).
- **Migrations**: new `_VOL_SIGNALS_MIGRATIONS` tuple (same `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` pattern as `_PRETRADE_MEMOS_MIGRATIONS`); run it in `initialize_vol_schema()` alongside the existing migration loop.
- **`upsert_vol_signals()`**: add both columns to the column list + `VALUES` placeholders + params. `next_earnings_date` from `signals.get('next_earnings_date')`; `data_source` from `signals.get('data_source', 'yfinance')`.
- **Comment**: note the UW-import contract constraint — UW writes must produce the same column set and JSON conventions (same `term_structure_json` shape, `ts_shape` from `term_structure_slopes()`, IVR via `iv_context()`) so every reader stays single-shape.

### 2. `systems/sarah/catalyst_calendar.py`
- Add `next_earnings_date(ticker, today) -> str | None` — thin wrapper over existing `_earnings_candidates`, never raises.
- Add `has_near_term_catalyst(ticker, days=14, today=None, macro_conn=None) -> bool` — checks earnings + macro within `days`. Reuses `_earnings_candidates` + `_macro_candidates`.

### 3. `systems/params/models.py`
- Add `batch_inter_ticker_delay_s: float = 1.0` to `SarahParams` (after `chain_max_expirations`).
- Add a `FIELD_SPECS` entry with `bounds=(0.0, 10.0)` + help text.

### 4. `systems/sarah/daily_vol_run.py`
- **Refactor**: extract the 93-line inline loop body (`:212-305`) into module-level `_process_ticker(ticker, today, rate, spot_vix, macro_regime, max_exp) -> dict | None` (pure extraction, no behaviour change; returns signals dict or None for failures).
- **Stamp** `next_earnings_date` (via `next_earnings_date()`) and `data_source='yfinance'` into the signals dict inside `_process_ticker`.
- **Batch delay**: in the (now-thin) loop, `time.sleep(get_params("sarah").batch_inter_ticker_delay_s)` between tickers in batch mode only; `import time`.
- Loop becomes ~6 lines.

### 5. `systems/api/routes/sarah.py`
- Extend `_SIGNAL_COLS` to include `next_earnings_date, data_source`.
- **`GET /api/sarah/compare?tickers=AMD,PLTR`** — latest row per requested ticker; computes `iv_rv_spread`; returns `{as_of, rows, rankings}` where rankings sort tickers per numeric field (iv_rank, vrp_proxy_bkwd, skew_25d_rr, atm_iv_30d, ts_front_slope, rv_21d). 404 if none. `_py()` scrubs numpy/NaN.
- **`GET /api/sarah/charts/term-structure-compare?tickers=...`** — one scatter trace per ticker from parsed `term_structure_json`; x=DTE, y=ATM IV; per-ticker colour palette.
- **`GET /api/sarah/charts/iv-history-compare?tickers=...&days=126`** — per-ticker IV history traces.
- **`GET /api/sarah/charts/scatter-vol-map?tickers=...`** — one point/ticker: x=iv_rank, y=vrp_proxy_bkwd, size∝atm_iv_30d, hover=metrics; quadrant lines at 50/0.
- All read-only via `trading_conn()`, hand-built Plotly JSON via `_base_layout()` (no Plotly lib).

### 6. Frontend
- **`frontend/src/pages/sarah/BatchCompare.tsx`** (new): batch-run card (textarea + `skip_regime_check` checkbox → `apiSend("/api/jobs", "POST", {name:"sarah_daily_vol", args:{tickers, skip_regime_check}})` → poll `GET /api/jobs/{id}` every 3s, status chip, disable while any job running, auto-reload compare on success) + compare card (ticker multi-select chips seeded from `tickers` prop, client-side sortable ranking table using `rankings` to highlight rank-1, 3 `<PlotlyFig src=...>` charts in grid-cols-2 + full-width scatter).
- **`SarahPage.tsx`**: import BatchCompare, add `{id:"batch", label:"Batch & compare"}` to TOOLS, add conditional render.

### 7. Docs
- `docs/wiki/01-components/sarah-vol-workspace.md`: 5th tab, compare endpoints, `next_earnings_date`/`data_source` columns, batch-screening workflow.
- `docs/wiki/02-platform/api-reference.md`: four new compare endpoints.

## Verification
- `python -m compileall` on touched modules + import smoke test.
- `npm run build` (tsc) in `frontend/`.
- Spot-check the migration is idempotent (run twice).

## UW constraints captured (not pre-built)
The `data_source` column + the contract-freeze comment are the only UW groundwork shipped now. The remaining UW decisions (client as single normalization boundary, IVR via `iv_context()` not UW's field, `ON CONFLICT DO NOTHING` for UW history writes, `uw_quota_ledger`) belong in the UW-client build and are noted in the `vol_db.py`/wiki comments as binding constraints for that future work.