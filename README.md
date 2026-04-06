# Trading Infrastructure

A systematic trading research and execution infrastructure.

## Components

| Component | Status | Entry point |
|-----------|--------|-------------|
| **Marcus** — macro regime classifier | ✅ Live | `systems/signals/regime_classifier.py` |
| **Sarah Stage 1** — daily vol pipeline | ✅ Complete | `systems/sarah/daily_vol_run.py` |
| **Sarah Stage 2** — analytic greeks engine | ✅ Complete | `systems/sarah/greeks_tool.py` |
| **Sarah Stage 3** — scenario P&L engine | ✅ Complete | `systems/sarah/scenario_engine.py` |
| **Sarah Stage 4** — pre-trade dashboard | ✅ Complete | `systems/sarah/pretrade_dashboard.py` |
| **Sarah Stage 5** — regime library / analog search | ✅ Complete | `systems/sarah/regime_library.py` |
| **Jordan** — risk layer | ⬜ Not built | `systems/risk/` |
| **Priya** — research backtesting | ⬜ Not built | `research/` |
| **Kai** — execution layer | ⬜ Not built | `systems/execution/` |
| **Alex** — orchestration | ⚠️ Framework only | `scheduler.py` |

## Databases

| File | Purpose |
|------|---------|
| `data/processed/macro.db` | Marcus: macro series, regime history, COT, calendar |
| `data/processed/trading.db` | Sarah: vol signals, vol surface, VVIX daily |

## User-facing interfaces

**Marcus dashboard (Dash web app):**
```bash
python systems/dashboard/macro_dashboard.py
# → http://127.0.0.1:8050
```

**Sarah — programmatic (no GUI):**
```bash
python systems/sarah/daily_vol_run.py          # Stage 1: refresh vol signals
python systems/sarah/greeks_tool.py            # Stage 2: greeks demo
```

See `docs/architecture/current_state.md` for full API reference.

## Setup

```bash
bash setup.sh
```

## Verification

```bash
python scripts/verify_phase0.py
```

## Pipeline

The scheduler runs automatically:
- **Weekdays 08:00** — Sarah vol surface run (requires Marcus regime_state.json)
- **Weekdays 18:05** — Marcus macro pipeline (FRED → regime classify → snapshot)
- **Sunday 20:00** — Full FRED history refresh

```bash
python scheduler.py
```
