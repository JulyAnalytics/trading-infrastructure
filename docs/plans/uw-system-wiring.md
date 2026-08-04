# UW Backfill — Trading-System Wiring Scope

Status: **plan** (not implemented)
Date: 2026-08-02
Companion to: `docs/plans/uw-iv-backfill.md` (data capture — what/how/cost) and
`docs/plans/uw-refresh-capabilities.md` (what the data enables).
Scope: what must be wired in `trading-infrastructure` **to consume** the captured
data. Data capture alone is covered by the backfill plan; this doc scopes the
consumption side, including the Jordan (`systems/risk/`) and Priya
(`systems/backtest/`) components.

## 1. What activates automatically (no wiring)

| Capability | Mechanism |
|---|---|
| IVR/IVP confidence → `standard` | daily run recomputes today's row via `_get_iv_history()` over the now-deep `vol_signals` |
| Analog search unlocks | `analog_search()` (`systems/sarah/regime_library.py:267`) reads `vol_signals` per ticker; 120d gate clears itself |
| Pre-trade panels per ticker | `pretrade_dashboard.py` reads latest `vol_signals` row for any ticker |
| `/api/context/vol-signals` | output file — unchanged shape |
| GreeksTool IV fallback improves | `greeks_tool.py:220-240` single-latest-row `atm_iv_30d`/`skew_25d_rr` reads now resolve to real data for any ticker |
| Priya tables readable | `vol_signals`/`vol_surface` in trading.db — nothing reads them yet (see §5) |

## 2. Sarah consumption — the Phase-A screens (highest ROI)

Screens from `uw-refresh-capabilities.md` §A–B. **Unspecified in the capture plan —
this is the wiring.**

| Screen | Data (plan phase) | Wiring |
|---|---|---|
| IVR league table + zone crossings | Phase 1 (wide) | new route(s) in `systems/api/routes/sarah.py` (e.g. `/api/sarah/screens/ivr-league?limit=&min_ivr=&zone=`) + daily `screens.json` output artifact in `data/outputs/` (pattern: `vol_signals.json`) |
| VRP screen (IV − RV) | Phase 1 | same route family; needs GARCH RV forecast (see §5) for the forecast side |
| TS-shape screen (backwardation / steep contango) | month (SP500 TS) | same |
| Skew screen (richest 25Δ RR) | month (skew-wide) | same |
| Event screen (earnings IVR buildup/crush) | Phase 1 + earnings dates | needs a catalyst/earnings-date source (RCS `catalyst_types` or UW earnings endpoint) |
| Market-wide IVR breadth | Phase 1 (wide) | see §3 — shared with Marcus |

Thresholds (`IVR > 80/20`, event premium `> 2 vpts`, DTE 45) → `SarahParams`
fields + `FIELD_SPECS` (registry-editable, GUI pattern exists).
Frontend: extend `pretrade_dashboard` or add a CommandDeck panel / new page.
Output contract: add screen rows to `docs/wiki/03-contracts/output-contracts.md`.

## 3. Marcus wiring — market-wide IVR breadth

Marcus consumes VIX level only (`regime_classifier.py` reads `macro_series`; no
options-implied input). New input:

- A daily `ivr_breadth` series (e.g. % names with IVR > 80, % < 20, cross-sectional
  IVR median) written into `macro.db` `macro_series` by the UW refresh job
  (extension of `scripts/uw_daily_refresh.py` or a small post-step).
- New `MarcusParams` fields for thresholds/breadth weighting; optional regime
  classifier input or a standalone "breadth oscillator" panel alongside the
  VIX/HY/curve inputs.
- Consumer of the same series: Jordan (see §4), Marcus, and the Stage 5
  pre-transition monitor generalization.

## 4. Jordan wiring (`systems/risk/`)

**Current state** (verified): Jordan touches exactly four data sources — RCS
trades (read-only `rcs_bridge.py`), manual `jordan_positions`, yfinance pricing
(`GreeksTool`), FRED DGS3MO. The only vol_signals touch is the single-latest-row
`atm_iv_30d`/`skew_25d_rr` fallback in `greeks_tool.py`. No IVR/IVP/VRP reads, no
gamma limit, no margin utilization, no bucketed greeks, no correlation, no
drawdown evaluation (declared-not-evaluated, needs NAV history), **Kelly
deliberately rejected** (fixed-fractional sizing — do not propose Kelly).
Wiki status: closed 2026-07-17, open gaps ranked in
`docs/audit/05_jordan_risk_layer.md:424-435`.

Wiring opportunities (all net-new):

| # | Item | Where | Data needed |
|---|---|---|---|
| J1 | **Position vol-context block** — per-position IVR/IVP/confidence, skew, VRP, TS shape, ivr_regime_bias attached to `analyze_book()` output | `book.py` (new small module `systems/risk/vol_context.py`), surfaced in `/api/jordan/analyze` + JordanPage | Phase 1 |
| J2 | **Vol-aware limits** — the #2 open gap (regime-contingent tightening) becomes buildable: tighten `max_net_vega_pct` / add per-position IVR bands when market-wide breadth is elevated; volga-aware vega (limit evaluated at stressed IV, not current) | `limits.py` + `JordanParams` fields + `FIELD_SPECS` | Phase 1 (breadth), month (percentiles) |
| J3 | **Stress enhancement** — ScenarioEngine currently uses generic ±vol-pt shifts; with 2y history, stress scenarios can apply the *actual* IV/RV changes of each underlying during named events (2018 Q4, March 2020…) from the dataset instead of endpoint approximations | `stress.py` + `SarahParams.stress_scenarios` | month (2y) |
| J4 | **Correlation/crowding monitor** — open gap #5 ("matters once multiple strategies run"): per-underlying RV/IV series → correlation matrix among held names → crowding flags; PSD-hygiene per Hull §7.4 | new module `systems/risk/correlation.py` + route | month (2y) |
| J5 | **Margin/funding-stress flag** — market-wide IVR breadth as a standing flag (B&P margin-escalation signal) in the daily check banner | `run_job.py:_jordan_daily_check` (extends to read breadth) | Phase 1 (breadth) |
| J6 | **NAV persistence** — daily analyzed-book NAV row persisted so the declared drawdown tiers (#1 gap) can eventually evaluate; IV-independent but sequenced with J2 | `book.py`/daily check + trading.db table | none (separate) |

Not wired here: Kelly (deliberately rejected in this codebase), liquidity checks
(gated on paid bid/ask — U4.1, out of scope), bucketed greeks (needs surface —
partially fed by Phase 2 surface data, defer).

## 5. Priya wiring (`systems/backtest/`)

**Current state** (verified): the Stage 0–8 engine is fully built and audited, but
signals are only `momentum`/`mean_reversion` on yfinance closes
(`routes/priya.py:110-116`). **Nothing in `systems/backtest/` reads
`vol_signals`/`vol_surface`.** No VRP/IVR/skew signal modules exist anywhere on
the Priya side (`research/signals/` functions are Sarah-only, take plain Python
inputs, never touch DuckDB). No matched-maturity VRP (the only occurrence is the
explicit "NOT matched-maturity VRP" note in `backward_vrp_proxy`), no GARCH,
`VolCone` exists but is only fed user-provided closes, no analog-conditioned or
stress-path backtests. The engine contract for signals:
`signal_func(returns, **params) -> pd.Series` into
`VectorizedBacktester.parameter_sweep` (`vectorized_engine.py:280`).

Wiring (the "carry-forward" signal modules from the persona spec — VRP, IV rank,
skew):

| # | Item | Where | Data needed |
|---|---|---|---|
| P1 | **Vol data loader** — read `vol_signals`/`vol_surface` per ticker into backtest-shaped DataFrames (ticker, date, atm_iv_30d, iv_rank, iv_percentile, skew_25d_rr, ts_*, rv_21d, close), with `DataAuditReport.run_full_audit` hooks | new `systems/backtest/vol_data.py` | Phase 1 |
| P2 | **IVR signal** — e.g. IVR z-score / zone-crossing long-short signal shaped for the engine | new `systems/backtest/signals/` (or `research/strategies/`) | Phase 1 (2y for valid distribution) |
| P3 | **VRP signal** — backward proxy first (`backward_vrp_proxy`), upgraded to matched-maturity once P4 lands | same | Phase 1; P4 needs month |
| P4 | **Matched-maturity VRP module** — IV(t) vs realized(t→t+30) from the 2y dataset (U1.3 "activates automatically" — no machinery exists; must be built) | new `research/signals/matched_vrp.py` | month (2y) |
| P5 | **GARCH(1,1) RV forecast** — long-run vol V_L per name; the forecast side of VRP screens and the mean-reversion anchor (Hull §7.3); no implementation exists | new `research/signals/garch.py` (or in `vol_estimators.py`) | Phase 1 |
| P6 | **Skew signal** — RR percentile / tail-steepness signal | signals package | month (skew-wide) |
| P7 | **TS-shape signal** — slope percentile / shape-state signal | signals package | month (SP500 TS) |
| P8 | **Workbench extension** — new `SIGNALS` entries + a run path that sources vol data from trading.db instead of yfinance closes | `routes/priya.py` (`/api/priya/signals`, `/api/priya/run`) | P1–P7 |
| P9 | **Vol-cone wiring** — `VolCone` fed from the dataset's RV/IV history (params `vol_cone_windows`/`vol_cone_percentiles` already exist) | `vol_estimators.py` caller | Phase 1 |
| P10 | **Trade-journal feedback** — RCS trades joined with entry-day vol context ("did I enter at high IVR?") as a Priya analysis + report | extends `trade_context_report.py` pattern | Phase 1 |
| P11 | **Analog-conditioned / stress-path backtests** — conditioning on Sarah's analog dates and reconstructed historical stress paths | research feature; needs J3-adjacent surface tooling | month (2y surface) |

MLflow/experiment tracking, hypothesis registry, CPCV/PBO/DSR gates, Jordan
verdict contract: all work automatically once runs flow through `run_equity`.

## 6. RCS intake enrichment (workflow)

`trade_context_report.py` (capture plan, read-only bonus) becomes a workflow:
for any RCS thesis/trade, an advisory endpoint returns the underlying's IV
context (IVR/IVP, TS shape, skew, VRP, expected move, Natenberg breakeven check)
at entry. Wiring: read-only read of `research.db` via `rcs_bridge` patterns
(ADR-003 — trading-infrastructure never writes research.db), a route under
`/api/sarah/` or `/api/jordan/`, surfaced in CommandDeck. Needs the Natenberg
breakeven computation (new small module) — capability doc item 13.

## 7. Contracts & docs updates

- `docs/wiki/03-contracts/output-contracts.md` — new screen outputs (`screens.json`
  fields), new routes, breadth series contract.
- `docs/wiki/02-platform/databases.md` — `ivr_breadth` series (macro.db),
  NAV-history table (J6).
- `docs/wiki/02-platform/parameter-registry.md` — new params: Sarah screen
  thresholds, Marcus breadth fields, Jordan J2 fields, Priya signal params.
- `docs/wiki/01-components/{jordan-risk-layer,priya-research-engine,marcus-macro-regime,data-feeds}.md` — capability + status updates.
- Frontend: JordanPage (J1 context block, J2 flags), new screens page/panels,
  CommandDeck (enrichment).

## 8. Delivery order (dependency-aware)

1. **Phase 1 of capture lands** → auto-activations happen for free.
2. **Screens §2** (league table + zone crossings + event screen) — pure consumers
   of wide data; the highest-ROI first build; needs `screens.json` + routes +
   thresholds params.
3. **Jordan J1 + J5** (vol-context block, breadth flag) — small, read-only,
   immediate value in the daily check.
4. **Priya P1–P3 + P8** (loader + IVR/VRP signals + workbench) — the strategic
   "carry-forward" modules; engine already supports them, only the adapters are
   missing.
5. **Marcus breadth §3** + **Jordan J2** — second-order, build on the breadth
   series.
6. **Month-phase data (2y)** → P4 matched VRP, P5 GARCH, P6/P7 signals, J3 stress
   paths, J4 correlation, P11 analog-conditioned backtests.
7. **Docs/contracts §7** land incrementally with each item.

## 9. Open scope decisions

- Which screens ship first (league + zones + event are the capabilities-doc
  recommendation); whether screens are daily artifacts vs on-demand routes.
- Earnings-date source for the event screen (RCS catalysts vs UW earnings
  endpoint).
- Marcus breadth as classifier input vs standalone panel.
- Whether J6 (NAV persistence) is in scope now or stays with weekly-review.
- Which Priya signals get hypotheses registered first (IVR vs VRP — the persona
  spec carries all three forward).
