# Sarah — Vol Surface & Pre-Trade Intelligence

**Status:** stages 1–5 engines ✅ complete (v0.5) · workspace GUI 🟡 unverified · data completions ⬜ Phase 3
**Code:** `systems/sarah/` + `research/signals/` + `systems/data_feeds/{options,cboe}_feed.py`
**GUI:** workstation *Sarah* page · **Params:** registry component `sarah`

## Job

Measure what the options market is pricing — per ticker, daily — and give
the trader position-level tools: greeks, scenario P&L, structure comparison,
and historical analogs. Sarah **describes**; she never recommends direction.

## The five stages

### Stage 1 — Daily vol pipeline (`daily_vol_run.py`) ✅
Runs weekday mornings for each `SarahParams.vol_tickers` (SPY, QQQ, IWM,
XLE, GLD by default). Hard-fails if `regime_state.json` is stale. Per ticker:
fetch chain (yfinance, 15–20min delayed) → enrich (forward price,
log-moneyness, two-pass delta, mid, DTE) → ATM IV term structure (30/60/180d)
→ 25Δ/10Δ skew slice → IV rank/percentile vs stored history (confidence-
flagged below 252 days) → backward VRP proxy (30d IV − 21d RV, a documented
tenor mismatch) → term-structure shape (6-state enum). Writes
`trading.db:vol_signals` + [`vol_signals.json`](../03-contracts/output-contracts.md#vol_signalsjson).
Also fetches the VIX term structure and persists VVIX (`vvix_daily`).

*Phase 3 gap:* the `vol_surface` strike×expiry table, `skew_by_delta_json`,
and `pc_oi_ratio_json` are schema'd but not yet populated.

### Stage 2 — Greeks tool (`greeks_tool.py`) ✅
One position (ticker/flag/strike/expiry/qty/side) → seven analytic
Black-Scholes greeks (delta, gamma, theta, vega, vanna, charm, vomma), raw
and position-scaled, with an IV source ladder (live chain → stored ATM IV →
18% fallback, always warned), a skew-based BS-reliability flag, and a
plain-English interpretation block. `aggregate_portfolio()` nets greeks
across positions and flags vanna/charm/vomma concentrations — Jordan reuses
this for the book.

### Stage 3 — Scenario engine (`scenario_engine.py`) ✅ (params 🟡)
- **P&L grid**: spot (±30%, step 2.5%) × IV (±25 vpts) at 0/25/50/75% of
  DTE elapsed; widens automatically to ±40%/±35vpts when VIX > 25. All grid
  geometry is `SarahParams`.
- **Named stress scenarios**: the six-event library (2018 Q4, March 2020,
  Aug 2015, Volmageddon, 2022 rates, 2011 euro) — now **registry data you can
  edit/extend in the GUI**. Flat and skew-amplified P&L (deeper-OTM puts get
  amplified vol shocks, capped 1.8×). Endpoint approximation, absolute vol
  points.
- **Kill scenario**: spot flat + IV −8 vpts by day 30 (both parameters) —
  the "thesis simply fails" loss.
- **Structure comparison**: entry cost, P&L at ±expected-move, and
  expiration break-evens across candidate structures.

### Stage 4 — Pre-trade dashboard (`pretrade_dashboard.py`) ✅ engine · GUI ⬜ Phase 3
`TradeThesisInput` (ticker, expected move, thesis days, catalyst type, max
loss budget) → five panels: vol level (cost burden incl. monthly carry),
term structure (tenor alignment), skew (wing cost), flow (structured manual
observations), and a Breeden-Litzenberger risk-neutral density; plus a
structure comparison and the
[`pretrade_memo.json`](../03-contracts/output-contracts.md#pretrade_memojson)
contract. Phase 3 adds persistence (`pretrade_memos` table) + the memo-builder GUI.

### Stage 5 — Regime library (`regime_library.py`) ✅ engine · GUI ⬜ Phase 3
Normalized 6-D surface feature vector (ATM IV, IVR, both TS slopes, 25Δ RR,
VIX z; VVIX joins after ~2 years of history) → Euclidean analog search over
stored `vol_signals` history with macro-compatibility filters; VIX/VVIX
pre-transition monitor; curated event browser (`data/events/regime_events.yaml`).

## Workstation page (today, 🟡)

Vol monitor table (per-ticker IV / IVR+confidence / VRP / TS shape / skew /
regime) → IV-vs-RV and term-structure charts per ticker → greeks form →
interpretation → one click into the scenario lab (grid heatmap by checkpoint,
stress table, kill card).

## Inputs · Outputs · API

| | |
|---|---|
| Reads | `regime_state.json` (gate) · yfinance chains/prices · FRED risk-free · CBOE VIX/VVIX · own `vol_signals` history |
| Writes | `trading.db`: `vol_signals`, `vvix_daily` (+ `vol_surface` in Phase 3) · `data/outputs/vol_signals.json`, `pretrade_memo.json` |
| Jobs | `sarah_daily_vol` |
| API | `/api/sarah/*` ([reference](../02-platform/api-reference.md#sarah)) |

## Data honesty

Everything Sarah touches is delayed retail data. Every output carries
`data_warning`; IVR/IVP carry `ivr_ivp_confidence`; analog search warns under
120 days of history. The pre-live-capital gate (CBOE historical options
data, upgrade items U3.3/U5.2) is documented in
[ADR-004](../../design_decisions/ADR-004-scope-deferrals.md).
