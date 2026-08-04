---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# Data Flow — the Daily Cycle

How data moves through the system across one trading day. All times are
**OpsParams registry fields**, read live by scheduler v2 — edit them on the
Parameters page and they apply within a minute. Every chained step is
dependency-enforced: a failed prerequisite blocks its dependents (and
alerts) instead of letting them run on stale data.

## Evening (18:05 weekdays) — Marcus refresh

```
FRED API ─┐
CFTC COT ─┼─► macro_feed.py ─► macro.db (macro_series, cot_positioning,
yfinance ─┘        │                     fetch_log, macro_calendar)
                   ▼
        regime_classifier.classify(persist=True)
                   │  reads latest values + z-scores per series
                   │  scores 6 components → weighted composite → regime label
                   ▼
        macro.db:regime_history  +  data/outputs/regime_state.json  ◄── THE GATE
                   ▼
        snapshot_generator (18:15) → data/snapshots/macro_*.pdf
```

`regime_state.json` carries `written_at`; every downstream run checks its age
(12h production limit; 80h research limit for weekend spans — both now
registry parameters).

## Morning (08:00 weekdays) — Sarah refresh

```
regime_state.json (fresh? else HARD FAIL)
        │
        ▼
daily_vol_run.py — for each ticker in SarahParams.vol_tickers:
    options_feed.fetch_options_chain (yfinance, 15–20min delayed,
        chain_max_expirations=24 → term structure out to ~250 DTE)
        → enrich: forward, log-moneyness, delta, mid, dte
    vol_surface.build_term_structure → ATM IV per listed expiration
    vol_surface.extract_skew_slice   → 25Δ/10Δ skew + full 5–50Δ grid
    vol_surface.compute_pc_oi_ratios → put/call open interest
    vol_signals.term_structure_slopes / backward_vrp_proxy / iv_context
    cboe_feed → VIX term structure + VVIX (→ trading.db:vvix_daily)
        │
        ▼
trading.db:vol_signals (1 row/ticker/day) + vol_surface (strike×expiry)
        +  data/outputs/vol_signals.json
        │ depends_on success
        ▼
jordan_daily_check — price the book, evaluate limits, alert on breach
```

## On demand — analysis tools (no schedule)

- **Greeks tool**: position → live spot/IV → 7 analytic greeks
  (`systems/sarah/greeks_tool.py`), via GUI or `POST /api/sarah/greeks`.
- **Scenario lab**: greeks result → spot×IV P&L grid, named stress
  scenarios, kill scenario (`scenario_engine.py`).
- **Pre-trade memo**: thesis (catalyst auto-resolved from `macro_calendar` +
  earnings) → 5 panels + BL density + structure comparison → persisted to
  `trading.db:pretrade_memos` with a stable `PTM-…` ID + the
  `pretrade_memo.json` contract (`pretrade_dashboard.py`).
- **Regime library**: today's surface → nearest historical analogs
  (runtime vix_z1y/vvix_z1y enrichment from macro.db + the 2006+ VVIX
  backfill) + VVIX pre-transition monitor + event browser
  (`regime_library.py`).

## On demand — research (Priya)

```
hypothesis registered (trading.db:hypothesis_registry)  ── Gate 1
        → data audit → features/labels → backtest (vectorized or options MC)
        → CPCV path distribution → PBO/overfit diagnostics
        → Lo/PSR/DSR Sharpe pipeline → haircut → 13 gates
        → MLflow run (data/mlruns) + data/outputs/research_verdict.json ── Jordan contract
```

## On demand — risk (Jordan)

```
RCS journal (read-only) ─► positions book ─► live greeks (yfinance)
manual positions        ─┘                       │
                                                 ▼
                    limits check (JordanParams) + book stress + net exposure
research_verdict.json + regime_state.json ─► verdict intake ─► sizing suggestion
```

The human then executes at the broker and journals the fill in the RCS —
which flows back into Jordan's book on the next refresh. That loop is the
system's core feedback circuit.

## Sub-daily — RCS trade intake (Sarah)

The one automated trigger that runs *from* the journal rather than on a clock:

```
RCS: trade idea→active (or created as an idea)
  └─ entity_events ──(read-only, mode=ro)──► sarah_intake_poll
        every sarah.intake_poll_minutes (5), every day of the week
        │  option trades only; ticker ← sarah.underlier_map
        ├─► trading.db: sarah_trade_inputs  (Class-B position/budget from RCS,
        │      Class-A catalyst from the resolver; expected_move left NULL)
        └─► one coalesced sarah_daily_vol job with args.tickers
                │
                ▼
   vol_signals + vol_surface for that ticker
        ├─► Phase A: vol monitor + greeks/scenario lab — live, zero input
        └─► Phase B: pre-trade memo — waits only for your expected_move,
                     then persists carrying rcs_trade_ulid
```

Nothing is written back to RCS at any point (ADR-003); the watermark that
makes the poll idempotent lives on the trading side.

## Weekly

- **Sunday** (`weekly_refresh_time`): `fred_full` — full FRED history
  re-pull (catches revisions) + macro calendar refresh (45 days ahead).
- **Friday** (`weekly_review_time`): `weekly_review` — regime week + vol
  summary + research runs + risk flags + journal activity →
  `reports/weekly/*.md/pdf`, browsable on Jobs & Health
  ([workflow](../04-workflows/weekly-operations.md)).

## Provenance

Every v1.0 job records `param_hashes` (all six components' active parameter
versions) in `trading.db:jobs`, so any output can be traced to the exact
assumptions that produced it.
