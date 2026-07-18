"""
Risk limits framework — limits ARE parameters (JordanParams in the registry),
so they are GUI-editable, versioned, and stamped like everything else.
"""
from __future__ import annotations


def evaluate_limits(analysis: dict, params=None) -> dict:
    """
    analysis: output of systems.risk.book.analyze_book().
    Returns per-check results + a flat breaches list for banners/alerts.
    """
    from systems.params import get_params
    p = params or get_params("jordan")
    nav = float(p.nav)

    checks, breaches = {}, []

    def add(name: str, value: float, limit: float, label: str):
        breached = abs(value) > limit
        checks[name] = {
            "value": round(value, 4), "limit": limit,
            "utilization": round(abs(value) / limit, 3) if limit else None,
            "breached": breached, "label": label,
        }
        if breached:
            breaches.append(f"{name}: {label} at {abs(value):.1%} vs limit {limit:.1%}")

    add("net_delta", analysis["net_delta_dollars"] / nav,
        p.max_net_delta_pct, "net delta exposure / NAV")
    add("net_vega", analysis["net_vega_dollars"] / nav,
        p.max_net_vega_pct, "net vega ($/vol-pt) / NAV")

    oversized = []
    for a in analysis["analyses"]:
        frac = a["notional"] / nav
        if frac > p.max_single_position_pct:
            oversized.append({
                "id": a["position"].get("id"),
                "ticker": a["position"].get("ticker"),
                "notional_pct_nav": round(frac, 4),
            })
    checks["single_position"] = {
        "limit": p.max_single_position_pct,
        "breached": bool(oversized),
        "oversized": oversized,
        "label": "single position notional / NAV",
    }
    if oversized:
        names = ", ".join(f"{o['ticker']} ({o['notional_pct_nav']:.1%})"
                          for o in oversized)
        breaches.append(f"single_position: {names} exceed "
                        f"{p.max_single_position_pct:.1%} of NAV")

    checks["drawdown"] = {
        "breached": False,
        "label": "portfolio drawdown",
        "note": ("not evaluated — requires NAV history; lands with the "
                 "weekly-review P&L series (Phase 6)"),
        "alert_limit": p.drawdown_alert_pct,
        "halt_limit": p.drawdown_halt_pct,
    }

    breaches.extend(analysis.get("concentration_flags", []))

    return {
        "nav": nav,
        "checks": checks,
        "breaches": breaches,
        "ok": not breaches,
    }
