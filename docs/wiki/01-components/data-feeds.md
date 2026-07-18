# Data Feeds

**Status:** ✅ live (v0.5) · **Code:** `systems/data_feeds/`

All external data enters through three feed modules. Everything is free-tier
and **delayed**; that ceiling is architectural
([ADR-004](../../design_decisions/ADR-004-scope-deferrals.md)).

## `macro_feed.py` — FRED / CFTC / equity (→ macro.db)

- **FRED**: ~28 series defined in `config.MACRO_SERIES` (rates, curves,
  VIX, HY/IG OAS, inflation incl. PCE + T5YIFR, labor, money, housing, USD,
  oil, gold). `run_fred_pipeline(full=False)` is incremental; the Sunday
  job re-pulls full history to catch revisions. `upsert_series()` computes
  1m/3m/12m %-changes and rolling 1y/5y z-scores **at write time**.
- **Derived series**: M2 YoY, SPY drawdown-from-252d-peak.
- **CFTC COT** via `cot_reports`: net speculative positioning + z-scores for
  the instruments in `DataParams.cftc_instruments` (weekly, ~3-day lag).
- **Calendar**: FRED release dates + the FOMC schedule
  (`DataParams.fomc_schedule` — needs a manual yearly update).
- **Equity**: SPY history via yfinance.
- Every fetch is audit-logged to `macro.db:fetch_log`.

## `options_feed.py` — option chains (→ Sarah, runtime only)

`fetch_options_chain(ticker, rate, max_expirations=6)` pulls the yfinance
chain and enriches every contract: per-expiration forward price,
log-moneyness, two-pass Black-Scholes delta, mid, DTE. Returns
`{spot, div_yield, rate, as_of, data_warning, chains{exp_c/exp_p → DataFrame}}`.
Known gaps (audit #1): yfinance IV is unreliable on illiquid strikes; no
zero-bid filtering; flat-vol delta.

## `cboe_feed.py` — VIX complex (→ trading.db)

VIX term structure (9D/30D/3M/6M via `^VIX9D`, `^VIX`, `^VIX3M`, `^VIX6M`)
returned at runtime; **VVIX** persisted daily to `trading.db:vvix_daily`
(with VIX and the VVIX/VIX ratio). `^VIX9D` availability is flaky; failures
return None without imputation.

## Freshness & staleness

Per-component staleness thresholds live in
`MarcusParams.staleness_thresholds_days` (daily series 3d, weekly 10d;
unemployment level 45d) and surface as chips on the Marcus page. The
master gate is `regime_state.json.written_at`
(12h production / 80h research — both registry parameters).

## Disabling a series

Add its internal name to `DataParams.macro_series_disabled` in the registry
(Parameters → Data). *(Feed-side enforcement of the disable list is wired in
Phase 6; today the field exists but `macro_feed` does not yet consult it.)*

## What would upgrade this layer

Polygon starter ($29/mo) for real-time-ish chains (Sarah upgrade U4.1/U4.2);
CBOE historical options EOD for backtest-grade surfaces (U3.3/U5.2 — the
pre-live-capital gate); OptionMetrics for institutional-grade history.
Purchase decisions, deliberately out of v1.0.
