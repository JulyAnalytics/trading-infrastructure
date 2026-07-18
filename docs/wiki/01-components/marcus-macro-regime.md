# Marcus — Macro Regime Classification

**Status:** classifier ✅ live since Phase 1 · v1.0 analytics 🟡 unverified
**Code:** `systems/signals/regime_classifier.py`, `systems/signals/regime_analytics.py`
**Feeds:** `systems/data_feeds/macro_feed.py` · **GUI:** workstation *Marcus* page + Command Deck
**Params:** registry component `marcus` ([schema](../03-contracts/parameter-schemas.md#marcus))

## Job

Answer, every evening: *what macro environment are we in, how sure are we,
and is it cracking?* Marcus's output is the context gate for the entire
system — Sarah, Priya, and Jordan all refuse to run against a stale regime.

## How classification works

1. `_load_snapshot()` pulls the latest value, z-score, and date for ~20
   series from `macro.db:macro_series` (VIX, HY/IG spreads, 10Y−2Y and
   10Y−3M curves, 10Y breakeven + 5y5y forward, real rates, PCE YoY,
   unemployment + 3m delta, jobless claims z, M2 YoY, oil, SP500 COT z).
2. Six **component scorers** each map their inputs to −1…+1 using the
   threshold families in `MarcusParams.regime_thresholds` (e.g. VIX < 15 →
   +1.0; HY > 900bps → −1.0). Missing data scores 0 (neutral) and is listed
   in `missing_inputs`.
3. Weighted sum (`component_weights`: vol .25, credit .25, curve .20, labor
   .15, inflation .10, positioning .05) → **composite score** → regime label
   via the `score_to_regime` floors (+0.60 / +0.25 / −0.10 / −0.40 / −0.65).
4. **Confidence** from sign-agreement among the five fundamental components
   (≥0.8 → HIGH, ≥0.6 → MEDIUM); positioning is excluded (contrarian).
5. **Divergence detection**: vol-vs-credit spread ≥ 0.6 fires
   `LEADING_STRESS_WARNING` (credit stressed, vol calm) or
   `ELEVATED_VOL_UNCONFIRMED`; vol+credit stressed while labor strong fires
   `LABOR_LAG_WARNING`; max−min component spread ≥ 1.2 fires the LOW-severity
   broad-divergence flag.
6. Persist to `macro.db:regime_history`; `write_output_contract()` writes
   [`regime_state.json`](../03-contracts/output-contracts.md#regime_statejson).

Every number in steps 2–5 is a registry parameter. The classifier asserts
weights sum to 1.0 at construction and accepts an injected `MarcusParams`
for GUI previews (`RegimeResult.params` keeps attribution consistent with
whatever scored it).

## The analytical layers on top

| Layer | What it answers | Where |
|---|---|---|
| **Attribution** | Which components drive vs contradict the label; how far to the nearest flip (`flip_watch`) | `RegimeResult.attribution()` |
| **Transition probability** | ~30d chance of a label change (threshold proximity + 10-day momentum + divergence boost, capped 85%) | `RegimeResult.regime_change_probability()` |
| **Fragility assessment** 🟡 | STABLE / WATCH / FRAGILE / BREAKING headline + divergence duration & trend | `regime_analytics.fragility_assessment` |
| **State vector + geometry** 🟡 | Six scores preserved; financial-conditions / real-economy / nominal sub-composites; distance to CAUTION/STRESS; configuration type (e.g. `CREDIT_LED_STRESS`); coherence | `regime_analytics.build_state_vector`, `regime_geometry` |
| **Historical analogues** 🟡 | Nearest past dates in score-space (trailing year excluded) | `regime_analytics.nearest_neighbours` |
| **Interpreter (vol+credit)** 🟡 | Plain-language read per component: headline, regime-consistency, and an explicit *watch condition* (the falsifier) | `regime_analytics.interpret_components` |
| **Return implications** 🟡 | What SPY/TLT/GLD/HYG/UUP historically did in this regime (1M/3M medians + quartiles), with sample-reliability flags and a configuration caveat | `regime_analytics.implication_summary` over `regime_return_stats` |

## Inputs · Outputs

| | |
|---|---|
| Reads | `macro.db`: `macro_series`, `cot_positioning`, `regime_history` (momentum), `regime_return_stats` (implications) |
| Writes | `macro.db:regime_history` · `data/outputs/regime_state.json` |
| Jobs | `marcus_classify`, `fred_incremental`, `snapshot_pdf`, `backfill_regime_history`, `calibrate_divergence` |
| API | `/api/marcus/*` ([reference](../02-platform/api-reference.md#marcus)) |

## Known limitations (from audit #2)

- Weights and thresholds are expert-set, not empirically calibrated;
  `calibrate_divergence` exists as a job for the divergence pair.
- Hard thresholds create cliff effects (VIX 24.9 vs 25.1 scores differently).
- The label is coincident/lagging; the fragility layer exists precisely
  because transitions, not levels, carry the value.
- Positioning scores SP500 COT only, despite six instruments being ingested.
- Regime-conditional weights (Gap 2) and the forward scenario layer (Gap 6)
  are deliberately deferred to v1.1 (need longer validated backfill).

## Operating Marcus

Morning read: [morning-routine.md](../04-workflows/morning-routine.md).
Changing weights/thresholds (with preview + backfill re-run):
[editing-parameters.md](../04-workflows/editing-parameters.md).
