# Build Status

**As of 2026-07-06.** Tags: ✅ verified (automated suite green, or pre-v1.0
production use) · 🟢 built, smoke-tested (boots/compiles/responds; no full
interactive pass) · 🟡 partially built · ⬜ planned.

## By plan phase

| Phase | Scope | Status |
|---|---|---|
| 0 | Parameter registry + config facade + engine refactors (classifier, scenario engine) + golden-master harness | ✅ **gauntlet green** — golden master identical, all 47 legacy names resolve, `verify_v1_platform.py` 34/34. See [verification.md](verification.md) |
| 1 | FastAPI :8100 (params/jobs/context/marcus) + job runner + React shell + Marcus workspace | 🟢 boots clean (`/health`, `/api/marcus/summary` 200 against real data, `/docs`); frontend `npm install` + `tsc -b` + `vite build` all succeed. No interactive browser pass yet, no live job-trigger test |
| 2 | Marcus 1.0 analytics (improvement priorities 1–5) + fragility Command Deck + parameter editor with preview | 🟢 covered by the Phase 0 golden master (classification/attribution unchanged) + platform suite; **Dash retirement still pending** (app still exists at :8050) |
| 3 | Sarah data completions + five GUI tools | **partial 🟡**: daily vol run **now works end-to-end** (2026-07-17 — was blocked by an `UnboundLocalError` scoping bug that meant it had *never* completed; fixed) — 5 tickers, VVIX, `vol_signals.json`, `/api/sarah/signals` 200. Vol monitor, greeks tool, scenario lab built. ⬜ remaining: populate `vol_surface`/`skew_by_delta`/`pc_oi_ratio`, U5.0 vix_z1y backfill, U5.1 VVIX bootstrap, U4.3 catalyst calendar, U1.1 vol-cone wiring, GAP-001 staleness warning, GAP-002 roll-adjusted carry, memo builder GUI + `pretrade_memos` table, regime-library GUI |
| 4 | Priya workbench | ⬜ (engine itself ✅ since v0.5). Backend fixes queued: auto trial counting (G4-1), equity trade-log builder (G4-2), `regime_at_verdict` stamp (G4-7 writer side), param-hash → MLflow |
| 5 | Jordan risk layer + RCS bridge | ✅ **`verify_jordan.py` 21/21** (sizing, limits, verdict intake, RCS read-only guarantee, book assembly — one test-parameter bug found and fixed, code was correct). ⬜ remaining: `docs/audit/05_jordan_risk_layer.md`, live smoke vs the real RCS DB (verified suite uses a synthetic RCS DB) |
| 6 | Scheduler v2 + alerting + weekly review + docs refresh (`current_state.md`) + EV research queue | ⬜ (job core exists; legacy `scheduler.py` is still the clock) |

## By component

| Component | Engine | GUI | Notes |
|---|---|---|---|
| Marcus | ✅ verified | 🟢 built | improvements gaps 2 & 6 deferred to v1.1 |
| Sarah | ✅ stages 1–5; daily run verified end-to-end 2026-07-17 | 🟢 built (`/api/sarah/signals` 200) | data completions ⬜ |
| Priya | ✅ stages 1–8 | ⬜ | verified by `verify_priya*.py` in v0.5 |
| Jordan | ✅ verified (offline) | 🟢 built | drawdown check awaits NAV history |
| Alex | 🟢 job core / ✅ legacy clock | 🟢 jobs page | weekly review ⬜ |
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
ADRs 001–004 · audits 01–04 (05 pending) ·
`current_state.md` (v0.5 ground truth — its Priya rows predate Stage 8;
refresh is a Phase 6 item).

## Environment

The venv (`venv/`, Python 3.11.9 via pyenv) had corrupted interpreter
symlinks and stale shebangs from a cloud-provider move (OneDrive →
Nextcloud) — repaired 2026-07-06; see
[verification.md](verification.md#two-environment-bugs-found-and-fixed-during-this-run).
Always invoke `venv/bin/python` explicitly; system `python3` has none of
the project's dependencies.
