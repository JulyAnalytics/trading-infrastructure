"""
Golden-master harness for the parameter-registry migration (v1.0 Phase 0).

The config.py → registry refactor must be behavior-neutral. This script
snapshots the observable behavior of the migrated surface and compares
before/after:

  1. config_values — every legacy config constant the registry now backs
  2. marcus        — full RegimeClassifier().classify(persist=False) output,
                     attribution, and regime-change probability (DB-driven,
                     no network)
  3. scenario      — ScenarioEngine grid/stress/kill/structure outputs on a
                     fixed synthetic position (pure computation)

Usage:
    python scripts/golden_master.py capture  /path/to/before.json
    python scripts/golden_master.py capture  /path/to/after.json
    python scripts/golden_master.py compare  /path/to/before.json /path/to/after.json
"""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

FLOAT_TOL = 1e-9

# Kept as a literal list (not imported from systems.params) so the capture is
# identical whether it runs against pre- or post-migration code.
CONFIG_NAMES = [
    "REGIME_THRESHOLDS", "COMPONENT_WEIGHTS", "STALENESS_THRESHOLDS_DAYS",
    "UNEMPLOYMENT_STALE_DAYS", "DIVERGENCE_THRESHOLD_VC",
    "DIVERGENCE_THRESHOLD_VL", "DIVERGENCE_MIN_CREDIT_STRESS",
    "VOL_TICKERS", "FRED_RISK_FREE_SERIES", "VOL_IVR_MIN_HISTORY_DAYS",
    "ANALOG_MIN_HISTORY_DAYS", "VVIX_CONFIDENCE_MIN_DAYS", "CATALYST_TYPES",
    "MAX_FLOW_NOTES_LENGTH",
    "BACKTEST_MIN_OBSERVATIONS", "BACKTEST_MIN_OPTIONS_OBS",
    "SPREAD_FLOOR_OTM_SHORT", "SPREAD_FLOOR_OTM_LONG",
    "SPREAD_FLOOR_ATM_SHORT", "SPREAD_FLOOR_ATM_LONG",
    "SPREAD_FLOOR_ITM_SHORT", "SPREAD_FLOOR_ITM_LONG",
    "BACKTEST_DEFAULT_SIGNIFICANCE", "BACKTEST_PBO_REJECT_THRESHOLD",
    "BACKTEST_DSR_ACCEPT_THRESHOLD", "BACKTEST_PRODUCTION_HAIRCUT",
    "BACKTEST_MIN_VIABLE_HAIRCUT_SR", "BACKTEST_REGIME_STALENESS_HOURS",
    "CPCV_DEFAULT_N_GROUPS", "CPCV_DEFAULT_K_TEST", "CPCV_DEFAULT_PCT_EMBARGO",
    "MC_DEFAULT_N_PATHS", "SHARPE_AUTOCORR_PVALUE_THRESHOLD",
    "SHARPE_NEWEY_WEST_LAGS", "VOL_CONE_WINDOWS", "VOL_CONE_PERCENTILES",
    "FRACDIFF_D_RANGE", "FRACDIFF_D_STEP", "FRACDIFF_WEIGHT_THRESHOLD",
    "TRIPLE_BARRIER_PT_MULTIPLIER", "TRIPLE_BARRIER_SL_MULTIPLIER",
    "TRIPLE_BARRIER_EWMA_SPAN", "BACKTEST_OVERFITTING_SHARPE_CV_THRESHOLD",
    "BACKTEST_SWEEP_MIN_POINTS",
    "FOMC_SCHEDULE_2026", "CFTC_INSTRUMENTS", "DASHBOARD_REFRESH_SECONDS",
]

SYNTHETIC_POSITION = {
    "market": {"spot": 500.0, "iv": 18.0, "dte": 45, "rate": 0.045,
               "div_yield": 0.012, "forward": 502.0},
    "position": {"strike": 510.0, "flag": "c", "quantity": 2,
                 "long_short": "long"},
    "greeks": {"delta": 0.42},
}

SYNTHETIC_STRUCTURES = [
    {"label": "Long 510C 45d",
     "legs": [{"flag": "c", "strike": 510.0, "dte": 45, "iv": 18.0,
               "long_short": "long", "quantity": 1}]},
    {"label": "510/530 call vertical 45d",
     "legs": [{"flag": "c", "strike": 510.0, "dte": 45, "iv": 18.0,
               "long_short": "long", "quantity": 1},
              {"flag": "c", "strike": 530.0, "dte": 45, "iv": 17.2,
               "long_short": "short", "quantity": 1}]},
]


def _jsonable(obj):
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(v) for v in obj]
    if isinstance(obj, float):
        return None if math.isnan(obj) else obj
    if isinstance(obj, (int, str, bool)) or obj is None:
        return obj
    return str(obj)


def capture_config_values() -> dict:
    import config
    return {name: _jsonable(getattr(config, name)) for name in CONFIG_NAMES}


def capture_marcus() -> dict:
    from systems.signals.regime_classifier import RegimeClassifier
    clf = RegimeClassifier()
    result = clf.classify(persist=False)
    history = clf.get_history(252)
    out = {
        "regime": result.regime,
        "composite_score": result.composite_score,
        "confidence": result.confidence,
        "as_of": str(result.as_of),
        "scores": {
            "vol": result.vol_score, "credit": result.credit_score,
            "curve": result.curve_score, "inflation": result.inflation_score,
            "labor": result.labor_score, "positioning": result.positioning_score,
        },
        "bullish_signals": result.bullish_signals,
        "bearish_signals": result.bearish_signals,
        "warnings": result.warnings,
        "divergence": _jsonable(result.divergence),
        "attribution": _jsonable(result.attribution()),
        "regime_change_probability": _jsonable(
            result.regime_change_probability(history)
        ),
    }
    return out


def capture_scenario() -> dict:
    from systems.sarah.scenario_engine import ScenarioEngine
    eng = ScenarioEngine()
    pos = SYNTHETIC_POSITION

    grid = eng.scenario_pnl_grid(pos, spot_vix=17.0)
    grid_summary = {}
    for tf, df in grid["grids"].items():
        vals = df.values
        grid_summary[str(tf)] = {
            "shape": list(vals.shape),
            "nansum": round(float(__import__("numpy").nansum(vals)), 6),
            "cell_00": round(float(vals[0, 0]), 6),
            "cell_center": round(float(vals[vals.shape[0] // 2,
                                             vals.shape[1] // 2]), 6),
        }

    grid_hv = eng.scenario_pnl_grid(pos, spot_vix=32.0)

    stress = {}
    from systems.sarah import scenario_engine as se_mod
    scenario_keys = sorted(
        getattr(se_mod, "STRESS_SCENARIOS", None)
        or eng.stress_scenario_library().keys()  # post-migration accessor
    )
    for key in scenario_keys:
        r = eng.stress_scenario_pnl(pos, key)
        stress[key] = {
            "pnl_flat_shift": r["pnl_flat_shift"],
            "pnl_skew_amplified": r["pnl_skew_amplified"],
            "spot_shock_pct": r["spot_shock_pct"],
            "vol_shock_vpts": r["vol_shock_vpts"],
        }

    kill = eng.kill_scenario(pos)
    structures = eng.compare_structures(
        SYNTHETIC_STRUCTURES, expected_move_pct=0.06, expected_move_days=30,
        spot=500.0, rate=0.045, div_yield=0.012,
    )

    return {
        "grid_normal": grid_summary,
        "grid_params_normal": _jsonable(grid["grid_params"]),
        "grid_highvol_mode": grid_hv["high_vol_mode"],
        "grid_params_highvol": _jsonable(grid_hv["grid_params"]),
        "entry_price": round(float(grid["entry_price"]), 9),
        "stress": stress,
        "kill": _jsonable(kill),
        "structure_comparison": structures,
    }


def capture(out_path: str) -> None:
    snapshot = {
        "config_values": capture_config_values(),
        "marcus": capture_marcus(),
        "scenario": capture_scenario(),
    }
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(snapshot, indent=2, sort_keys=True))
    print(f"golden master captured → {out_path}")


def _diff(a, b, path, problems):
    if isinstance(a, float) and isinstance(b, (int, float)):
        if not math.isclose(a, float(b), rel_tol=FLOAT_TOL, abs_tol=FLOAT_TOL):
            problems.append(f"{path}: {a!r} != {b!r}")
        return
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                problems.append(f"{path}.{k}: missing in BEFORE")
            elif k not in b:
                problems.append(f"{path}.{k}: missing in AFTER")
            else:
                _diff(a[k], b[k], f"{path}.{k}", problems)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            problems.append(f"{path}: length {len(a)} != {len(b)}")
            return
        for i, (x, y) in enumerate(zip(a, b)):
            _diff(x, y, f"{path}[{i}]", problems)
        return
    if a != b:
        problems.append(f"{path}: {a!r} != {b!r}")


def compare(before_path: str, after_path: str) -> int:
    before = json.loads(Path(before_path).read_text())
    after = json.loads(Path(after_path).read_text())
    problems: list[str] = []
    _diff(before, after, "$", problems)
    if problems:
        print(f"GOLDEN MASTER MISMATCH — {len(problems)} difference(s):")
        for p in problems[:60]:
            print(f"  ✗ {p}")
        if len(problems) > 60:
            print(f"  … and {len(problems) - 60} more")
        return 1
    print("GOLDEN MASTER OK — before and after are identical "
          f"(float tol {FLOAT_TOL}).")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "capture":
        capture(sys.argv[2])
    elif len(sys.argv) >= 4 and sys.argv[1] == "compare":
        sys.exit(compare(sys.argv[2], sys.argv[3]))
    else:
        print(__doc__)
        sys.exit(2)
