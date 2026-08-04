---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# Data Feeds

**Status:** ✅ live · **Code:** `systems/data_feeds/`

All external data enters through three feed modules. Everything is free-tier
and **delayed**; that ceiling is architectural
([ADR-004](../../design_decisions/ADR-004-scope-deferrals.md)) — this is a
research/paper workstation until the paid-data gates are consciously opened.

> **Learning anchor.** Every conclusion downstream is bounded by the quality
> of what enters here. The system's defense is not pretending the data is
> better than it is — it's propagating `data_warning` fields, confidence
> flags, and staleness gates so degraded inputs are *visible* at the point
> of use.

## `macro_feed.py` — FRED / CFTC / equity / calendar (→ macro.db)

- **FRED**: ~28 series defined in `config.MACRO_SERIES` (rates, curves,
  VIX, HY/IG OAS, inflation incl. PCE + T5YIFR, labor, money, housing, USD,
  oil). `run_fred_pipeline(full=False)` is incremental; the Sunday
  `fred_full` job re-pulls full history to catch revisions. `upsert_series()`
  computes 1m/3m/12m %-changes and rolling 1y/5y z-scores **at write time**.
- **Derived series**: M2 YoY, SPY drawdown-from-252d-peak.
- **CFTC COT** via `cot_reports`: net speculative positioning + z-scores for
  the instruments in `DataParams.cftc_instruments` (weekly, ~3-day lag).
- **Calendar** (`fetch_calendar_data`): FRED release dates for CPI/PCE/NFP/
  claims/retail/industrial-production + the FOMC schedule
  (`DataParams.fomc_schedule` — needs a manual yearly update). Uses FRED's
  REST release-dates endpoint directly (the `fredapi` wrapper lacks it) and
  **rides every FRED pull** (`fred_incremental`/`fred_full`) since 2026-07-17
  — it feeds Sarah's catalyst auto-resolve (U4.3).
- Every fetch is audit-logged to `macro.db:fetch_log`.

## `options_feed.py` — option chains (→ Sarah, runtime only)

`fetch_options_chain(ticker, rate, max_expirations)` pulls the yfinance
chain and enriches every contract: per-expiration forward price,
log-moneyness, two-pass Black-Scholes delta, mid, DTE. Returns
`{spot, div_yield, rate, as_of, data_warning, chains{exp_c/exp_p → DataFrame}}`.

**Chain depth matters** (learned live): the daily run fetches
`SarahParams.chain_max_expirations` (default **24**) expirations per ticker.
Weekly-chain tickers (SPY/QQQ/IWM) list ~3 expirations per week, so the old
6-expiration fetch only reached ~10 DTE — the 30/60/180d tenors were flat
extrapolations and `ts_shape` was stuck on "flat". At 24 the term structure
reaches ~250 DTE with real observations. The memo builder fetches 12 (needs
the expiry nearest your thesis, not the full surface).

Known gaps (audit #1): yfinance IV is unreliable on illiquid strikes; no
zero-bid filtering; flat-vol delta.

## `cboe_feed.py` — VIX complex (→ trading.db)

- **VIX term structure** (9D/30D/3M/6M via `^VIX9D`, `^VIX`, `^VIX3M`,
  `^VIX6M`) returned at runtime; `^VIX9D` availability is flaky; failures
  return None without imputation.
- **VVIX** persisted daily to `trading.db:vvix_daily` (with VIX and the
  VVIX/VIX ratio). **History bootstrapped 2006-03-06 → present** (5,063
  rows) from CBOE's free `VVIX_History.csv` via the `backfill_vvix_history`
  job (U5.1) — which is why VVIX z-scores and the pre-transition monitor
  are reliable from day one. The backfill is idempotent and never
  overwrites live-fetched rows.

## Freshness & staleness

Per-component staleness thresholds live in
`MarcusParams.staleness_thresholds_days` (daily series 3d, weekly 10d;
unemployment level 45d) and surface as chips on the Marcus page. The
master gate is `regime_state.json.written_at`
(12h production / 80h research — both registry parameters). Sarah's analog
search additionally surfaces a macro.db staleness warning (GAP-001) because
its `vix_z1y` feature depends on this feed.

## Disabling a series

Add its internal name to `DataParams.macro_series_disabled` in the registry
(Parameters → Data). *(Feed-side enforcement of the disable list is still
pending; the field exists but `macro_feed` does not yet consult it.)*

## What would upgrade this layer

Polygon starter ($29/mo) for real-time-ish chains (Sarah upgrade U4.1/U4.2);
CBOE historical options EOD for backtest-grade surfaces (U3.3/U5.2 — **the
pre-live-capital gate**); OptionMetrics for institutional-grade history.
Purchase decisions, deliberately out of v1.0.
