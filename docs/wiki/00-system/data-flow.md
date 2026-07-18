# Data Flow — the Daily Cycle

How data moves through the system across one trading day. Times are the
v0.5 schedule (ET); in Phase 6 they become `OpsParams` fields.

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
    options_feed.fetch_options_chain (yfinance, 15–20min delayed)
        → enrich: forward, log-moneyness, delta, mid, dte
    vol_surface.build_term_structure → ATM IV at 30/60/180d
    vol_surface.extract_skew_slice   → 25Δ/10Δ skew, risk reversal
    vol_signals.term_structure_slopes / backward_vrp_proxy / iv_context
    cboe_feed → VIX term structure + VVIX (→ trading.db:vvix_daily)
        │
        ▼
trading.db:vol_signals (1 row/ticker/day)  +  data/outputs/vol_signals.json
```

## On demand — analysis tools (no schedule)

- **Greeks tool**: position → live spot/IV → 7 analytic greeks
  (`systems/sarah/greeks_tool.py`), via GUI or `POST /api/sarah/greeks`.
- **Scenario lab**: greeks result → spot×IV P&L grid, named stress
  scenarios, kill scenario (`scenario_engine.py`).
- **Pre-trade memo**: thesis → 5 market-context panels + structure
  comparison → `data/outputs/pretrade_memo.json` (`pretrade_dashboard.py`).
- **Regime library**: today's surface → nearest historical analogs +
  VVIX pre-transition monitor (`regime_library.py`).

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

## Weekly (Sunday 20:00) 

Full FRED history re-pull (catches revisions) + macro calendar refresh
(45 days ahead). Phase 6 adds the generated weekly review on top.

## Provenance

Every v1.0 job records `param_hashes` (all six components' active parameter
versions) in `trading.db:jobs`, so any output can be traced to the exact
assumptions that produced it.
