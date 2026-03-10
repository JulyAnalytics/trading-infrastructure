"""
Regime Classifier
-----------------
Takes current macro readings and produces a discrete regime state.
This is the single most important output of Phase 1 —
every downstream system queries this before making decisions.

Regime States (ordered from most to least risk-friendly):
  RISK_ON_LOW_VOL       — ideal conditions for short vol, carry, risk
  RISK_ON_ELEVATED_VOL  — growth OK but vol rising; be selective
  NEUTRAL               — no clear dominant signal
  CAUTION               — deteriorating conditions; reduce risk
  RISK_OFF_STRESS       — clear risk-off: credit wide, vol high
  CRISIS                — system-level stress (2008, 2020 type)

Usage:
    from signals.regime_classifier import RegimeClassifier
    clf = RegimeClassifier()
    result = clf.classify()
    print(result)
"""

import sys
import os
from dataclasses import dataclass, field
from datetime import date, datetime
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from config import REGIME_THRESHOLDS, DUCKDB_PATH
from systems.utils.db import get_connection, get_latest, get_series_history


# ── Data Types ────────────────────────────────────────────────────────────────

@dataclass
class MacroSnapshot:
    """Current readings for all regime inputs."""
    as_of:            date   = None
    vix:              float  = None
    vix_z1y:          float  = None
    hy_spread:        float  = None
    ig_spread:        float  = None
    yield_curve_10_2: float  = None   # bps
    yield_curve_10_3: float  = None   # bps
    breakeven_10y:    float  = None
    real_rate_10y:    float  = None
    unemployment:     float  = None
    unemp_delta_3m:   float  = None   # change over last 3 months
    nfp_3m_avg:       float  = None   # 3-month avg job adds (000s)
    m2_yoy:           float  = None
    jobless_claims:   float  = None
    claims_z1y:       float  = None
    oil_chg_3m:       float  = None   # % change
    cot_sp500_z:      float  = None   # z-score of spec positioning
    missing_inputs:   list   = field(default_factory=list)


@dataclass
class RegimeResult:
    """Full regime output including component scores."""
    regime:           str    = "NEUTRAL"
    composite_score:  float  = 0.0    # -1 (crisis) to +1 (risk-on)
    confidence:       str    = "LOW"  # LOW / MEDIUM / HIGH
    as_of:            date   = None

    # Component scores (-1 to +1 each)
    vol_score:        float  = 0.0
    credit_score:     float  = 0.0
    curve_score:      float  = 0.0
    inflation_score:  float  = 0.0
    labor_score:      float  = 0.0
    positioning_score: float = 0.0

    # Human-readable signal list
    bullish_signals:  list   = field(default_factory=list)
    bearish_signals:  list   = field(default_factory=list)
    warnings:         list   = field(default_factory=list)

    # Raw snapshot used
    snapshot:         MacroSnapshot = field(default_factory=MacroSnapshot)

    def __str__(self):
        lines = [
            f"═══ REGIME STATE: {self.regime} ═══",
            f"As of:     {self.as_of}",
            f"Score:     {self.composite_score:+.2f}  (confidence: {self.confidence})",
            f"",
            f"Component Scores:",
            f"  Vol:          {self.vol_score:+.2f}",
            f"  Credit:       {self.credit_score:+.2f}",
            f"  Yield Curve:  {self.curve_score:+.2f}",
            f"  Inflation:    {self.inflation_score:+.2f}",
            f"  Labor:        {self.labor_score:+.2f}",
            f"  Positioning:  {self.positioning_score:+.2f}",
        ]
        if self.bullish_signals:
            lines += ["", "✓ Bullish signals:"]
            lines += [f"  + {s}" for s in self.bullish_signals]
        if self.bearish_signals:
            lines += ["", "✗ Bearish signals:"]
            lines += [f"  - {s}" for s in self.bearish_signals]
        if self.warnings:
            lines += ["", "⚠ Warnings:"]
            lines += [f"  ! {w}" for w in self.warnings]
        return "\n".join(lines)


# ── Classifier ────────────────────────────────────────────────────────────────

class RegimeClassifier:
    """
    Scores each macro dimension on a -1 to +1 scale,
    combines them with weights, then maps the composite to a regime label.

    Weights are intentionally transparent — change them in config.py.
    """

    # Component weights — must sum to 1.0
    WEIGHTS = {
        "vol":         0.25,   # VIX is the fastest signal
        "credit":      0.25,   # HY spread is co-leading
        "curve":       0.20,   # yield curve is slower but powerful
        "inflation":   0.10,   # affects policy regime
        "labor":       0.15,   # unemployment is lagging but matters
        "positioning": 0.05,   # COT is noisy — low weight
    }

    # Composite score → regime mapping
    SCORE_TO_REGIME = [
        (+0.60, "RISK_ON_LOW_VOL"),
        (+0.25, "RISK_ON_ELEVATED_VOL"),
        (-0.10, "NEUTRAL"),
        (-0.40, "CAUTION"),
        (-0.65, "RISK_OFF_STRESS"),
        (-2.00, "CRISIS"),           # floor
    ]

    def __init__(self, db_path: str = DUCKDB_PATH):
        self.conn = get_connection()

    # ── Data Loading ──────────────────────────────────────────────────────────

    def _load_snapshot(self) -> MacroSnapshot:
        snap = MacroSnapshot()
        missing = []

        def latest(series_id: str) -> dict | None:
            return get_latest(self.conn, series_id)

        def val(series_id: str) -> float | None:
            row = latest(series_id)
            if row is None:
                missing.append(series_id)
                return None
            return row["value"]

        def z(series_id: str) -> float | None:
            row = latest(series_id)
            return row["z_1y"] if row else None

        snap.vix              = val("vix")
        snap.vix_z1y          = z("vix")
        snap.hy_spread        = val("hy_spread")
        snap.ig_spread        = val("ig_spread")
        snap.yield_curve_10_2 = val("yield_curve_10_2")
        snap.yield_curve_10_3 = val("yield_curve_10_3")
        snap.breakeven_10y    = val("breakeven_10y")
        snap.real_rate_10y    = val("real_rate_10y")
        snap.unemployment     = val("unemployment")
        snap.m2_yoy           = val("m2_yoy_growth")
        snap.jobless_claims   = val("jobless_claims")
        snap.claims_z1y       = z("jobless_claims")
        snap.oil_chg_3m       = latest("oil_wti")["chg_1m"] if latest("oil_wti") else None

        # Unemployment delta: compare last reading to 3 months ago
        unemp_hist = get_series_history(self.conn, "unemployment", lookback_days=180)
        if len(unemp_hist) >= 3:
            snap.unemp_delta_3m = (
                unemp_hist["value"].iloc[-1] - unemp_hist["value"].iloc[-3]
            )

        # COT SP500 z-score
        cot = self.conn.execute("""
            SELECT z_score_1y FROM cot_positioning
            WHERE instrument = 'SP500'
            ORDER BY date DESC LIMIT 1
        """).fetchone()
        if cot:
            snap.cot_sp500_z = cot[0]

        snap.missing_inputs = missing
        snap.as_of = date.today()
        return snap

    # ── Component Scorers  (-1 = bearish, 0 = neutral, +1 = bullish) ─────────

    def _score_vol(self, snap: MacroSnapshot) -> tuple[float, list, list]:
        """VIX level and trend."""
        bullish, bearish = [], []
        if snap.vix is None:
            return 0.0, bullish, bearish

        t = REGIME_THRESHOLDS["vix"]
        if snap.vix > t["crisis"]:
            score = -1.0
            bearish.append(f"VIX in CRISIS territory ({snap.vix:.1f} > {t['crisis']})")
        elif snap.vix > t["high"]:
            score = -0.6
            bearish.append(f"VIX elevated ({snap.vix:.1f})")
        elif snap.vix > t["medium"]:
            score = -0.2
            bearish.append(f"VIX above neutral ({snap.vix:.1f})")
        elif snap.vix < t["low"]:
            score = +1.0
            bullish.append(f"VIX low/complacent ({snap.vix:.1f})")
        else:
            score = +0.3
            bullish.append(f"VIX in normal range ({snap.vix:.1f})")

        # Adjust for z-score trend
        if snap.vix_z1y is not None:
            if snap.vix_z1y > 1.5:
                score -= 0.2
                bearish.append(f"VIX rising sharply (z={snap.vix_z1y:.1f})")
            elif snap.vix_z1y < -1.0:
                score += 0.1
                bullish.append(f"VIX declining trend (z={snap.vix_z1y:.1f})")

        return max(-1.0, min(1.0, score)), bullish, bearish

    def _score_credit(self, snap: MacroSnapshot) -> tuple[float, list, list]:
        """HY and IG credit spreads."""
        bullish, bearish = [], []
        if snap.hy_spread is None:
            return 0.0, bullish, bearish

        t = REGIME_THRESHOLDS["hy_spread"]
        if snap.hy_spread > t["crisis"]:
            score = -1.0
            bearish.append(f"HY spreads at crisis levels ({snap.hy_spread:.0f}bps)")
        elif snap.hy_spread > t["wide"]:
            score = -0.7
            bearish.append(f"HY spreads wide ({snap.hy_spread:.0f}bps)")
        elif snap.hy_spread > t["normal"]:
            score = -0.2
            bearish.append(f"HY spreads elevated ({snap.hy_spread:.0f}bps)")
        elif snap.hy_spread < t["tight"]:
            score = +1.0
            bullish.append(f"HY spreads historically tight ({snap.hy_spread:.0f}bps)")
        else:
            score = +0.4
            bullish.append(f"HY spreads normal ({snap.hy_spread:.0f}bps)")

        return max(-1.0, min(1.0, score)), bullish, bearish

    def _score_curve(self, snap: MacroSnapshot) -> tuple[float, list, list]:
        """Yield curve shape — powerful but lagging."""
        bullish, bearish = [], []
        t = REGIME_THRESHOLDS["yield_curve_10_2"]
        curve = snap.yield_curve_10_2

        if curve is None:
            return 0.0, bullish, bearish

        # Convert to bps if stored as %
        curve_bps = curve * 100 if abs(curve) < 5 else curve

        if curve_bps < t["inverted"]:
            score = -0.8
            bearish.append(f"Yield curve inverted ({curve_bps:.0f}bps) — recession risk")
        elif curve_bps < t["flat"]:
            score = -0.3
            bearish.append(f"Yield curve flat ({curve_bps:.0f}bps)")
        elif curve_bps > t["steep"]:
            score = +0.7
            bullish.append(f"Yield curve steep ({curve_bps:.0f}bps) — growth supportive")
        else:
            score = +0.2
            bullish.append(f"Yield curve normal ({curve_bps:.0f}bps)")

        # Also check 10y-3m (more predictive for recession per Fed research)
        if snap.yield_curve_10_3 is not None:
            c2 = snap.yield_curve_10_3 * 100 if abs(snap.yield_curve_10_3) < 5 else snap.yield_curve_10_3
            if c2 < 0:
                bearish.append(f"10Y-3M also inverted ({c2:.0f}bps) — confirms recession signal")
                score -= 0.1

        return max(-1.0, min(1.0, score)), bullish, bearish

    def _score_inflation(self, snap: MacroSnapshot) -> tuple[float, list, list]:
        """Inflation regime — affects Fed policy space."""
        bullish, bearish = [], []
        t = REGIME_THRESHOLDS["breakeven_10y"]
        be = snap.breakeven_10y

        if be is None:
            return 0.0, bullish, bearish

        if be > t["unanchored"]:
            score = -0.8
            bearish.append(f"Inflation expectations unanchored ({be:.2f}%)")
        elif be > t["elevated"]:
            score = -0.3
            bearish.append(f"Inflation expectations elevated ({be:.2f}%)")
        elif be < 1.5:
            score = -0.2                 # deflation risk is also bad
            bearish.append(f"Inflation expectations very low — deflation risk ({be:.2f}%)")
        else:
            score = +0.4
            bullish.append(f"Inflation expectations anchored ({be:.2f}%)")

        # Real rates: positive real rates are headwind for risk assets
        if snap.real_rate_10y is not None:
            if snap.real_rate_10y > 2.0:
                score -= 0.3
                bearish.append(f"Real rates restrictive ({snap.real_rate_10y:.2f}%)")
            elif snap.real_rate_10y < 0:
                score += 0.2
                bullish.append(f"Real rates negative — supportive for risk ({snap.real_rate_10y:.2f}%)")

        return max(-1.0, min(1.0, score)), bullish, bearish

    def _score_labor(self, snap: MacroSnapshot) -> tuple[float, list, list]:
        """Labor market conditions — lagging but crucial for policy."""
        bullish, bearish = [], []
        score = 0.0

        if snap.unemployment is not None:
            if snap.unemployment < 4.0:
                score += 0.4
                bullish.append(f"Unemployment low ({snap.unemployment:.1f}%)")
            elif snap.unemployment > 5.5:
                score -= 0.5
                bearish.append(f"Unemployment elevated ({snap.unemployment:.1f}%)")

        if snap.unemp_delta_3m is not None:
            t = REGIME_THRESHOLDS["unemployment_delta"]
            if snap.unemp_delta_3m > t["deteriorating"]:
                score -= 0.4
                bearish.append(
                    f"Unemployment rising fast (+{snap.unemp_delta_3m:.1f}pp in 3m)"
                )
            elif snap.unemp_delta_3m < t["improving"]:
                score += 0.3
                bullish.append(
                    f"Unemployment improving ({snap.unemp_delta_3m:.1f}pp in 3m)"
                )

        # Jobless claims z-score
        if snap.claims_z1y is not None:
            if snap.claims_z1y > 1.5:
                score -= 0.3
                bearish.append(
                    f"Jobless claims spiking (z={snap.claims_z1y:.1f})"
                )

        return max(-1.0, min(1.0, score)), bullish, bearish

    def _score_positioning(self, snap: MacroSnapshot) -> tuple[float, list, list]:
        """
        Contrarian: extreme long positioning is bearish (crowded),
        extreme short is bullish (squeezable).
        """
        bullish, bearish = [], []
        if snap.cot_sp500_z is None:
            return 0.0, bullish, bearish

        z = snap.cot_sp500_z
        if z > 2.0:
            score = -0.5
            bearish.append(f"SP500 specs extremely long (z={z:.1f}) — crowded")
        elif z < -2.0:
            score = +0.5
            bullish.append(f"SP500 specs extremely short (z={z:.1f}) — contrarian long")
        elif z > 1.0:
            score = -0.2
            bearish.append(f"SP500 specs leaning long (z={z:.1f})")
        elif z < -1.0:
            score = +0.2
            bullish.append(f"SP500 specs leaning short (z={z:.1f})")
        else:
            score = 0.0

        return score, bullish, bearish

    # ── Main Classify ─────────────────────────────────────────────────────────

    def classify(self, persist: bool = True) -> RegimeResult:
        """
        Run full classification. Returns RegimeResult.
        If persist=True, saves to regime_history table.
        """
        snap = self._load_snapshot()

        vol_score,   vol_bull,   vol_bear   = self._score_vol(snap)
        cred_score,  cred_bull,  cred_bear  = self._score_credit(snap)
        curv_score,  curv_bull,  curv_bear  = self._score_curve(snap)
        infl_score,  infl_bull,  infl_bear  = self._score_inflation(snap)
        lab_score,   lab_bull,   lab_bear   = self._score_labor(snap)
        pos_score,   pos_bull,   pos_bear   = self._score_positioning(snap)

        composite = (
            vol_score   * self.WEIGHTS["vol"]
            + cred_score  * self.WEIGHTS["credit"]
            + curv_score  * self.WEIGHTS["curve"]
            + infl_score  * self.WEIGHTS["inflation"]
            + lab_score   * self.WEIGHTS["labor"]
            + pos_score   * self.WEIGHTS["positioning"]
        )

        # Map score to regime
        regime = "CRISIS"   # default floor
        for threshold, label in self.SCORE_TO_REGIME:
            if composite >= threshold:
                regime = label
                break

        # Confidence: HIGH if 4+ components agree, LOW if split
        component_scores = [
            vol_score, cred_score, curv_score, infl_score, lab_score
        ]
        positives = sum(s > 0 for s in component_scores)
        negatives = sum(s < 0 for s in component_scores)
        agreement = max(positives, negatives) / len(component_scores)

        if agreement >= 0.8:
            confidence = "HIGH"
        elif agreement >= 0.6:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"

        result = RegimeResult(
            regime           = regime,
            composite_score  = round(composite, 3),
            confidence       = confidence,
            as_of            = snap.as_of,
            vol_score        = round(vol_score, 3),
            credit_score     = round(cred_score, 3),
            curve_score      = round(curv_score, 3),
            inflation_score  = round(infl_score, 3),
            labor_score      = round(lab_score, 3),
            positioning_score= round(pos_score, 3),
            bullish_signals  = vol_bull + cred_bull + curv_bull + infl_bull + lab_bull + pos_bull,
            bearish_signals  = vol_bear + cred_bear + curv_bear + infl_bear + lab_bear + pos_bear,
            warnings         = [f"Missing data: {s}" for s in snap.missing_inputs],
            snapshot         = snap,
        )

        if persist:
            self._persist(result)

        return result

    def _persist(self, result: RegimeResult):
        """Save regime result to history table."""
        snap = result.snapshot
        self.conn.execute("""
            INSERT OR REPLACE INTO regime_history
                (date, regime, regime_score, vix, hy_spread, yield_curve,
                 breakeven_10y, unemp_delta, composite_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            result.as_of,
            result.regime,
            result.composite_score,
            snap.vix,
            snap.hy_spread,
            snap.yield_curve_10_2,
            snap.breakeven_10y,
            snap.unemp_delta_3m,
            result.composite_score,
        ])

    def get_history(self, lookback_days: int = 252) -> pd.DataFrame:
        """Return regime history as a DataFrame for charting."""
        return self.conn.execute("""
            SELECT date, regime, composite_score,
                   vix, hy_spread, yield_curve, breakeven_10y
            FROM regime_history
            WHERE date >= current_date - INTERVAL (?) DAY
            ORDER BY date ASC
        """, [lookback_days]).df()

    def __del__(self):
        try:
            self.conn.close()
        except Exception:
            pass


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    clf = RegimeClassifier()
    result = clf.classify()
    print(result)
