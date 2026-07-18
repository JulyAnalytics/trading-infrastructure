"""
Marcus 1.0 analytics layer — implements priorities 1–5 of
macro_system_architecture_improvements.md (Gaps 1, 3, 4, 5; Gap 7 handled in
the classifier/params migration):

  Gap 1 — MacroStateVector + RegimeGeometry + historical nearest-neighbours
  Gap 3 — RegimeFragilityAssessment (fragility-first hierarchy)
  Gap 4 — SignalInterpreter MVP (vol + credit conditional headlines)
  Gap 5 — RegimeImplicationSummary (regime return stats promoted, with caveat)

Design: every function here is PURE — callers (API routes, jobs) supply the
regime rows / return-stat rows; nothing in this module opens a database.
That keeps it unit-testable and lets the GUI preview alternative inputs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import date

COMPONENT_KEYS = ("vol", "credit", "curve", "inflation", "labor", "positioning")
_SCORE_COLS = {c: f"{c}_score" for c in COMPONENT_KEYS}


def _scores_from_row(row: dict) -> "dict[str, float]":
    return {c: float(row.get(col) or 0.0) for c, col in _SCORE_COLS.items()}


# ── Gap 1: vector state ──────────────────────────────────────────────────────

@dataclass
class MacroStateVector:
    """Preserved six-component state; the regime label is an annotation."""
    vol_score: float
    credit_score: float
    curve_score: float
    inflation_score: float
    labor_score: float
    positioning_score: float

    # Derived sub-composites — compute several, never collapse to one
    financial_conditions_score: float = 0.0   # vol + credit (market-facing)
    real_economy_score: float = 0.0           # labor + curve (fundamental)
    nominal_score: float = 0.0                # inflation

    distance_to_stress: float = 0.0           # composite units to CAUTION floor
    distance_to_crisis: float = 0.0           # composite units to CRISIS floor

    regime_label: str = "NEUTRAL"
    regime_confidence: str = "LOW"
    composite_score: float = 0.0
    component_as_of: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def build_state_vector(row: dict, marcus_params) -> MacroStateVector:
    """row: a regime_history row (dict). marcus_params: MarcusParams."""
    s = _scores_from_row(row)
    composite = float(row.get("composite_score") or 0.0)
    floors = {label: thr for thr, label in
              (tuple(r) for r in marcus_params.score_to_regime)}
    caution_floor = floors.get("CAUTION", -0.40)
    stress_floor = floors.get("RISK_OFF_STRESS", -0.65)
    return MacroStateVector(
        vol_score=s["vol"], credit_score=s["credit"], curve_score=s["curve"],
        inflation_score=s["inflation"], labor_score=s["labor"],
        positioning_score=s["positioning"],
        financial_conditions_score=round((s["vol"] + s["credit"]) / 2, 3),
        real_economy_score=round((s["labor"] + s["curve"]) / 2, 3),
        nominal_score=round(s["inflation"], 3),
        distance_to_stress=round(composite - caution_floor, 3),
        distance_to_crisis=round(composite - stress_floor, 3),
        regime_label=row.get("regime", "NEUTRAL"),
        regime_confidence=row.get("confidence") or "LOW",
        composite_score=composite,
        component_as_of={
            c: str(row.get(f"{c}_as_of"))[:10] if row.get(f"{c}_as_of") else None
            for c in COMPONENT_KEYS
        },
    )


def nearest_neighbours(
    current_row: dict,
    history_rows: "list[dict]",
    k: int = 5,
    exclude_trailing_days: int = 252,
) -> "list[dict]":
    """
    Euclidean nearest neighbours over the six component scores, excluding the
    trailing window so the present doesn't trivially match itself.
    history_rows: regime_history rows (dicts with date + *_score + regime).
    """
    cur = _scores_from_row(current_row)
    cur_date = date.fromisoformat(str(current_row["date"])[:10])
    out = []
    for row in history_rows:
        d = date.fromisoformat(str(row["date"])[:10])
        if (cur_date - d).days < exclude_trailing_days:
            continue
        other = _scores_from_row(row)
        dist = math.sqrt(sum((cur[c] - other[c]) ** 2 for c in COMPONENT_KEYS))
        out.append({
            "date": str(row["date"])[:10],
            "regime": row.get("regime"),
            "composite_score": row.get("composite_score"),
            "distance": round(dist, 4),
            "similarity": round(1.0 / (1.0 + dist), 4),
            "scores": other,
        })
    out.sort(key=lambda r: r["distance"])
    return out[:k]


def regime_geometry(row: dict, neighbours: "list[dict]") -> dict:
    """Shape of the current configuration (Gap 1 RegimeGeometry)."""
    s = _scores_from_row(row)
    composite = float(row.get("composite_score") or 0.0)
    direction = 1 if composite >= 0 else -1
    aligned = [c for c in COMPONENT_KEYS if s[c] * direction > 0]
    contradicting = [c for c in COMPONENT_KEYS if s[c] * direction < 0 and s[c] != 0]

    # Coherence: 1 − normalized dispersion of the five fundamental components
    fundamentals = [s[c] for c in COMPONENT_KEYS if c != "positioning"]
    spread = max(fundamentals) - min(fundamentals)
    coherence = round(max(0.0, 1.0 - spread / 2.0), 3)

    if s["credit"] < -0.3 and s["vol"] > 0:
        config_type = "CREDIT_LED_STRESS"
    elif s["vol"] < -0.3 and s["credit"] > 0:
        config_type = "VOL_SPIKE_UNCONFIRMED"
    elif all(s[c] > 0 for c in ("vol", "credit", "curve")):
        config_type = "BROAD_RISK_ON"
    elif all(s[c] < 0 for c in ("vol", "credit", "curve")):
        config_type = "BROAD_RISK_OFF"
    else:
        config_type = "MIXED"

    return {
        "aligned_components": aligned,
        "contradicting_components": contradicting,
        "regime_coherence_score": coherence,
        "configuration_type": config_type,
        "nearest_historical_analogues": neighbours,
    }


# ── Gap 3: fragility-first ───────────────────────────────────────────────────

def fragility_assessment(
    row: dict,
    history_rows: "list[dict]",
    transition_probability: "dict | None",
) -> dict:
    """
    Fragility mapping per the improvements doc:
      STABLE   — no active divergence and p_transition < 15%
      WATCH    — active divergence or p_transition 15–30%
      FRAGILE  — p_transition > 30% (with or without divergence)
      BREAKING — composite moved > 0.15 in 7 days
    Plus 7-day component trends and divergence duration (DivergenceTimeline).
    """
    p = float((transition_probability or {}).get("probability") or 0.0)
    divergence_type = row.get("divergence_type")

    ordered = sorted(history_rows, key=lambda r: str(r["date"]))
    trends = {}
    delta_7d = 0.0
    if len(ordered) >= 2:
        recent = ordered[-7:] if len(ordered) >= 7 else ordered
        first, last = recent[0], recent[-1]
        delta_7d = float(last.get("composite_score") or 0) - \
                   float(first.get("composite_score") or 0)
        for c in ("vol", "credit", "inflation"):
            col = _SCORE_COLS[c]
            trends[f"{c}_trend_7d"] = round(
                float(last.get(col) or 0) - float(first.get(col) or 0), 3)

    # Divergence duration: consecutive most-recent days with the same type
    onset, days_active = None, 0
    if divergence_type:
        for r in reversed(ordered):
            if r.get("divergence_type") == divergence_type:
                onset = str(r["date"])[:10]
                days_active += 1
            else:
                break

    if abs(delta_7d) > 0.15:
        level, score = "BREAKING", 0.95
    elif p > 0.30:
        level, score = "FRAGILE", min(0.5 + p / 2, 0.9)
    elif divergence_type or p >= 0.15:
        level, score = "WATCH", max(0.35, p)
    else:
        level, score = "STABLE", max(0.05, p / 2)

    severity_trend = None
    if divergence_type and days_active >= 2:
        severity_trend = "INTENSIFYING" if delta_7d < -0.03 else \
                         "RESOLVING" if delta_7d > 0.03 else "STABLE"

    return {
        "fragility_level": level,
        "fragility_score": round(score, 2),
        "active_divergence": {
            "type": divergence_type,
            "severity": row.get("divergence_severity"),
            "onset_date": onset,
            "days_active": days_active,
            "severity_trend": severity_trend,
        } if divergence_type else None,
        "composite_delta_7d": round(delta_7d, 3),
        "component_trends_7d": trends,
        "p_transition_30d": transition_probability,
    }


# ── Gap 5: regime implications ───────────────────────────────────────────────

def implication_summary(
    regime: str,
    return_stats_rows: "list[dict]",
    geometry: "dict | None" = None,
    horizon: str = "1M",
) -> dict:
    """
    RegimeImplicationSummary from regime_return_stats rows
    (regime, asset, horizon, median_return, p25_return, p75_return, n_observations).
    """
    rows = [r for r in return_stats_rows
            if r.get("regime") == regime and r.get("horizon") == horizon]
    all_rows = [r for r in return_stats_rows if r.get("horizon") == horizon]

    all_regime_median: "dict[str, list[float]]" = {}
    for r in all_rows:
        all_regime_median.setdefault(r["asset"], []).append(float(r["median_return"]))

    implications = []
    min_n = None
    for r in sorted(rows, key=lambda x: -float(x["median_return"])):
        n = int(r.get("n_observations") or 0)
        min_n = n if min_n is None else min(min_n, n)
        med = float(r["median_return"])
        baseline = sorted(all_regime_median.get(r["asset"], [med]))
        base = baseline[len(baseline) // 2]
        implications.append({
            "asset": r["asset"],
            "median_return": round(med, 4),
            "vs_all_regime_median": round(med - base, 4),
            "percentile_range": [round(float(r["p25_return"]), 4),
                                 round(float(r["p75_return"]), 4)],
            "n_observations": n,
            "low_sample": n < 20,
        })

    if min_n is None:
        reliability = "NO_DATA"
    elif min_n > 40:
        reliability = f"HIGH (n>{min_n - 1})"
    elif min_n >= 20:
        reliability = f"MODERATE (n={min_n})"
    else:
        reliability = f"LOW (n={min_n})"

    headline = None
    if implications:
        best = implications[0]
        worst = implications[-1]
        headline = (
            f"{regime} regimes have historically favoured {best['asset']} "
            f"({best['median_return'] * 100:+.1f}% median {horizon}) and penalised "
            f"{worst['asset']} ({worst['median_return'] * 100:+.1f}%)."
        )

    caveat = None
    if geometry:
        analogues = geometry.get("nearest_historical_analogues") or []
        same_label = [a for a in analogues if a.get("regime") == regime]
        if analogues and len(same_label) < len(analogues) / 2:
            caveat = (
                "Current configuration resembles historical instances of OTHER "
                "regime labels more than typical instances of its own label — "
                "these return statistics may not be representative."
            )
        elif geometry.get("regime_coherence_score", 1.0) < 0.4:
            caveat = (
                "Low internal coherence: components disagree strongly. Historical "
                f"{regime} averages blend very different configurations."
            )

    return {
        "regime": regime,
        "horizon": horizon,
        "asset_implications": implications,
        "headline_implication": headline,
        "sample_reliability": reliability,
        "caveat": caveat,
    }


# ── Gap 4: interpreter MVP (vol + credit) ────────────────────────────────────

def _severity(score: float) -> str:
    a = abs(score)
    if a >= 0.8:
        return "EXTREME"
    if a >= 0.5:
        return "ELEVATED"
    if a >= 0.2:
        return "NOTABLE"
    return "BENIGN"


def interpret_components(row: dict, marcus_params) -> "list[dict]":
    """
    Conditional interpretations for the two highest-weight components.
    Each answers: what is it saying, does it agree with the regime, and what
    would change the read (watch_condition — the falsifier).
    """
    s = _scores_from_row(row)
    regime = row.get("regime", "NEUTRAL")
    risk_on = "RISK_ON" in regime or regime == "NEUTRAL"
    vix = row.get("vix")
    hy = row.get("hy_spread")
    t = marcus_params.regime_thresholds

    out = []

    # Vol
    vol = s["vol"]
    aligned = (vol >= 0) == risk_on
    vix_txt = f"VIX {float(vix):.1f}" if vix is not None else "VIX unavailable"
    if vol >= 0:
        headline = f"{vix_txt}: volatility is contained and supportive of risk-taking."
    else:
        headline = f"{vix_txt}: volatility is signalling stress (score {vol:+.2f})."
    regime_context = (
        f"Consistent with the {regime} classification."
        if aligned else
        f"CONTRADICTS the {regime} classification — this is the configuration "
        f"that historically precedes regime deterioration when credit confirms."
    )
    watch = (
        f"Watch VIX above {t['vix']['high']:.0f} (elevated) and "
        f"{t['vix']['crisis']:.0f} (crisis); a close above "
        f"{t['vix']['medium']:.0f} flips the component negative."
        if vol >= 0 else
        f"A sustained move back below {t['vix']['medium']:.0f} would neutralise "
        f"the vol drag; below {t['vix']['low']:.0f} turns it supportive."
    )
    out.append({"component": "vol", "score": vol, "severity": _severity(vol),
                "aligned": aligned, "headline": headline,
                "regime_context": regime_context, "watch_condition": watch})

    # Credit
    credit = s["credit"]
    aligned = (credit >= 0) == risk_on
    hy_txt = f"HY OAS {float(hy):.0f}bps" if hy is not None else "HY spread unavailable"
    if credit >= 0:
        headline = f"{hy_txt}: credit markets are calm — borrowers face no stress premium."
    else:
        headline = f"{hy_txt}: credit is pricing stress (score {credit:+.2f})."
    regime_context = (
        f"Consistent with the {regime} classification."
        if aligned else
        f"CONTRADICTS the {regime} classification. Credit tends to LEAD vol by "
        f"days to weeks — treat this as the earlier signal."
    )
    watch = (
        f"Watch HY OAS above {t['hy_spread']['normal']:.0f}bps (elevated) and "
        f"{t['hy_spread']['wide']:.0f}bps (stress) — widening there activates "
        f"LEADING_STRESS_WARNING if vol stays calm."
        if credit >= 0 else
        f"Spreads back inside {t['hy_spread']['normal']:.0f}bps would lift the "
        f"credit drag; inside {t['hy_spread']['tight']:.0f}bps turns it a tailwind."
    )
    out.append({"component": "credit", "score": credit, "severity": _severity(credit),
                "aligned": aligned, "headline": headline,
                "regime_context": regime_context, "watch_condition": watch})

    return out
