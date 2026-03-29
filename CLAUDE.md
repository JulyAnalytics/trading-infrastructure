# Trading Infrastructure — Claude Code Reference
**Last updated:** 2026-03-29

---

## What This Project Is
A six-component systematic trading system. Each component produces
structured outputs consumed by downstream components. Integration
happens through shared files in `data/outputs/` and a single DuckDB
instance at `data/processed/macro.db`.

---

## Absolute Rules — Read Before Every Task

1. All file paths come from **root `config.py`**. Never hardcode a path.
2. All DB connections use `get_connection()` from `systems/utils/db.py`.
   Never call `duckdb.connect()` directly.
3. Never import from `systems/config_phase0_deprecated.py`.
   It is a deprecated Phase 0 relic. Use root `config.py` only.
4. Every downstream component (Sarah, Jordan, Kai, etc.) must read
   `data/outputs/regime_state.json` before running. If it is missing
   or its `written_at` is more than 12 hours ago, the run must fail
   loudly with a clear error — never silently proceed with stale data.
5. Output contract schemas in `data/outputs/` are locked. Never change
   a schema without updating this document and `docs/architecture/`.

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

---

## Component Status

| Component | Status | Entry point |
|-----------|--------|-------------|
| Marcus | ✅ Live | `systems/signals/regime_classifier.py` |
| Sarah | 🔨 Next | `systems/sarah/` (not yet created) |
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
