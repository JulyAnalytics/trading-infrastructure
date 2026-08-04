---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# Output Contracts (`data/outputs/`)

Four locked JSON files are the inter-component handshake. **Schemas are
locked** (CLAUDE.md Rule 5): changing one requires updating CLAUDE.md and
`docs/architecture/`. `written_at` timestamps drive the staleness gates.

## `regime_state.json`
**Writer:** Marcus (`RegimeClassifier.write_output_contract`) · **Readers:** everyone
**Staleness:** 12h production / 80h research (registry: `ops.regime_staleness_hours_production`, `priya.backtest_regime_staleness_hours`)

```json
{
  "regime_state":     "RISK_ON_LOW_VOL",
  "composite_score":  0.42,
  "component_scores": { "vol": 0.6, "credit": 0.5, "curve": 0.3,
                         "inflation": 0.1, "labor": 0.4, "positioning": -0.1 },
  "confidence":       "HIGH",
  "divergence_type":  null,
  "as_of":            "2026-03-29",
  "missing_inputs":   [],
  "written_at":       "2026-03-29T18:07:23.441"
}
```

Reading it: `missing_inputs` containing `vix` or `hy_spread` (the two
25%-weight components) makes the label unreliable. `write_output_contract()`
must be called explicitly after `classify()` — the scheduler/jobs do this;
a DB-only classify leaves the file stale.

## `vol_signals.json`
**Writer:** Sarah Stage 1 (`daily_vol_run.py`) · **Readers:** GUI, Priya research, Jordan context

```json
{
  "as_of": "2026-03-29",
  "macro_regime": "RISK_ON_LOW_VOL",
  "signals": {
    "SPY": { "atm_iv_30d": 0.142, "realized_vol_21d": 0.108,
             "vrp": 0.034, "vrp_signal": "elevated_vrp",
             "skew_25d": 0.041, "skew_direction": "put_bid",
             "iv_rank": 0.28, "iv_percentile": 0.31,
             "vol_regime": "LOW_VOL",
             "ts_slope": 0.021, "ts_shape": "contango" }
  },
  "summary": { "elevated_vrp": ["SPY"], "low_iv_rank": ["SPY"],
                "high_put_skew": [] }
}
```

The DB row (`trading.db:vol_signals`) is the richer record; the JSON is the
summary contract. Check `ivr_ivp_confidence` in the DB before trusting
rank/percentile.

## `pretrade_memo.json`
**Writer:** Sarah Stage 4 (`generate_memo`) · **Reader:** the human. The
file holds the *latest* memo; the durable record is
`trading.db:pretrade_memos`, where every memo persists with a stable
`memo_id` (`PTM-YYYYMMDD-TICKER-NNN`) for RCS/library cross-links.

```json
{ "ticker": "SPY", "date": "2026-03-31", "written_at": "2026-03-31T…",
  "thesis_parameters": { "expected_move": 0.10, "thesis_days": 45,
                          "catalyst_type": "macro_catalyst",
                          "max_loss_budget": 600.0 },
  "market_state": { "vol_level": {}, "term_structure": {},
                     "skew": {}, "flow": null, "distribution": {} },
  "structure_comparison": { "all_structures": {}, "affordable": {} },
  "data_warning": "⚠ Data: yfinance 15–20 min delayed. Not for live pre-trade decisions." }
```

## `research_verdict.json`
**Writer:** Priya Stage 8 (`ResearchPipeline` → `write_jordan_contract`) · **Reader:** Jordan's verdict intake

```json
{
  "hypothesis_id": "…", "strategy_type": "equity|options",
  "verdict": "GO|NO_GO", "production_haircut_sharpe": 0.65,
  "viable_after_haircut": true, "pbo": 0.03, "dsr": 0.97,
  "cpcv_path_count": 5, "n_trials": 8, "n_eff": 5.2,
  "min_track_record_years": 2.1, "leland_breakeven_spread": null,
  "regime_conditional_sharpe": {"RISK_ON_LOW_VOL": 1.2, "NEUTRAL": 0.8},
  "regime_at_verdict": "RISK_ON_LOW_VOL",
  "regime_as_of": "2026-04-06",
  "staleness_guidance": "…do not act if stale or regime shifted…",
  "written_at": "2026-04-06T14:30:00.000+00:00"
}
```

**The G4-7 rule (both halves closed 2026-07-17/18):** the file does not
update as conditions change, so (writer side) it stamps
`regime_at_verdict`/`regime_as_of`/`staleness_guidance` at write time, and
(consumer side) Jordan's intake re-checks freshness
(`jordan.verdict_max_age_hours`) and regime compatibility
(`regime_conditional_sharpe[current regime] > 0`, with the stamp making a
shift detectable) before any sizing — a GO is *never* actionable on its
own. `written_at` is tz-aware UTC.

## Related artifacts (not contracts)

`data/snapshots/macro_*.pdf` (nightly one-pagers) ·
`data/mlruns/` (MLflow, incl. the NO_GO failure archive) ·
v1.0 provenance lives in DB tables (`jobs.param_hashes`,
`parameter_versions`) rather than JSON files.
