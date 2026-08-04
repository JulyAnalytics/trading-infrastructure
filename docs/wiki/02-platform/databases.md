---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# Databases — Full Schema Reference

Two DuckDB files own all persistent state; JSON contracts live in
`data/outputs/` ([output-contracts.md](../03-contracts/output-contracts.md));
the RCS SQLite is external and read-only
([rcs-journal.md](../01-components/rcs-journal.md)). Access rules:
`get_connection()` from `systems/utils/db.py` only (Rule 2); API reads are
`read_only=True` via `systems/api/deps.py`.

---

## `data/processed/macro.db` — Marcus's world

Schema owner: `systems/utils/db.py:initialize_schema()`.

### `macro_series` — every macro time series
| Column | Type | Notes |
|---|---|---|
| series_id | VARCHAR | internal key, e.g. `vix`, `hy_spread` (PK with date) |
| series_name | VARCHAR | human label |
| date | DATE | |
| value | DOUBLE | native units (%, bps, index) |
| pct_chg_1m / _3m / _12m | DOUBLE | 21/63/252-row percent changes |
| z_score_1y / z_score_5y | DOUBLE | rolling 252/1260-day z-scores, computed **at write time** |
| updated_at | TIMESTAMP | |

*Caveat:* re-upserting history silently recomputes z-scores (audit #1).

### `regime_history` — one row per classified day
| Column | Type | Notes |
|---|---|---|
| date | DATE PK | |
| regime | VARCHAR | six-state label |
| regime_score / composite_score | DOUBLE | duplicated by legacy insert |
| vix, hy_spread, yield_curve, breakeven_10y, unemp_delta | DOUBLE | snapshot inputs |
| vol_score … positioning_score | DOUBLE ×6 | component scores |
| confidence | VARCHAR | HIGH/MEDIUM/LOW |
| vol_as_of … positioning_as_of | DATE ×6 | per-component data dates (staleness) |
| divergence_type / divergence_severity | VARCHAR | null when none |
| notes, updated_at | | |

*Phase 2 planned addition:* `divergence_onset_date`,
`divergence_severity_trend` (currently computed on the fly by
`regime_analytics.fragility_assessment`).

### `cot_positioning`
instrument VARCHAR + date DATE (PK) · net_spec DOUBLE (contracts) ·
net_spec_pct DOUBLE (of OI) · z_score_1y / z_score_3y · updated_at.

### `fetch_log`
series_id · fetched_at · rows_updated · status · error_msg — ingestion audit trail.

### `macro_calendar`
event_name + event_date (PK) · category · importance INTEGER · component ·
source · updated_at — FOMC + release dates, 45d horizon.

### `regime_return_stats` (built by `scripts/compute_regime_return_stats.py`)
regime · asset (SPY/TLT/GLD/HYG/UUP) · horizon (1M/3M) · median_return ·
p25_return · p75_return · n_observations — feeds the implications panel;
rows with n<20 are flagged low-sample in the GUI.

---

## `data/processed/trading.db` — Sarah, Priya, and the v1.0 platform

Schema owners: `systems/sarah/vol_db.py` (vol tables),
`systems/data_feeds/cboe_feed.py` (vvix), `systems/backtest/hypothesis_registry.py`,
and the v1.0 modules (each `CREATE TABLE IF NOT EXISTS` on first use).

### `vol_signals` — one row per (ticker, date)
| Group | Columns |
|---|---|
| Basis | spot_price, forward_price, risk_free_rate, div_yield, atm_iv_30d |
| IV context | iv_rank, iv_percentile, ivr_ivp_confidence (`low/medium/standard/insufficient`), ivr_regime_bias |
| Skew (Δ-space) | skew_25d_rr, skew_25d_put, skew_25d_call, skew_1025_ratio |
| Term structure | ts_iv_30d/60d/180d, ts_front_slope, ts_back_slope, ts_shape (6-state) |
| VRP | rv_21d, vrp_proxy_bkwd, vrp_proxy_signal (6-state) |
| Context | macro_regime |
| Raw JSON | term_structure_json ({dte: iv}), skew_by_delta_json ({dte, puts:{Δ:iv}, calls:{Δ:iv}} — 5Δ–50Δ grid), pc_oi_ratio_json ({aggregate_ratio, by_expiration, totals}) |

All populated since the Phase 3 data completions (2026-07-17).

### `vol_surface` — strike×expiry grid ✅ populated daily
ticker · date · expiration · dte · strike · log_moneyness · delta ·
option_type (`call/put`) · iv (**vol points**, matching vol_signals) · bid ·
ask · volume · open_interest. Delete-then-insert per (ticker, date) —
idempotent. Feeds the surface heatmap.

### `vvix_daily`
date PK · vvix · vix · vvix_vix_ratio · source (`yfinance` live /
`cboe_historical` backfill). **History: 2006-03-06 → present** (U5.1
bootstrap; the backfill never overwrites live rows).

### `pretrade_memos` (Phase 3)
memo_id VARCHAR PK (**stable `PTM-YYYYMMDD-TICKER-NNN`** — the RCS/library
cross-link key) · ticker · date · created_at · catalyst_type ·
expected_move · thesis_days · max_loss_budget · expected_move_sign ·
memo_json (full memo contract) · param_hashes ·
**rcs_trade_ulid** (set when the memo priced an RCS trade — the citation key
back to it; the RCS-side citation stays the user's own note, ADR-003).

### `alerts` (Phase 6)
id PK · created_at · source (`jobs`/`jordan_limits`/…) · severity
(`warning/error`) · message · acked BOOLEAN — the GUI feed; every row also
fired a macOS notification.

### `hypothesis_registry` (Priya)
Pre-registered hypotheses + **trial counts per dataset** (the N for DSR).
Managed exclusively by `hypothesis_registry.py`.

### `parameter_versions` (v1.0 registry) 🟡
| Column | Type | Notes |
|---|---|---|
| component | VARCHAR | `marcus/sarah/priya/jordan/ops/data` (PK with version) |
| version | INTEGER | monotonically increasing per component |
| payload | VARCHAR | canonical sorted-key JSON of the full parameter set |
| hash | VARCHAR | 12-hex sha256 of payload — the provenance stamp |
| note | VARCHAR | the "why" entered at save time |
| created_at | TIMESTAMP | |
| active | BOOLEAN | exactly one true row per component |

Append-only in spirit: rollback inserts a new version with an old payload.

### `jobs` (v1.0 orchestration) ✅
id VARCHAR PK (12-hex) · name · status (`queued/running/succeeded/failed`) ·
param_hashes (JSON component→hash at launch) · created_at · started_at ·
finished_at · exit_code · log_tail (last 4KB stdout+stderr) · error ·
requested_by (`gui`/`scheduler`/`sarah_intake_poll`/`retry:<origin>:aN`) ·
**depends_on** (job id that must have succeeded — dependency enforcement) ·
**args** (JSON per-run arguments, handed to the child as `JOB_ARGS_JSON` —
e.g. `{"tickers":["AAOI"],"source":"rcs_intake"}`; retries carry it forward).

### `jordan_positions` (v1.0 manual book entries) ✅
id PK · ticker · asset_type (`option/equity`) · flag (`c/p`) · strike ·
expiration · quantity · long_short · entry_price · entry_date · note ·
status (`active/closed`) · created_at.

### `sarah_trade_inputs` (RCS trade intake) ✅
The judgment inputs and pre-fills for one RCS trade. Keyed by the RCS trade
ULID — **FK-by-convention only**: the two databases are deliberately not
coupled (ADR-005), and nothing here is ever written back to RCS (ADR-003).

| Column | Notes |
|---|---|
| rcs_trade_ulid | VARCHAR PK — the RCS `trade.id` |
| ticker | the options-liquid underlier actually analysed (post `sarah.underlier_map`) |
| rcs_instrument | the original RCS instrument, pre-map (so "AMDL analysed as AMD" is visible) |
| **expected_move** | the one genuinely user-only field. **Unsigned decimal fraction** — 0.20 = ±20%, *not* 20. NULL until the user supplies it |
| expected_move_sign | ±1 or NULL; single long call → +1, long put → −1; spreads stay unsigned |
| thesis_days · catalyst_type | from `resolve_catalyst()`, else the dominant leg expiry (DTE), else a prompt |
| max_loss_budget | $/contract: `options_meta.max_loss_dollar` ÷ contracts → `thesis.worst_case_dollar` ÷ contracts → prompt |
| flow_json | optional FlowObservation payload |
| source | `user` / `rcs_intake` / `llm` — a row the user has edited stays labelled `user` |
| **user_overrides** | JSON list of the Class-A/B fields the user set *deliberately*. Per-field provenance is what lets a re-pull refresh everything RCS owns while leaving explicit choices alone; without it the merge had to either clobber judgment or freeze stale data (it froze — fixed 2026-08-03) |
| last_error | set when the vol pull failed for this ticker even after the map; surfaced as the blocking "which underlier?" item |
| created_at · updated_at | `updated_at` moves on any write |
| rcs_synced_at | last re-derivation from RCS specifically — distinguishes "re-read the journal" from "the user edited a field" |

### `sarah_intake_watermark` (RCS trade intake) ✅
`id INTEGER PK CHECK(id=1)` · `last_occurred_at TIMESTAMP` — the last RCS
`entity_events.occurred_at` processed by the intake poll. It lives on the
trading side because RCS's own `export_watermarks` does not cover the `trade`
entity, and because ADR-003 forbids writing `research.db` at all. Never moves
backwards; a restart re-polls harmlessly rather than replaying history.

---

## Other stores

| Store | What |
|---|---|
| `data/outputs/*.json` | The four locked contracts ([details](../03-contracts/output-contracts.md)) |
| `data/mlruns/` | MLflow experiment store — every Priya run incl. NO_GO failure archive |
| `data/events/regime_events.yaml` | Hand-curated historical event library (6 events) for the regime library & stress narratives |
| `data/snapshots/*.pdf` | Nightly one-page regime snapshots |
| `reports/weekly/*.{md,pdf}` | Friday weekly reviews (generated; parameter-hash-stamped) |
| `data/processed/main.db.deprecated` | Phase 0 relic — never touch (Rule 3) |
| RCS `research.db` | External journal — read-only (Rule 6); schema in [rcs-journal.md](../01-components/rcs-journal.md) |
