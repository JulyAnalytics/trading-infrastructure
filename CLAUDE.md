# Leopold — Claude Code Reference
**Last updated:** 2026-08-03 — **Sarah ← RCS trade intake seam live** (`systems/sarah/trade_intake.py`, `/api/sarah/intake`, `sarah_trade_inputs` + `sarah_intake_watermark`): a trade committed in RCS auto-triggers Sarah's vol pull and arrives pre-filled, leaving only `expected_move` (spec: `~/Nextcloud/Documents/Planning/sarah-rcs-trade-intake-spec.md`). Brought job **args** plumbing (`JOB_ARGS_JSON`) and `run_daily_vol(tickers=…)` batch mode with it. Earlier: v1.0 workstation build (parameter registry + FastAPI/React), see `docs/architecture/v1_architecture.md`; Phase 0 gauntlet + Jordan suite green 07-06; **Phase 3 (Sarah) complete 07-17** — five tools live (vol monitor + surface/cones, greeks/scenarios, memo builder → `pretrade_memos`, regime library + VVIX backfill to 2006).

> **Environment note:** use `venv/bin/python` (Python 3.11.9 via pyenv), not
> system `python3`. The venv's interpreter symlinks and script shebangs were
> found corrupted by Nextcloud sync (symlinks → plain-text target files;
> shebangs hardcoded to a stale OneDrive path) and have been repaired.
> `py_vollib` (used by `systems/utils/pricing.py`) and `reportlab` (used by
> `systems/reports/snapshot_generator.py`) were both missing from
> `requirements.txt` despite being real dependencies — added. `kaleido` is
> still absent, so the snapshot PDF falls back to matplotlib text for charts
> (job succeeds, charts degraded) — install `kaleido` for full-quality PDFs.

---

## What This Project Is
A six-component systematic trading system. Each component produces
structured outputs consumed by downstream components. Integration
happens through shared files in `data/outputs/`, DuckDB instances at
`data/processed/macro.db` + `trading.db`, and (v1.0) a FastAPI service
layer at :8100 with a React workstation frontend.

---

## Absolute Rules — Read Before Every Task

1. All file **paths** come from root `config.py`. All **tunables**
   (thresholds, weights, windows, gates, scenario libraries, schedules)
   come from the parameter registry — `systems/params` → `get_params("<component>")`.
   Never hardcode either. Legacy `from config import CONSTANT` still resolves
   (through the registry via `config.__getattr__`), but new code calls
   `get_params()` directly. Edit values via the GUI/`set_params()` — never in code.
2. All DB connections use `get_connection()` from `systems/utils/db.py`.
   Never call `duckdb.connect()` directly. API read paths use the read-only
   helpers in `systems/api/deps.py`.
3. Never import from `systems/config_phase0_deprecated.py`.
   It is a deprecated Phase 0 relic. Use root `config.py` only.
4. Every downstream component (Sarah, Jordan, Kai, etc.) must read
   `data/outputs/regime_state.json` before running. If it is missing
   or its `written_at` is more than 12 hours ago, the run must fail
   loudly with a clear error — never silently proceed with stale data.
5. Output contract schemas in `data/outputs/` are locked. Never change
   a schema without updating this document and `docs/architecture/`.
6. The Research Capture System database is READ-ONLY from this repo (SQLite
   `mode=ro` in `systems/risk/rcs_bridge.py`). Never open it writable; RCS
   owns its own writes and backups (ADR-003). Its location comes from
   `config.RCS_DB_PATH`, which follows the RCS app's own `research/.env` —
   live path today is `~/.local/state/rcs/research.db`, NOT the in-repo
   `research/data/research.db` copy. Never hardcode either.
7. Pipeline writes run one-at-a-time through job subprocesses
   (`systems/orchestration`); GET endpoints never write. Every run stamps
   `systems.params.all_active_hashes()` for reproducibility.

---

## Documentation Map

**The wiki is the reference manual:** [docs/wiki/Home.md](docs/wiki/Home.md) —
rebuilt 2026-07-18 as a learning-oriented operator's guide: per-component
deep-dives (variables, computations, workflows), 8 step-by-step workflow
guides, live screenshots (`docs/wiki/images/`, regenerate via
`node scripts/capture_wiki_screenshots.mjs`), an LLM-assistant guide
(`00-system/llm-assistant-guide.md`), and the Knowledge-Library integration
spec (`06-knowledge/`). Every page carries `domain/stage/project/persona/
status` frontmatter for the Ashurbanipal filesystem adapter. Architecture
snapshots: `docs/architecture/`; audits: `docs/audit/`; decisions:
`docs/design_decisions/`.

---

## v1.0 Workstation Layer (build in progress)

| Piece | Location | Run / entry point |
|---|---|---|
| Parameter registry | `systems/params/` (models, store, compat) | `python scripts/migrate_params.py --check` |
| FastAPI service layer | `systems/api/` | `python -m uvicorn systems.api.main:app --port 8100` |
| React frontend | `frontend/` (Vite + TS + react-plotly) | `cd frontend && npm install && npm run dev` → :5173 |
| Job runner | `systems/orchestration/` (subprocess-per-job, single worker) | via API `POST /api/jobs` |
| Marcus 1.0 analytics | `systems/signals/regime_analytics.py` (vector/fragility/NN/interpreter/implications) | via `/api/marcus/*` |
| Jordan risk layer | `systems/risk/` (book, limits, stress, verdict intake, RCS bridge) | via `/api/jordan/*`; `python scripts/verify_jordan.py` |
| Golden-master harness | `scripts/golden_master.py`, `scripts/run_phase0_gauntlet.sh` | proves registry migration is behavior-neutral |

New trading.db tables (v1.0): `parameter_versions`, `jobs`, `jordan_positions`,
`pretrade_memos` (stable `PTM-YYYYMMDD-TICKER-NNN` ids for RCS cross-links),
`sarah_trade_inputs` + `sarah_intake_watermark` (RCS trade intake, 2026-08-03).
Registry components: `marcus`, `sarah`, `priya`, `jordan`, `ops`, `data` — seeds
mirror v0.5 config.py values exactly. Priya gate fields are `guarded`: editable,
loudly logged, hash-stamped on outputs.

Still pending (Phase 6): scheduler v2 + weekly review + alerting, Dash
retirement, docs refresh of `current_state.md`. Priya workbench (Phase 4)
complete 07-18 — G4-1/G4-2/G4-7-writer closed, registry hashes → MLflow,
workbench GUI at `/priya`. Audit #5
(Jordan) complete 07-17 — `docs/audit/05_jordan_risk_layer.md`, live RCS smoke
done, drawdown check activates with the Phase 6 NAV series.
Kai + live trading are v1.1 (ADR-004). Phase 3 note: U5.0 was
reconciled as moot — `vix_z1y` is runtime-computed from macro.db (VIX history
1990→present), enriched per-date in `regime_library.enrich_snapshots_with_z_scores`.

---

## Output Contract Schemas (Locked)

### `data/outputs/regime_state.json` — written by Marcus
```json
{
  "regime_state":     "RISK_ON_LOW_VOL",
  "composite_score":  0.42,
  "component_scores": {
    "vol": 0.6, "credit": 0.5, "curve": 0.3,
    "inflation": 0.1, "labor": 0.4, "positioning": -0.1
  },
  "confidence":       "HIGH",
  "divergence_type":  null,
  "as_of":            "2026-03-29",
  "missing_inputs":   [],
  "written_at":       "2026-03-29T18:07:23.441"
}
```

### `data/outputs/vol_signals.json` — written by Sarah (not yet built)
```json
{
  "as_of":        "2026-03-29",
  "macro_regime": "RISK_ON_LOW_VOL",
  "signals": {
    "SPY": {
      "atm_iv_30d": 0.142, "realized_vol_21d": 0.108,
      "vrp": 0.034, "vrp_signal": "elevated_vrp",
      "skew_25d": 0.041, "skew_direction": "put_bid",
      "iv_rank": 0.28, "iv_percentile": 0.31,
      "vol_regime": "LOW_VOL",
      "ts_slope": 0.021, "ts_shape": "contango"
    }
  },
  "summary": {
    "elevated_vrp": ["SPY"],
    "low_iv_rank": ["SPY"],
    "high_put_skew": []
  }
}
```

### `data/outputs/pretrade_memo.json` — written by Sarah Stage 4
```json
{ "ticker": "SPY", "date": "2026-03-31", "written_at": "2026-03-31T...",
  "thesis_parameters": { "expected_move": 0.10, "thesis_days": 45,
                          "catalyst_type": "macro_catalyst", "max_loss_budget": 600.0 },
  "market_state": { "vol_level": {}, "term_structure": {},
                     "skew": {}, "flow": null, "distribution": {} },
  "structure_comparison": { "all_structures": {}, "affordable": {} },
  "data_warning": "⚠ Data: yfinance 15–20 min delayed. Not for live pre-trade decisions." }
```

### `data/outputs/research_verdict.json` — written by Priya (Stage 8)
```json
{
    "hypothesis_id": "...", "strategy_type": "equity|options",
    "verdict": "GO|NO_GO", "production_haircut_sharpe": 0.65,
    "viable_after_haircut": true, "pbo": 0.03, "dsr": 0.97,
    "cpcv_path_count": 5, "n_trials": 8, "n_eff": 5.2,
    "min_track_record_years": 2.1, "leland_breakeven_spread": null,
    "regime_conditional_sharpe": {"RISK_ON_LOW_VOL": 1.2, "NEUTRAL": 0.8},
    "regime_at_verdict": "RISK_ON_LOW_VOL", "regime_as_of": "2026-04-06",
    "staleness_guidance": "…do not act if stale or regime shifted…",
    "written_at": "2026-04-06T14:30:00.000+00:00"
}
```
*(regime_at_verdict / regime_as_of / staleness_guidance added 2026-07-17 —
G4-7 writer side; consumed by `systems/risk/verdict_intake.py`.)*

---

## Component Status

| Component | Status | Entry point |
|-----------|--------|-------------|
| Marcus | ✅ Live | `systems/signals/regime_classifier.py` |
| Sarah Stage 1 | ✅ Complete | `systems/sarah/daily_vol_run.py` — daily vol pipeline |
| Sarah Stage 2 | ✅ Complete | `systems/sarah/greeks_tool.py` — analytic BS, 7 greeks, mispricing flag, portfolio aggregator |
| Sarah Stage 3 | ✅ Complete | `systems/sarah/scenario_engine.py` — scenario P&L engine — heatmap, stress scenarios (skew-amplified), structure comparison with break-even, kill scenario |
| Sarah Stage 4 | ✅ Complete | `systems/sarah/pretrade_dashboard.py` — pre-trade dashboard: 5 panels, BL density, structure comparison, memo JSON |
| Sarah Stage 5 (Complete) | ✅ Complete | `systems/sarah/regime_library.py` — regime library: VVIX feed, analog search, event library (6 events), pre-transition monitor |
| Sarah ← RCS trade intake | ✅ Complete (2026-08-03) | `systems/sarah/trade_intake.py` — RCS `entity_events` poll → underlier map → Class-A/B pre-fills → coalesced `sarah_daily_vol` batch. `/api/sarah/intake`; `python scripts/verify_sarah_intake.py` |
| Priya Stage 1 | ✅ Complete | `systems/backtest/data_audit.py`, `systems/backtest/hypothesis_registry.py` — data audit + hypothesis registration |
| Priya Stage 2 | ✅ Complete | `systems/backtest/feature_engineering.py`, `systems/backtest/vol_estimators.py` — FracDiff + 5 vol estimators + vol cones |
| Priya Stage 3 | ✅ Complete | `systems/backtest/label_construction.py` — triple-barrier labeling (Mode A/B, meta-labeling) + sample uniqueness weights; `systems/backtest/vectorized_engine.py` — VectorizedBacktester: run_single, parameter_sweep, regime_conditional_analysis, _flag_overfitting |
| Priya Stage 4 | ✅ Complete | `systems/backtest/options_engine.py` — MC P&L distribution + 3-level costs + Leland breakeven |
| Priya Stage 5 | ✅ Complete | `systems/backtest/purged_cv.py`, `cpcv.py`, `overfit_statistics.py` — PurgedKFold + CPCV path distribution + PBO + overfit diagnostics |
| Priya Stage 6 | ✅ Complete | `systems/backtest/sharpe_pipeline.py`, `strategy_risk.py` — Lo SE + PSR/DSR pipeline; strategy risk P[p < p*] |
| Priya Stage 7 | ✅ Complete | `systems/backtest/impl_shortfall.py`, `experiment_tracker.py` — implementation shortfall + production haircut utilities + MLflow tracking |
| Priya Stage 8 | ✅ Complete | `systems/backtest/research_pipeline.py` — full pipeline orchestrator + PROCESS_GATES + NON_NEGOTIABLE_OUTPUTS + validate_outputs + write_jordan_contract; `scripts/verify_priya.py`, `scripts/verify_priya_integration.py` |
| Jordan | ⬜ Not built | `systems/risk/` |
| Priya | ⬜ Not built | `research/` |
| Kai | ⬜ Not built | `systems/execution/` |
| Alex | ⬜ Framework only | `scheduler.py` |

---

## Shared Utilities — Always Import, Never Rewrite

```python
from config import (
    DUCKDB_PATH, OUTPUTS_DIR, REGIME_THRESHOLDS,
    COMPONENT_WEIGHTS, FOMC_SCHEDULE_2026
)
from systems.utils.db import get_connection, get_latest, get_series_history
```

### Event Library
`data/events/regime_events.yaml` — manually curated. Add new events after significant market moves.

---

## DB Tables in `macro.db` (do not recreate)

| Table | Written by | Purpose |
|-------|-----------|---------|
| `macro_series` | macro_feed.py | All FRED + derived series with z-scores |
| `regime_history` | regime_classifier.py | Daily regime classification history |
| `cot_positioning` | macro_feed.py | CFTC COT positioning data |
| `fetch_log` | macro_feed.py | Data ingestion audit trail |
| `macro_calendar` | macro_feed.py | FOMC + release dates |
| `regime_return_stats` | compute_regime_return_stats.py | Regime-conditional returns |

## DB Tables in `trading.db` (do not recreate)

| Table | Written by | Purpose |
|-------|-----------|---------|
| `vol_signals` | daily_vol_run.py | Daily vol surface signals per ticker |
| `vol_surface` | daily_vol_run.py | Raw vol surface term structure |
| `vvix_daily` | cboe_feed.py | Daily VVIX, VIX, ratio values |
| `hypothesis_registry` | hypothesis_registry.py | Pre-registered research hypotheses + trial counts per dataset |
| `sarah_trade_inputs` | trade_intake.py | Per-RCS-trade judgment inputs (`expected_move`) + Class-A/B pre-fills, keyed by RCS trade ULID |
| `sarah_intake_watermark` | trade_intake.py | Single-row watermark over RCS `entity_events` (trading-side; RCS is never written) |

---

## Phase 1 Features Already Built (do not rebuild)

- Regime classification with 6 weighted components
- Divergence detection (Vol/Credit/Labor signal tiers)
- Attribution analysis (drivers, contradictors, flip-watch)
- Regime change probability scoring (~30d)
- Data staleness tracking per component
- Regime persistence statistics
- Regime-conditional return statistics
- PCE (PCEPI) wired into inflation component scoring
- 5y5y forward breakeven (T5YIFR) in MACRO_SERIES and inflation scoring
- PDF snapshot generation
- Macro calendar integration (FOMC + release dates)
- COT positioning data pipeline
- Dash dashboard at http://127.0.0.1:8050

---

## Known Deprecated / Superseded Files

| File | Status | Notes |
|------|--------|-------|
| `systems/config_phase0_deprecated.py` | Deprecated | Phase 0 only; only db_init.py uses it |
| `systems/db_init.py` | Superseded | Phase 0 schema; `main.db` not used by pipeline |
| `data/processed/main.db.deprecated` | Superseded | Phase 0 DB renamed; pipeline uses `macro.db` |
| `scheduler.py` (root) | **Retired 2026-07-18 (code-enforced 2026-07-19)** | Replaced by `systems/orchestration/scheduler_v2.py` (in-process, OpsParams-driven, dependency-enforced). `__main__` now exits non-zero — refuses to run |
| `systems/dashboard/macro_dashboard.py` | **App retired 2026-07-18** | Never run the :8050 Dash app (write-on-refresh); module kept — snapshot_generator imports its figure builders |
