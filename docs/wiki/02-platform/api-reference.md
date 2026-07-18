# API Reference — FastAPI :8100

**Status:** 🟡 unverified · **Code:** `systems/api/` · Interactive docs at
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
| `POST /api/jobs` | body `{name}` → enqueue; 404 on unknown name |
| `GET /api/jobs/{id}` | one job: status, timestamps, exit code, log tail, param_hashes |

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
| `POST /api/sarah/greeks` | body = position (ticker/flag/strike/expiration/quantity/long_short) → full GreeksTool result (LIVE yfinance) |
| `POST /api/sarah/scenario` | body `{position: <greeks result>, checkpoint, spot_vix?}` → P&L-grid heatmap figure + all stress scenarios + kill scenario, under active SarahParams |

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
