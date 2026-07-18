"""
Book-level stress testing — reuses Sarah's scenario engine (and therefore the
user-editable stress library in the registry) across every analyzed position.

Endpoint approximation, same caveats as the single-position engine: vol
shocks are absolute vol points; paths are not reconstructed.
"""
from __future__ import annotations

from loguru import logger


def stress_book(analysis: dict) -> dict:
    """
    analysis: output of systems.risk.book.analyze_book().
    Returns per-scenario portfolio P&L (flat + skew-amplified) with
    per-position contributions.
    """
    from systems.sarah.scenario_engine import ScenarioEngine
    eng = ScenarioEngine()
    library = eng.stress_scenario_library()

    scenarios = {}
    for key, meta in library.items():
        total_flat = total_skew = 0.0
        contributions = []
        for a in analysis["analyses"]:
            pos = a["position"]
            try:
                if pos["asset_type"] == "option":
                    engine_pos = {
                        "market": {
                            "spot": a["market"]["spot"],
                            "iv": a["market"]["iv"],
                            "dte": a["market"]["dte"],
                            "rate": a["market"]["rate"],
                            "div_yield": a["market"]["div_yield"],
                        },
                        "position": {
                            "strike": pos["strike"], "flag": pos["flag"],
                            "quantity": pos["quantity"],
                            "long_short": pos["long_short"],
                        },
                        "greeks": {"delta": a["greeks_scaled"]["delta"]
                                   / (pos["quantity"] * 100)
                                   * (1 if pos["long_short"] == "long" else -1)},
                    }
                    r = eng.stress_scenario_pnl(engine_pos, key)
                    flat, skew = r["pnl_flat_shift"], r["pnl_skew_amplified"]
                else:
                    # Equity: linear P&L on the spot shock.
                    flat = skew = round(
                        a["delta_dollars"] * float(meta["spot_shock"]), 2)
                total_flat += flat
                total_skew += skew
                contributions.append({
                    "id": pos.get("id"), "ticker": pos.get("ticker"),
                    "pnl_flat": flat, "pnl_skew": skew,
                })
            except Exception as e:
                logger.warning(f"stress {key} failed for {pos.get('id')}: {e}")
                contributions.append({
                    "id": pos.get("id"), "ticker": pos.get("ticker"),
                    "error": str(e),
                })
        scenarios[key] = {
            "label": meta.get("label", key),
            "spot_shock": meta.get("spot_shock"),
            "vol_shock_vpts": meta.get("vol_shock_vpts"),
            "duration": meta.get("duration"),
            "pnl_flat": round(total_flat, 2),
            "pnl_skew_amplified": round(total_skew, 2),
            "contributions": contributions,
        }

    worst = min(scenarios.values(), key=lambda s: s["pnl_skew_amplified"]) \
        if scenarios else None
    return {
        "scenarios": scenarios,
        "worst_case": {"label": worst["label"],
                       "pnl_skew_amplified": worst["pnl_skew_amplified"]}
        if worst else None,
        "methodology_note": ("Endpoint approximation via ScenarioEngine; "
                             "equities linear in spot shock; vol shocks are "
                             "ABSOLUTE vol points."),
    }
