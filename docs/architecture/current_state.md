# Leopold — Ground Truth Architecture
**Refreshed:** 2026-07-18 (v1.0 workstation build — Phases 0–6 of the v1.0 plan complete)
**Previous snapshot:** `current_state_2026-04-06.md.bak` (pre-v1.0 — kept for history)
**Authoritative detail:** `docs/wiki/Home.md` (schemas, per-component docs) ·
`docs/wiki/05-status/build-status.md` (live status + verification record) ·
`docs/audit/01–05` (capability maps + output literacy) · ADRs 001–004

---

## What is running

One FastAPI service layer (`systems/api`, **:8100**) over the engines, a React
workstation (`frontend/`, **:5173**), a versioned parameter registry
(`systems/params` — every tunable, GUI-editable, hash-stamped onto every run),
and a single-writer job system (`systems/orchestration`) with scheduler v2,
retries, dependency enforcement, and an alert feed (+ macOS notifications).

```
frontend (Vite+React+TS, react-plotly)  :5173
  Command Deck · Marcus · Sarah (5 tools) · Priya workbench · Jordan risk
  · Parameters · Jobs & Health (alerts, scheduler, weekly reviews)
        │ REST + job polling
systems/api (FastAPI)  :8100
  routes: context marcus sarah priya jordan ops params jobs
systems/orchestration
  JobManager (subprocess-per-job, one writer at a time, OpsParams retries,
  depends_on enforcement) + scheduler_v2 (in-process loop, catch-up guard)
  + alerts (trading.db feed + osascript)
engines
  signals (Marcus) · sarah · backtest (Priya) · risk (Jordan) · data_feeds
  · reports (snapshot PDF, weekly review)
storage
  macro.db (FRED/derived/regime) · trading.db (vol, memos, jobs, alerts,
  params, jordan book, hypothesis registry) · MLflow (research runs)
  · RCS research.db (READ-ONLY bridge, ADR-003)
```

## v1.0 phase status (plan of record: docs/architecture/v1_architecture.md)

| Phase | Delivered | Verified |
|---|---|---|
| 0 | Parameter registry + config facade + golden master | gauntlet green (2026-07-06) |
| 1 | API + jobs + React shell + Marcus workspace | `verify_v1_platform.py` 34/34 |
| 2 | Param editing + Marcus 1.0 analytics + command deck | golden master + platform suite |
| 3 | Sarah: data completions + five tools (vol monitor w/ surface+cones, greeks/scenarios, memo builder → `pretrade_memos`, regime library w/ VVIX 2006+ backfill) | end-to-end 2026-07-17 |
| 4 | Priya workbench + G4-1/2/7 fixes + registry hashes → MLflow | `verify_priya*.py` green; first live run correctly stopped by the PBO gate |
| 5 | Jordan risk layer + RCS bridge | `verify_jordan.py` 21/21 + live RCS smoke; audit #5 written |
| 6 | Scheduler v2, alerting, weekly review, Dash retirement, this refresh | see build-status Phase 6 row |

## Persona → code map (v0.5 "six analysts" → v1.0 desk)

| Persona | Layer | Engine | Workspace |
|---|---|---|---|
| Marcus | macro regime | `systems/signals/` | /marcus |
| Sarah | vol/options | `systems/sarah/` + `research/signals/` | /sarah (5 tools) |
| Priya | research validation | `systems/backtest/` (stages 1–8) | /priya (workbench) |
| Jordan | risk | `systems/risk/` | /jordan |
| Alex | operations | `systems/orchestration/` + `systems/reports/` | /jobs |
| Kai | execution | **v1.1** (ADR-004) — manual execution + RCS journaling in v1.0 | — |
| Sam | ops/P&L attribution | not built (post-v1.0; NAV series lands with weekly-review history) | — |

## Standing constraints

- **Research/paper posture.** yfinance ceiling by design; every consumer
  carries `data_warning`. Pre-live-capital hard gate: CBOE historical options
  EOD (U3.3/U5.2) — deliberately not purchased.
- **Single writer.** Pipeline writes only via job subprocesses; API reads are
  read-only short-lived; small metadata writes (memos, book, alerts, registry)
  are short-lived writes with retry.
- **Registry contract.** Code never reads tunables from constants —
  `get_params("<component>")`; every run stamps `all_active_hashes()`.
- **RCS is read-only** from this repo (`mode=ro`, ADR-003).
- **Known debts** (tracked in build-status / audit #5): drawdown check awaits
  NAV history; liquidity limits await bid/ask data; Marcus gaps 2 & 6 and
  regime-contingent risk limits deferred; `divergence_onset_date` /
  `divergence_severity_trend` still computed on the fly, not persisted.
