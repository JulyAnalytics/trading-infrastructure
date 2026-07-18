"""
Phase 0 verification — parameter registry + config facade + classifier wiring.

Self-contained: runs the registry against a TEMPORARY database (config.VOL_DB_PATH
is monkeypatched), so trading.db is never touched. No network access.

Usage:
    python scripts/verify_v1_platform.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from systems import params as P  # noqa: E402

PASS, FAIL = 0, 0


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}  {detail}")


def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="params_verify_")
    tmp_db = str(Path(tmpdir) / "verify_params.db")
    original_db = config.VOL_DB_PATH
    config.VOL_DB_PATH = tmp_db
    P.invalidate_cache()

    try:
        print("── Registry: seeding ──")
        marcus = P.get_params("marcus")
        active = P.get_active("marcus")
        check("seed-on-first-use returns defaults",
              marcus.component_weights["vol"] == 0.25)
        check("seed creates version 1", active.version == 1, f"got {active.version}")
        check("hash is 12 hex chars",
              len(active.hash) == 12 and all(c in "0123456789abcdef" for c in active.hash))

        print("── Registry: versioned edits ──")
        v1_hash = active.hash
        updated = P.set_params("marcus", {"divergence_threshold_vc": 0.55},
                               note="verify: edit")
        check("edit creates version 2", updated.version == 2)
        check("edit changes hash", updated.hash != v1_hash)
        check("get_params reflects edit immediately",
              P.get_params("marcus").divergence_threshold_vc == 0.55)
        check("unchanged fields preserved through edit",
              P.get_params("marcus").component_weights["credit"] == 0.25)

        print("── Registry: validation ──")
        try:
            P.set_params("marcus", {"component_weights": {
                "vol": 0.5, "credit": 0.5, "curve": 0.5,
                "inflation": 0.0, "labor": 0.0, "positioning": 0.0}})
            check("rejects weights not summing to 1.0", False)
        except ValueError as e:
            check("rejects weights not summing to 1.0", "sum" in str(e))
        try:
            P.set_params("marcus", {"divergence_threshold_vc": 99.0})
            check("rejects out-of-bounds scalar", False)
        except ValueError:
            check("rejects out-of-bounds scalar", True)
        try:
            P.set_params("sarah", {"stress_scenarios": {"broken": {"label": "x"}}})
            check("rejects malformed stress scenario", False)
        except ValueError:
            check("rejects malformed stress scenario", True)
        try:
            P.set_params("nonsense", {})
            check("rejects unknown component", False)
        except KeyError:
            check("rejects unknown component", True)

        print("── Registry: history + rollback ──")
        history = P.get_history("marcus")
        check("history has 2 versions", len(history) == 2, f"got {len(history)}")
        check("exactly one active version",
              sum(1 for h in history if h["active"]) == 1)
        rolled = P.activate_version("marcus", 1, note="verify: rollback")
        check("rollback restores v1 payload hash", rolled.hash == v1_hash)
        check("rollback is a NEW version (audit trail)", rolled.version == 3)
        check("rolled-back value live",
              P.get_params("marcus").divergence_threshold_vc == 0.6)

        print("── Registry: guarded gate edits ──")
        g = P.set_params("priya", {"backtest_dsr_accept_threshold": 0.90},
                         note="verify: guarded edit")
        check("guarded edit allowed but versioned", g.version >= 2)
        P.activate_version("priya", 1, note="verify: restore gates")

        print("── Config facade ──")
        check("REGIME_THRESHOLDS resolves",
              config.REGIME_THRESHOLDS["vix"]["crisis"] == 35.0)
        check("COMPONENT_WEIGHTS resolves",
              abs(sum(config.COMPONENT_WEIGHTS.values()) - 1.0) < 1e-9)
        check("CATALYST_TYPES is a tuple", isinstance(config.CATALYST_TYPES, tuple))
        check("FRACDIFF_D_RANGE is a tuple",
              config.FRACDIFF_D_RANGE == (0.0, 1.0))
        check("SHARPE_NEWEY_WEST_LAGS is a list",
              config.SHARPE_NEWEY_WEST_LAGS == [3, 6])
        check("facade returns copies (mutation-safe)",
              (config.COMPONENT_WEIGHTS is not config.COMPONENT_WEIGHTS))
        try:
            config.NOT_A_REAL_CONSTANT
            check("unknown config name raises AttributeError", False)
        except AttributeError:
            check("unknown config name raises AttributeError", True)
        missing = []
        for name in P.LEGACY_CONFIG_MAP:
            try:
                getattr(config, name)
            except Exception:
                missing.append(name)
        check(f"all {len(P.LEGACY_CONFIG_MAP)} legacy names resolve",
              not missing, f"failed: {missing[:5]}")

        print("── Run stamping ──")
        hashes = P.all_active_hashes()
        check("all_active_hashes covers all components",
              set(hashes) == set(P.COMPONENTS))

        print("── Classifier wiring ──")
        from systems.signals.regime_classifier import RegimeClassifier, RegimeResult
        bad = P.MarcusParams(component_weights={
            "vol": 0.5, "credit": 0.5, "curve": 0.5,
            "inflation": 0.0, "labor": 0.0, "positioning": 0.0})
        try:
            RegimeClassifier(db_path=":memory:", params=bad)
            check("classifier asserts weight sum", False)
        except ValueError:
            check("classifier asserts weight sum", True)
        clf = RegimeClassifier(db_path=":memory:")
        check("classifier binds active params",
              clf.params.divergence_threshold_vc == 0.6)
        r = RegimeResult(composite_score=0.30, params=clf.params)
        attr = r.attribution()
        check("attribution uses bound params",
              attr["nearest_regime"] in ("RISK_ON_LOW_VOL", "NEUTRAL"))
        clf.conn.close()

        print("── Scenario engine wiring ──")
        from systems.sarah.scenario_engine import ScenarioEngine
        eng = ScenarioEngine()
        lib = eng.stress_scenario_library()
        check("stress library has 6 shipped scenarios", len(lib) == 6,
              f"got {sorted(lib)}")
        custom = P.SarahParams()
        custom.stress_scenarios = {
            "custom_1": {"label": "Custom", "spot_shock": -0.10,
                         "vol_shock_vpts": 10.0, "duration": "1w",
                         "character": "verify"}}
        eng2 = ScenarioEngine(params=custom)
        check("engine honors injected params (custom scenario library)",
              list(eng2.stress_scenario_library()) == ["custom_1"])
        pos = {
            "market": {"spot": 100.0, "iv": 20.0, "dte": 30, "rate": 0.04,
                       "div_yield": 0.0, "forward": 100.3},
            "position": {"strike": 100.0, "flag": "c", "quantity": 1,
                         "long_short": "long"},
            "greeks": {"delta": 0.5},
        }
        res = eng2.stress_scenario_pnl(pos, "custom_1")
        check("custom scenario prices", isinstance(res["pnl_flat_shift"], float))
        kill = eng.kill_scenario(pos)
        check("kill scenario uses registry defaults",
              kill["kill_conditions"]["iv_compression_vpts"] == 8.0
              and kill["kill_conditions"]["days_elapsed"] == 30)

        print("── Fallback resilience ──")
        config.VOL_DB_PATH = str(Path(tmpdir) / "nonexistent_dir_x" / "no.db")
        P.invalidate_cache()
        fb = P.get_params("marcus")
        check("registry-unavailable falls back to defaults (no crash)",
              fb.divergence_threshold_vc == 0.6)

    finally:
        config.VOL_DB_PATH = original_db
        P.invalidate_cache()

    print(f"\n{'='*46}\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
