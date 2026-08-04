---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# API Reference — FastAPI :8100

**Status:** ✅ all routes live (exercised through the GUI + curl, 2026-07-18) · **Code:** `systems/api/` · Interactive docs at
`http://127.0.0.1:8100/docs` once running. All bodies/responses are plain
JSON; validation errors return **422** with detail; a writer-locked database
returns **503** ("a pipeline job is writing").

## Health

| | |
|---|---|
| `GET /health` | api/registry status, both DB files present, current running job, all six active param hashes |

## Parameters (`routes/params.py`)

| Endpoint | Purpose |
|---|---|
| `GET /api/params` | every component: `{version, hash, payload, specs}` |
| `GET /api/params/{component}` | one component (payload + FIELD_SPECS for form rendering) |
| `PUT /api/params/{component}` | body `{payload: {partial fields}, note}` → validates, saves as new version; response adds `activated_version`, `guarded_fields_changed`, `recompute_suggested` |
| `GET /api/params/{component}/history?limit=` | most-recent-first versions incl. payloads |
| `POST /api/params/{component}/activate/{version}` | rollback (as a new version); body `{note}` optional |
| `GET /api/params-hashes` | flat `{component: hash}` map |

## Jobs (`routes/jobs.py`)

| Endpoint | Purpose |
|---|---|
| `GET /api/jobs/specs` | the runnable job menu (label, description, timeout, writes) |
| `GET /api/jobs?limit=` | recent runs + currently running job id |
| `POST /api/jobs` | body `{name, depends_on?, args?}` → enqueue; 404 on unknown name; a `depends_on` job id must have succeeded or the job fails with a dependency error. `args` is a JSON object handed to the child as `JOB_ARGS_JSON` — e.g. `{"tickers":["AMD","PLTR"]}` runs `sarah_daily_vol` over an ad-hoc batch instead of the daily universe |
| `GET /api/jobs/{id}` | one job: status, timestamps, exit code, log tail, param_hashes, depends_on, args |

## Context contracts (`routes/context.py`)

| Endpoint | Purpose |
|---|---|
| `GET /api/context/regime` | regime_state.json + `age_hours`, `staleness_limit_hours`, `stale` flag |
| `GET /api/context/vol-signals` | vol_signals.json |
| `GET /api/context/research-verdict` | research_verdict.json + age |

## Marcus (`routes/marcus.py`)

Read endpoints never classify; they serve persisted rows.

| Endpoint | Purpose |
|---|---|
| `GET /api/marcus/summary` | latest regime row + color + per-component staleness + attribution + 30d transition probability |
| `GET /api/marcus/history?days=` | regime_history rows |
| `GET /api/marcus/transitions?limit=` | label-change log |
| `GET /api/marcus/calendar?days_ahead=` | upcoming macro events |
| `GET /api/marcus/cot` | latest COT z-scores per instrument |
| `GET /api/marcus/returns` | regime_return_stats table (note when empty) |
| `GET /api/marcus/series/{series_id}?days=` | raw macro series rows |
| `GET /api/marcus/charts/regime-history?days=` | Plotly figure JSON (composite + regime-colored markers) |
| `GET /api/marcus/charts/series/{vix\|hy_spread\|yield_curve_10_2\|breakeven_10y}` | series line + live threshold lines from active params |
| `GET /api/marcus/fragility` | Gap-3 fragility assessment (level, divergence duration/trend, 7d momentum, transition prob) |
| `GET /api/marcus/state-vector?k=` | Gap-1 state vector + geometry + k nearest historical analogues |
| `GET /api/marcus/implications?horizon=1M` | Gap-5 regime return implications + reliability + caveat |
| `GET /api/marcus/interpretations` | Gap-4 vol+credit conditional reads with watch-conditions |
| `POST /api/marcus/preview` | body `{payload: {MarcusParams overrides}}` → classify today under draft vs active, persist=False, with a `changed` diff |

## Sarah (`routes/sarah.py`)

| Endpoint | Purpose |
|---|---|
| `GET /api/sarah/signals` | latest vol_signals row per ticker |
| `GET /api/sarah/signals/{ticker}/history?days=` | IV/RV/VRP/IVR/skew/slope series |
| `GET /api/sarah/charts/iv-history/{ticker}` | IV-vs-RV Plotly figure |
| `GET /api/sarah/charts/term-structure/{ticker}` | latest term-structure curve figure |
| `GET /api/sarah/charts/surface/{ticker}` | IV surface heatmap (strike×DTE, OTM composite) from `vol_surface` |
| `GET /api/sarah/charts/vol-cone/{ticker}?days=` | realized-vol cone figure + table (LIVE yfinance history) |
| `GET /api/sarah/catalysts/{ticker}` | U4.3 catalyst auto-resolve: next earnings + importance-1 macro events → suggested catalyst_type/thesis_days |
| `POST /api/sarah/greeks` | body = position (ticker/flag/strike/expiration/quantity/long_short) → full GreeksTool result (LIVE yfinance) |
| `POST /api/sarah/scenario` | body `{position: <greeks result>, checkpoint, spot_vix?}` → P&L-grid heatmap figure + all stress scenarios + kill scenario, under active SarahParams |
| `POST /api/sarah/memo` | body = thesis (+ optional flow, + optional `rcs_trade_ulid`) → full 5-panel memo + BL density + structure comparison, persisted to `pretrade_memos` (LIVE chain; 15–30s). With `rcs_trade_ulid` every field but `expected_move` is loaded from the stored intake row, and the memo persists carrying the ULID. `expected_move` is validated as an unsigned **decimal fraction**, `0.001 ≤ x ≤ 1.5` — `20` is rejected (percent-vs-decimal) and so is `0`/empty, which would otherwise render a degenerate memo with every candidate strike collapsed onto ATM. `thesis_days ≥ 1` and `max_loss_budget > 0` are enforced for the same empty-field reason |
| `GET /api/sarah/memos?ticker=&limit=` · `GET /api/sarah/memos/{memo_id}` | memo history / one stored memo by `PTM-…` id |
| `GET /api/sarah/rcs-trades?q=&status=&limit=` | **search RCS trades** by ticker, name, or ULID (read-only). Rows carry `leg_count`, `resolved_ticker`, `analysable`, and `intaken` — the "find it without knowing the ULID" path |
| `POST /api/sarah/intake` | body `{rcs_trade_ulid, refresh_vol?}` → reads the RCS trade (read-only), resolves the options-liquid underlier, stores the Class-A/B pre-fills, enqueues the vol pull. Returns `{ticker, job_id, prefilled, needs_user, changed, repull, vol_refresh_queued}`. **Idempotent — calling it again is the re-pull**: refreshes every Class-A/B field not in `user_overrides`, never touches `expected_move`, and by default fetches a chain only if the ticker has no signals for today (`refresh_vol: true` forces it). 422 on an equity trade (no vol pull needed, by design) |
| `GET /api/sarah/intake?limit=` · `GET /api/sarah/intake/{rcs_trade_ulid}` | stored intake rows + `needs_user`, `has_vol_data`, `implied_move_reference`, `user_overrides`, `rcs_synced_at` |
| `PUT /api/sarah/intake/{rcs_trade_ulid}` | the user's Class-C answers `{expected_move?, expected_move_sign?, thesis_days?, catalyst_type?, max_loss_budget?, ticker?, flow_json?}`. Setting a Class-A/B field records it in `user_overrides` so a re-pull won't revert it; setting it to `null` releases it back to RCS |
| `GET /api/sarah/regime-library/analogs?ticker=&n=&exclude_zero_rate_era=&require_regime_match=` | analog search w/ runtime z-enrichment + staleness & thin-history warnings |
| `GET /api/sarah/regime-library/monitor` | VVIX pre-transition monitor (z-scores, ratio, flags, confidence) |
| `GET /api/sarah/regime-library/charts/vvix?days=` | VVIX-vs-VIX dual-axis figure |
| `GET /api/sarah/regime-library/events` · `/events/{id}` | event library list / full record |
| `GET·PUT /api/sarah/regime-library/events-yaml` | read / save the curated YAML (validated; `.bak` kept) |

## Priya (`routes/priya.py`)

| Endpoint | Purpose |
|---|---|
| `GET /api/priya/hypotheses` · `POST /api/priya/hypotheses` | registry list / pre-register (hypothesis, dataset_id, signal_type, rationale) |
| `POST /api/priya/data-audit` | body `{ticker, days?}` → blockers/flags report (LIVE yfinance OHLC) |
| `GET /api/priya/signals` | available signal builders + their params |
| `POST /api/priya/run` | body `{hypothesis_id, ticker, signal_type, params?, sweep?, cost_bps?}` → sweep (trials auto-recorded) → full Stage 5–8 pipeline → verdict or structured `gate_failed` (30–90s) |
| `GET /api/priya/verdict` | current research_verdict.json |
| `GET /api/priya/runs?verdict=&limit=` | MLflow archive (GO / NO_GO failure archive) |
| `GET /api/priya/gates` | current guarded gate values + help text |

## Ops (`routes/ops.py`)

| Endpoint | Purpose |
|---|---|
| `GET /api/ops/alerts?limit=&unacked_only=` · `POST /api/ops/alerts/{id}/ack` | alert feed / acknowledge |
| `GET /api/ops/schedule` | scheduler v2 status: enabled, retry policy, entries, last run per job |
| `GET /api/ops/weekly-reviews` · `/weekly-reviews/{name}` | review archive / one review's markdown |

## Jordan (`routes/jordan.py`)

| Endpoint | Purpose |
|---|---|
| `GET /api/jordan/book` | positions (RCS + manual) + bridge status — no pricing |
| `POST /api/jordan/analyze` | body `{include_stress?}` → LIVE-priced analysis (per-position + net greeks/dollars) + limits evaluation (+ book stress) |
| `POST /api/jordan/positions` | add a manual position |
| `POST /api/jordan/positions/{id}/close` | close a manual position |
| `GET /api/jordan/verdict-intake` | the Priya-handoff checklist (fresh/GO/viable/regime-compatible) |
| `POST /api/jordan/size` | body `{entry, stop, risk_pct?}` → sizing suggestion (NAV-based, limit-capped) |
| `GET /api/jordan/rcs-activity?days=` | journal activity counts (for the weekly review) |

## Conventions

- **Plotly figures** are returned as `{data, layout}` JSON built server-side
  (`fig`-shaped dicts), rendered client-side by react-plotly — chart logic
  stays in Python.
- Live-data endpoints (`/sarah/greeks`, `/sarah/scenario` pricing inputs,
  `/jordan/analyze`) hit yfinance and carry `data_warning`; everything else
  reads persisted state only.
- CORS allows the Vite dev/preview origins; in dev the frontend proxies
  `/api` + `/health` so no CORS is involved at all.
