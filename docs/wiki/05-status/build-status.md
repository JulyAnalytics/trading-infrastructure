---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# Build Status

**As of 2026-07-18 — v1.0 complete (phases 0–6).** Tags: ✅ verified (automated suite green, or pre-v1.0
production use) · 🟢 built, smoke-tested (boots/compiles/responds; no full
interactive pass) · 🟡 partially built · ⬜ planned.

## By plan phase

| Phase | Scope | Status |
|---|---|---|
| 0 | Parameter registry + config facade + engine refactors (classifier, scenario engine) + golden-master harness | ✅ **gauntlet green** — golden master identical, all 47 legacy names resolve, `verify_v1_platform.py` 34/34. See [verification.md](verification.md) |
| 1 | FastAPI :8100 (params/jobs/context/marcus) + job runner + React shell + Marcus workspace | 🟢 boots clean (`/health`, `/api/marcus/summary` 200 against real data, `/docs`); frontend `npm install` + `tsc -b` + `vite build` all succeed. No interactive browser pass yet, no live job-trigger test |
| 2 | Marcus 1.0 analytics (improvement priorities 1–5) + fragility Command Deck + parameter editor with preview | 🟢 covered by the Phase 0 golden master (classification/attribution unchanged) + platform suite; Dash app retired 2026-07-18 (Phase 6) |
| 3 | Sarah data completions + five GUI tools | ✅ **complete 2026-07-17** — all five tools live behind tabs on the Sarah page. Data completions: `vol_surface` populated (strike×expiry, IV in vol points), `skew_by_delta_json` (5Δ–50Δ both wings), `pc_oi_ratio_json` (aggregate + per-expiration); daily run now fetches `chain_max_expirations` (registry, default 24) expirations so 30/60/180d tenors are observed, not clamped. U5.1 VVIX bootstrap: `vvix_daily` backfilled 2006-03-06→present (5,063 rows, job `backfill_vvix_history`; 2020 spike z=13.4 check passed) — pre-transition monitor is `reliable` day one. U4.3 catalyst resolver (`/api/sarah/catalysts/{t}`) over `macro_calendar` + yfinance earnings — `fetch_calendar_data` was never scheduled and its fredapi call didn't exist; now REST-based and wired into `fred_incremental`. U1.1 vol cones + IV-surface heatmap in the vol monitor. GAP-001 macro.db staleness surfaced in analog/monitor responses; GAP-002 roll-adjusted carry in Panel 1. Memo builder persists to `pretrade_memos` with stable IDs (`PTM-YYYYMMDD-TICKER-NNN`). Regime library GUI: analog search with macro filters (runtime vix_z1y/vvix_z1y enrichment), monitor, event browser + validated YAML editor (.bak kept). **U5.0 reconciled as moot**: `vix_z1y` is runtime-computed from macro.db (VIX history 1990→present, 9,213 rows — covers any analog window); there is no NULL column to backfill |
| 4 | Priya workbench | ✅ **complete 2026-07-17/18** — backend: G4-1 closed (sweeps auto-record trials via `parameter_sweep(dataset_id=…)`; pipeline auto-resolves `n_trials` from the registry), G4-2 closed (`VectorizedBacktester.build_trade_log()` → ImplementationShortfall, reconciles with strategy returns), G4-7 writer closed (`research_verdict.json` gains `regime_at_verdict`/`regime_as_of`/`staleness_guidance` — CLAUDE.md contract updated), registry hashes stamped into every MLflow run. `verify_priya*.py` both green. Workbench GUI (`/api/priya/*` + PriyaPage): hypothesis registration, data-audit runner, configurator (sweep → full Stage 5-8), CPCV/DSR/overfit panels, verdict view, failure-archive browser, gates display (edit via Params). First live workbench run: SPY momentum sweep — **PBO gate correctly stopped it** (PBO 0.467 ≥ 0.05), 4 trials recorded, structured `gate_failed` response |
| 5 | Jordan risk layer + RCS bridge | ✅ **closed 2026-07-17** — `verify_jordan.py` 21/21 AND live smoke vs the **real** `research.db`: bridge available, read-only guarantee held at driver level, all `/api/jordan/*` endpoints live. Two live-only bugs found+fixed: `reviews_completed` queried nonexistent `review.created_at` (→ `closed_at`); verdict intake crashed on tz-aware timestamps (real verdict now reports true 2,463h age). `docs/audit/05_jordan_risk_layer.md` written (audit-as-built, grounded in the Okafor persona + Artzner/BP2009/Hull/Natenberg/Thorp distillations; open gaps ranked). Drawdown check stays declared-not-evaluated until the Phase 6 NAV series exists; RCS journal is empty so the trade→book loop awaits the first real journaled trade |
| 6 | Scheduler v2 + alerting + weekly review + docs refresh (`current_state.md`) | ✅ **complete 2026-07-18** — scheduler v2 (`systems/orchestration/scheduler_v2.py`) runs in the API process: OpsParams times read live, weekday fred→marcus→snapshot chain, morning sarah→jordan_daily_check chain (Sarah blocks on Marcus success via `depends_on` when the regime is stale), Sunday `fred_full`, Friday `weekly_review`; catch-up-on-start with the jobs table as the double-run guard; OpsParams retries; master switch `ops.scheduler_enabled`. Alerting: `alerts` table + macOS osascript + Jobs-page feed with ack; **verified live** — a forced dependency failure was refused by the worker and raised a feed alert. `jordan_daily_check` prices the book daily and alerts on limit breaches. Weekly review generator → `reports/weekly/*.{md,pdf}` + archive browser in the GUI. Legacy `scheduler.py` and the :8050 Dash app retired (deprecation banners; Dash figure builders kept for the snapshot PDF). `current_state.md` rewritten (April snapshot archived). EV research queue: deferred (needs live outcome history to rank against) |

## By component

| Component | Engine | GUI | Notes |
|---|---|---|---|
| Marcus | ✅ verified | 🟢 built | improvements gaps 2 & 6 deferred to v1.1 |
| Sarah | ✅ stages 1–5; daily run + data completions verified end-to-end 2026-07-17. **RCS trade intake seam ✅ 2026-08-03** — `entity_events` poll → underlier map → Class-A/B pre-fills → coalesced ad-hoc vol batch; only `expected_move` is ever asked. Brought job `args`/`JOB_ARGS_JSON` and `run_daily_vol(tickers=…)` batch mode with it. Verified live end-to-end on the AAOI earnings trade (activation read → AAOI vol pull → `PTM-20260803-AAOI-001` persisted with the trade ULID); `scripts/verify_sarah_intake.py` 70/70 | 🟢 five tools built (vol monitor · greeks/scenarios · memo builder + RCS intake panel · regime library) | analog pool grows organically; CBOE historical EOD (U5.2) stays the pre-live gate. Intake's position surfaces stay empty until RCS captures `trade_option_legs` — that capture is the upstream gate |
| Priya | ✅ stages 1–8 + G4 fixes | 🟢 workbench built (7 tools on PriyaPage) | `verify_priya*.py` green post-fixes; first live run gated correctly |
| Jordan | ✅ verified (offline) | 🟢 built | drawdown check awaits NAV history |
| Alex | ✅ scheduler v2 + retries + alerts | 🟢 jobs page (alerts feed, schedule, weekly reviews) | weekly review generator live; EV queue deferred |
| Kai | ⬜ **v1.1** | — | manual execution + RCS journaling in v1.0 |
| RCS journal | ✅ (separate app) | ✅ (its own) | bridge read-only guarantee verified (`verify_jordan.py`) |

## Deliberately out of v1.0 ([ADR-004](../../design_decisions/ADR-004-scope-deferrals.md))

IBKR/paper execution · live-capital deployment (hard-gated on CBOE
historical options data, upgrade items U3.3/U5.2) · Marcus
regime-conditional weights & forward scenario layer · paid data tiers ·
email/Slack alerting.

## Key docs

Plan of record: `~/.claude/plans/can-you-review-the-logical-hickey.md` ·
[v1_architecture.md](../../architecture/v1_architecture.md) ·
ADRs 001–004 · audits 01–05 (complete) ·
[current_state.md](../../architecture/current_state.md) (refreshed
2026-07-18; April snapshot archived alongside).

## Environment

The venv (`venv/`, Python 3.11.9 via pyenv) had corrupted interpreter
symlinks and stale shebangs from a cloud-provider move (OneDrive →
Nextcloud) — repaired 2026-07-06; see
[verification.md](verification.md#two-environment-bugs-found-and-fixed-during-this-run).
Always invoke `venv/bin/python` explicitly; system `python3` has none of
the project's dependencies.
