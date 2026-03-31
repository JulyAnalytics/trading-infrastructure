"""
Stage 4: Pre-Trade Intelligence Dashboard.

Design principle: The dashboard describes what the market is pricing.
The trader brings the thesis. These two things are compared — they are
not merged into a recommendation.

No directional labels. No "bullish/bearish" language.
Cost basis characterization only.

Panels 1–3: Task 004
Panels 4–5 + structure comparison + memo: Task 005
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
from datetime import datetime
from loguru import logger

from config import (
    OUTPUTS_DIR, VOL_DB_PATH, CATALYST_TYPES,
    MAX_FLOW_NOTES_LENGTH, FRED_RISK_FREE_SERIES
)
from systems.utils.db import get_connection
from systems.utils.pricing import forward_price, bs_price


# ── Data Classes ──────────────────────────────────────────────────────────────

@dataclass
class TradeThesisInput:
    """
    User-provided thesis parameters. No direction label.
    expected_move is UNSIGNED magnitude (e.g. 0.12 for ±12%).
    expected_move_sign is optional (+1 or -1) — used only for skew cost calc.
    """
    ticker:            str
    expected_move:     float      # magnitude in decimal, UNSIGNED (e.g. 0.12)
    thesis_days:       int        # holding period in calendar days
    catalyst_type:     str        # one of CATALYST_TYPES
    max_loss_budget:   float      # max acceptable loss per contract in dollars
    expected_move_sign: Optional[int] = None  # +1 or -1 if directional; None = symmetric

    def __post_init__(self):
        assert self.expected_move >= 0, "expected_move must be unsigned (≥0)"
        assert self.catalyst_type in CATALYST_TYPES, \
            f"catalyst_type must be one of {CATALYST_TYPES}, got '{self.catalyst_type}'"
        if self.expected_move_sign is not None:
            assert self.expected_move_sign in (+1, -1), \
                "expected_move_sign must be +1, -1, or None"


@dataclass
class FlowObservation:
    """
    Structured entry of UW or equivalent flow observation.
    Replaces free-text field from v2.0.
    The structure forces explicit categorization of what flow is showing.

    flow_panel() implementation is in Task 005.
    """
    ticker:               str
    observation_date:     str        # 'YYYY-MM-DD'
    flow_type:            str        # 'calls' | 'puts' | 'mixed'
    execution_type:       str        # 'sweep' | 'block' | 'spread' | 'unknown'
    size_contracts:       int        # approximate contract count
    expiration_dte:       int        # days to expiration of the flow
    strike_delta_approx:  float      # approximate delta of struck options (e.g. 0.30)
    vs_avg_volume:        str        # 'below_avg' | 'avg' | '2x_avg' | '5x_avg' | '10x_plus'
    notes:                str = ""   # free text limited to MAX_FLOW_NOTES_LENGTH

    def __post_init__(self):
        assert self.flow_type in ('calls', 'puts', 'mixed'), \
            f"flow_type must be calls/puts/mixed, got '{self.flow_type}'"
        assert self.execution_type in ('sweep', 'block', 'spread', 'unknown'), \
            f"execution_type must be sweep/block/spread/unknown, got '{self.execution_type}'"
        assert self.vs_avg_volume in ('below_avg', 'avg', '2x_avg', '5x_avg', '10x_plus'), \
            f"vs_avg_volume invalid: '{self.vs_avg_volume}'"
        if len(self.notes) > MAX_FLOW_NOTES_LENGTH:
            logger.warning(
                "FlowObservation notes truncated from {} to {} chars",
                len(self.notes), MAX_FLOW_NOTES_LENGTH
            )
            self.notes = self.notes[:MAX_FLOW_NOTES_LENGTH]


# ── Helper: Fetch latest vol signals from trading.db ──────────────────────────

def _get_latest_signals(ticker: str) -> Optional[dict]:
    """
    Fetch the most recent vol_signals row for ticker from trading.db.
    Returns dict of all columns, or None if no data.
    """
    conn = get_connection(VOL_DB_PATH)
    try:
        row = conn.execute(
            "SELECT * FROM vol_signals WHERE ticker = ? ORDER BY date DESC LIMIT 1",
            [ticker]
        ).fetchone()
        if row is None:
            return None
        cols = [desc[0] for desc in conn.description]
        return dict(zip(cols, row))
    finally:
        conn.close()


def _get_signal_history(ticker: str, column: str, days: int = 252) -> pd.Series:
    """
    Fetch historical values for a single column from vol_signals.
    Returns pd.Series indexed by date.
    """
    conn = get_connection(VOL_DB_PATH)
    try:
        df = conn.execute(
            f"SELECT date, {column} FROM vol_signals "
            f"WHERE ticker = ? AND {column} IS NOT NULL "
            f"ORDER BY date DESC LIMIT ?",
            [ticker, days]
        ).fetchdf()
        if df.empty:
            return pd.Series(dtype=float)
        return df.set_index('date')[column].sort_index()
    finally:
        conn.close()


# ── Panel 1: Vol Level ────────────────────────────────────────────────────────

def vol_level_panel(thesis: TradeThesisInput, signals: dict) -> dict:
    """
    Cost basis characterization of current vol level.
    No directional inference — cost numbers ARE the verdict.

    Args:
        thesis: TradeThesisInput from user
        signals: Latest vol_signals row as dict (from _get_latest_signals)

    Returns:
        Dict with vol level metrics and cost basis interpretation.
    """
    atm_iv = signals.get('atm_iv_30d', 0.0)
    iv_rank = signals.get('iv_rank', 0.0)
    iv_pctile = signals.get('iv_percentile', 0.0)
    ivr_confidence = signals.get('ivr_ivp_confidence', 'unknown')
    regime_bias = signals.get('ivr_regime_bias')

    # Daily theta cost at ATM: approximate via BS theta
    # theta ≈ −(S × σ × N'(d1)) / (2 × √T) for ATM where d1 ≈ 0
    spot = signals.get('spot_price', 0.0)
    T = thesis.thesis_days / 365.0
    sigma = atm_iv / 100.0 if atm_iv > 0 else 0.01

    # N'(0) = 1/√(2π) ≈ 0.3989
    daily_theta_approx = -(spot * sigma * 0.3989) / (2 * np.sqrt(T) * 365.0) if T > 0 else 0.0

    # Monthly cost-of-carry: vol points absorbed by theta over 30 days
    monthly_carry_vpts = sigma * 100 * (1 - np.sqrt(max(0, (T * 365 - 30)) / (T * 365))) \
        if T > 0 and T * 365 > 30 else atm_iv

    # Break-even move by expiration: ≈ ATM straddle value / spot
    # Straddle ≈ 2 × ATM_call ≈ 2 × S × σ × √T × N'(0) / N(0)
    # Simplified: BE ≈ σ × √T × √(2/π) ≈ σ × √T × 0.7979
    be_move_pct = sigma * np.sqrt(T) * 0.7979 * 100 if T > 0 else 0.0

    # 52-week IV range from history
    iv_history = _get_signal_history(thesis.ticker, 'atm_iv_30d', 252)
    iv_52w_low = float(iv_history.min()) if len(iv_history) > 0 else None
    iv_52w_high = float(iv_history.max()) if len(iv_history) > 0 else None
    iv_52w_pctile = (
        float((iv_history < atm_iv).sum() / len(iv_history) * 100)
        if len(iv_history) > 20 else None
    )

    # Cost burden qualifier (no directional label)
    if iv_52w_pctile is not None:
        if iv_52w_pctile < 25:
            cost_burden = "low"
        elif iv_52w_pctile < 75:
            cost_burden = "moderate"
        else:
            cost_burden = "high"
    else:
        cost_burden = "insufficient history"

    return {
        'atm_iv_30d':         atm_iv,
        'iv_rank':            iv_rank,
        'iv_percentile':      iv_pctile,
        'ivr_confidence':     ivr_confidence,
        'regime_bias':        regime_bias,
        'daily_theta_approx': round(daily_theta_approx, 2),
        'monthly_carry_vpts': round(monthly_carry_vpts, 2),
        'be_move_pct':        round(be_move_pct, 2),
        'iv_52w_low':         round(iv_52w_low, 2) if iv_52w_low is not None else None,
        'iv_52w_high':        round(iv_52w_high, 2) if iv_52w_high is not None else None,
        'iv_52w_pctile':      round(iv_52w_pctile, 1) if iv_52w_pctile is not None else None,
        'cost_burden':        cost_burden,
        'data_warning':       '⚠ Data: yfinance 15–20 min delayed. Not for live pre-trade decisions.',
    }


# ── Panel 2: Term Structure ──────────────────────────────────────────────────

def _interpolate_iv(ts_signals: dict, target_days: int) -> float:
    """
    Linear interpolation of IV at target_days from available DTE points.
    Uses 30d, 60d, 180d from vol_signals.
    """
    points = {
        30:  ts_signals.get('ts_iv_30d', 0.0),
        60:  ts_signals.get('ts_iv_60d', 0.0),
        180: ts_signals.get('ts_iv_180d', 0.0),
    }
    # Remove zero/None entries
    points = {k: v for k, v in points.items() if v and v > 0}
    if not points:
        return 0.0

    dtes = sorted(points.keys())
    ivs = [points[d] for d in dtes]

    if target_days <= dtes[0]:
        return ivs[0]
    if target_days >= dtes[-1]:
        return ivs[-1]

    # Find bracketing points
    for i in range(len(dtes) - 1):
        if dtes[i] <= target_days <= dtes[i + 1]:
            frac = (target_days - dtes[i]) / (dtes[i + 1] - dtes[i])
            return ivs[i] + frac * (ivs[i + 1] - ivs[i])

    return ivs[-1]


def _select_expiration(catalyst_type: str, thesis_days: int, ts_signals: dict) -> dict:
    """
    Select recommended expiration based on catalyst_type and term structure.
    Returns dict with recommended DTE and reasoning.
    """
    front_slope = ts_signals.get('ts_front_slope', 0.0)
    event_premium = ts_signals.get('ts_iv_30d', 0.0) - ts_signals.get('ts_iv_60d', 0.0)
    event_premium_flag = event_premium > 2.0

    if catalyst_type == 'event_specific':
        # Event-dated: closest available to thesis_days
        rec_dte = thesis_days
        reason = "Event-dated expiration aligned with catalyst timeline"
    elif catalyst_type == 'macro_catalyst':
        # Near-term appropriate if event premium is not excessive
        if event_premium_flag:
            rec_dte = max(thesis_days, 45)
            reason = (f"Front premium of {event_premium:.1f} vpts elevated; "
                      "extending to reduce event premium cost")
        else:
            rec_dte = thesis_days
            reason = "Near-term expiration appropriate for macro catalyst"
    elif catalyst_type == 'macro_slow':
        # Avoid near-term; prefer 60d+ to avoid roll costs
        rec_dte = max(thesis_days, 60)
        reason = "Extended expiration to avoid near-term roll costs for slow thesis"
    else:  # technical
        rec_dte = thesis_days
        reason = "Expiration aligned with technical target timeline"

    rec_iv = _interpolate_iv(ts_signals, rec_dte)

    return {
        'recommended_dte': rec_dte,
        'recommended_iv':  round(rec_iv, 2),
        'reason':          reason,
    }


def term_structure_panel(thesis: TradeThesisInput, signals: dict) -> dict:
    """
    Term structure cost analysis with catalyst alignment.
    Reports carry cost of each expiration — does not recommend direction.

    Args:
        thesis: TradeThesisInput from user
        signals: Latest vol_signals row as dict

    Returns:
        Dict with term structure metrics and expiration recommendation.
    """
    ts_shape = signals.get('ts_shape', 'unknown')
    front_slope = signals.get('ts_front_slope', 0.0)
    back_slope = signals.get('ts_back_slope', 0.0)
    iv_30d = signals.get('ts_iv_30d', 0.0)
    iv_60d = signals.get('ts_iv_60d', 0.0)
    iv_180d = signals.get('ts_iv_180d', 0.0)

    # Front slope percentile from history
    front_slope_history = _get_signal_history(thesis.ticker, 'ts_front_slope', 252)
    front_slope_pctile = None
    if len(front_slope_history) > 20:
        front_slope_pctile = float(
            (front_slope_history < front_slope).sum() / len(front_slope_history) * 100
        )

    # Event premium detection
    front_premium = iv_30d - iv_60d if iv_30d and iv_60d else 0.0
    event_premium_flag = front_premium > 2.0

    # Roll cost estimate for macro_slow thesis
    rolls_needed = max(0, thesis.thesis_days // 30 - 1) if thesis.catalyst_type == 'macro_slow' else 0
    roll_cost_per_cycle = abs(front_slope) if front_slope else 0.0
    total_roll_cost = rolls_needed * roll_cost_per_cycle

    # Thesis expiration IV
    thesis_exp_iv = _interpolate_iv(signals, thesis.thesis_days)

    # Expiration recommendation
    exp_rec = _select_expiration(thesis.catalyst_type, thesis.thesis_days, signals)

    return {
        'ts_shape':            ts_shape,
        'front_slope':         round(front_slope, 2) if front_slope else 0.0,
        'back_slope':          round(back_slope, 2) if back_slope else 0.0,
        'front_slope_pctile':  round(front_slope_pctile, 1) if front_slope_pctile is not None else None,
        'iv_30d':              round(iv_30d, 2) if iv_30d else 0.0,
        'iv_60d':              round(iv_60d, 2) if iv_60d else 0.0,
        'iv_180d':             round(iv_180d, 2) if iv_180d else 0.0,
        'thesis_exp_iv':       round(thesis_exp_iv, 2),
        'event_premium_flag':  event_premium_flag,
        'event_premium_vpts':  round(front_premium, 2) if event_premium_flag else 0.0,
        'roll_cost_total':     round(total_roll_cost, 2),
        'rolls_needed':        rolls_needed,
        'optimal_expiration':  exp_rec,
        'data_warning':        '⚠ Data: yfinance 15–20 min delayed. Not for live pre-trade decisions.',
    }


# ── Panel 3: Skew ────────────────────────────────────────────────────────────

def skew_panel(thesis: TradeThesisInput, signals: dict) -> dict:
    """
    Skew cost analysis — absolute wing costs and relative cost between wings.
    If expected_move_sign provided, reports which wing aligns with the signed move.
    Does NOT tell the user which wing to buy.

    Args:
        thesis: TradeThesisInput from user
        signals: Latest vol_signals row as dict

    Returns:
        Dict with skew metrics, wing costs, and relative cost context.
    """
    skew_rr = signals.get('skew_25d_rr', 0.0)
    skew_put = signals.get('skew_25d_put', 0.0)
    skew_call = signals.get('skew_25d_call', 0.0)
    skew_ratio = signals.get('skew_1025_ratio', 0.0)
    atm_iv = signals.get('atm_iv_30d', 0.0)

    # 52-week skew history
    skew_history = _get_signal_history(thesis.ticker, 'skew_25d_rr', 252)
    skew_pctile = None
    skew_52w_low = None
    skew_52w_high = None
    if len(skew_history) > 20:
        skew_pctile = float((skew_history < skew_rr).sum() / len(skew_history) * 100)
        skew_52w_low = float(skew_history.min())
        skew_52w_high = float(skew_history.max())

    # Tail steepness interpretation
    if skew_ratio and skew_ratio > 0:
        if skew_ratio > 2.5:
            tail_interpretation = "steep"
        elif skew_ratio > 1.5:
            tail_interpretation = "normal"
        else:
            tail_interpretation = "flat"
    else:
        tail_interpretation = "unavailable"

    # Put wing premium vs call wing
    put_wing_premium = abs(skew_put) - abs(skew_call) if skew_put and skew_call else 0.0

    # Wing cost relative to ATM
    put_cost_vs_atm = abs(skew_put) if skew_put else 0.0
    call_cost_vs_atm = abs(skew_call) if skew_call else 0.0

    # Directional alignment (only if expected_move_sign provided)
    directional_context = None
    if thesis.expected_move_sign is not None:
        if thesis.expected_move_sign > 0:
            directional_context = {
                'aligned_wing': 'call',
                'wing_cost_vs_atm': round(call_cost_vs_atm, 2),
                'description': (f"For an up-side expected move, buying the call wing. "
                                f"Cost vs ATM: +{call_cost_vs_atm:.1f} vpts.")
            }
        else:
            directional_context = {
                'aligned_wing': 'put',
                'wing_cost_vs_atm': round(put_cost_vs_atm, 2),
                'description': (f"For a down-side expected move, buying the put wing. "
                                f"Cost vs ATM: +{put_cost_vs_atm:.1f} vpts.")
            }

    return {
        'skew_25d_rr':         round(skew_rr, 2) if skew_rr else 0.0,
        'skew_25d_put':        round(skew_put, 2) if skew_put else 0.0,
        'skew_25d_call':       round(skew_call, 2) if skew_call else 0.0,
        'skew_1025_ratio':     round(skew_ratio, 2) if skew_ratio else 0.0,
        'tail_steepness':      tail_interpretation,
        'skew_rr_pctile':      round(skew_pctile, 1) if skew_pctile is not None else None,
        'skew_52w_low':        round(skew_52w_low, 2) if skew_52w_low is not None else None,
        'skew_52w_high':       round(skew_52w_high, 2) if skew_52w_high is not None else None,
        'put_wing_premium':    round(put_wing_premium, 2),
        'directional_context': directional_context,
        'data_warning':        '⚠ Data: yfinance 15–20 min delayed. Not for live pre-trade decisions.',
    }


# ── Panel 4: Flow Context ────────────────────────────────────────────────────

def flow_panel(flow: FlowObservation, current_surface: dict, thesis: TradeThesisInput) -> dict:
    """
    Characterizes observed flow by its aggregate greek implications.
    Does NOT assign directional significance to the combination.

    Args:
        flow: FlowObservation from user
        current_surface: Latest vol_signals row as dict
        thesis: TradeThesisInput for expiration alignment check

    Returns:
        Dict with flow characterization — no directional opinion.
    """
    # Net delta direction of flow (factual characterization only)
    if flow.flow_type == 'calls':
        net_flow_delta_sign = '+1'
        net_flow_description = 'net long delta'
    elif flow.flow_type == 'puts':
        net_flow_delta_sign = '-1'
        net_flow_description = 'net short delta'
    else:
        net_flow_delta_sign = '0'
        net_flow_description = 'mixed/neutral delta'

    # Expiration alignment with thesis
    exp_gap_days = abs(flow.expiration_dte - thesis.thesis_days)
    if exp_gap_days <= 15:
        exp_alignment = 'aligned'
    elif exp_gap_days <= 30:
        exp_alignment = 'adjacent'
    else:
        exp_alignment = 'misaligned'

    # Size context
    size_context = f"{flow.vs_avg_volume} vs. 30-day average volume"

    # IV context at time of flow
    flow_iv_context = current_surface.get('atm_iv_30d', None)

    # P/C OI ratio if available in surface data
    pc_oi_raw = current_surface.get('pc_oi_ratio_json')
    pc_oi_ratio = None
    if pc_oi_raw:
        try:
            import json
            pc_data = json.loads(pc_oi_raw) if isinstance(pc_oi_raw, str) else pc_oi_raw
            pc_oi_ratio = pc_data.get('aggregate_ratio') if isinstance(pc_data, dict) else None
        except (json.JSONDecodeError, AttributeError):
            pass

    return {
        'net_delta_direction':   net_flow_delta_sign,
        'net_delta_description': net_flow_description,
        'execution_character':   flow.execution_type,
        'size_contracts':        flow.size_contracts,
        'expiration_dte':        flow.expiration_dte,
        'expiration_alignment':  exp_alignment,
        'exp_gap_days':          exp_gap_days,
        'size_context':          size_context,
        'approximate_delta':     flow.strike_delta_approx,
        'flow_iv_context':       flow_iv_context,
        'pc_oi_ratio':           pc_oi_ratio,
        'notes':                 flow.notes,
        'disclaimer':            ('Flow direction and expiration alignment are factual '
                                  'characterizations. Their significance depends on your '
                                  'thesis — this panel does not assign meaning to the '
                                  'combination. The trader interprets alignment with thesis.'),
    }


# ── Panel 5: Implied Distribution (Breeden-Litzenberger) ────────────────────

def breeden_litzenberger_density(
    chain:    pd.DataFrame,
    forward:  float,
    rate:     float,
    dte:      int,
    d_strike: float = 5.0
) -> dict:
    """
    Breeden-Litzenberger (1978) risk-neutral density extraction.
    From Hull (2021) Chapter 20 Appendix, Equation 20A.1:

        g(K) = e^(rT) × ∂²C/∂K²

    Approximated via butterfly spread values:
        g(K) ≈ e^(rT) × (C(K-d) + C(K+d) - 2C(K)) / d²

    Uses call prices throughout (put-call parity ensures equivalence).
    Uses forward-based ATM strike selection.

    Returns dict with discrete probability density, exceedance probabilities,
    distribution moments, and comparison metrics.

    Flags total_mass < 0.85 as unreliable — caller should fall back to
    straddle approximation.
    """
    T = dte / 365.0
    if T <= 0:
        return {'error': 'DTE must be positive', 'methodology': 'breeden_litzenberger_1978'}

    discount = np.exp(rate * T)

    # Filter to calls with valid bid
    calls = chain[chain['option_type'] == 'calls'].copy() if 'option_type' in chain.columns \
        else chain[chain['type'] == 'call'].copy() if 'type' in chain.columns \
        else pd.DataFrame()

    if calls.empty:
        return {'error': 'No call data in chain', 'methodology': 'breeden_litzenberger_1978'}

    if 'bid' in calls.columns:
        calls = calls[calls['bid'] > 0].copy()
    calls = calls.sort_values('strike')

    # Compute mid prices
    if 'mid' not in calls.columns:
        if 'bid' in calls.columns and 'ask' in calls.columns:
            calls['mid'] = (calls['bid'] + calls['ask']) / 2.0
        elif 'lastPrice' in calls.columns:
            calls['mid'] = calls['lastPrice']
        else:
            return {'error': 'Cannot compute mid prices', 'methodology': 'breeden_litzenberger_1978'}

    strikes = sorted(calls['strike'].unique())
    density_points = []

    for K in strikes:
        K_lo = K - d_strike
        K_hi = K + d_strike

        c_lo = calls[calls['strike'] == K_lo]['mid'].values
        c_K  = calls[calls['strike'] == K]['mid'].values
        c_hi = calls[calls['strike'] == K_hi]['mid'].values

        if len(c_lo) == 0 or len(c_K) == 0 or len(c_hi) == 0:
            continue

        butterfly_value = float(c_lo[0] + c_hi[0] - 2 * c_K[0])
        if butterfly_value < 0:
            continue  # arbitrage violation in data — skip

        prob_mass = discount * butterfly_value / (d_strike ** 2) * d_strike

        density_points.append({
            'strike':    K,
            'prob_mass': prob_mass,
        })

    if not density_points:
        return {
            'error': 'Insufficient chain data for density extraction',
            'methodology': 'breeden_litzenberger_1978'
        }

    df = pd.DataFrame(density_points)
    total_mass = df['prob_mass'].sum()

    if total_mass <= 0:
        return {
            'error': 'Zero total probability mass — chain data quality issue',
            'methodology': 'breeden_litzenberger_1978'
        }

    df['prob_normalized'] = df['prob_mass'] / total_mass

    # Exceedance probabilities relative to forward
    spot = forward
    prob_up_5pct   = float(df[df['strike'] > spot * 1.05]['prob_normalized'].sum())
    prob_up_10pct  = float(df[df['strike'] > spot * 1.10]['prob_normalized'].sum())
    prob_up_15pct  = float(df[df['strike'] > spot * 1.15]['prob_normalized'].sum())
    prob_dn_5pct   = float(df[df['strike'] < spot * 0.95]['prob_normalized'].sum())
    prob_dn_10pct  = float(df[df['strike'] < spot * 0.90]['prob_normalized'].sum())
    prob_dn_15pct  = float(df[df['strike'] < spot * 0.85]['prob_normalized'].sum())

    # Distribution moments
    mean_implied = float((df['strike'] * df['prob_normalized']).sum())
    var_implied  = float(((df['strike'] - mean_implied)**2 * df['prob_normalized']).sum())
    std_implied  = np.sqrt(var_implied) if var_implied > 0 else 0.0

    skew_implied = 0.0
    kurt_implied = 0.0
    if var_implied > 0:
        skew_implied = float(
            ((df['strike'] - mean_implied)**3 * df['prob_normalized']).sum() / (var_implied ** 1.5)
        )
        kurt_implied = float(
            ((df['strike'] - mean_implied)**4 * df['prob_normalized']).sum() / (var_implied ** 2) - 3
        )

    # Quality flag
    reliable = total_mass >= 0.85

    return {
        'density_points':   density_points,      # list of {strike, prob_mass}
        'total_mass':       round(total_mass, 4),
        'reliable':         reliable,
        'quality_note':     None if reliable else (
            f'Total mass = {total_mass:.2f} (< 0.85). Chain data quality insufficient '
            'for reliable density extraction. Exceedance probabilities may underestimate '
            'tail risk. Consider straddle approximation as fallback.'
        ),
        'iem_1sd_pct':      round(std_implied / spot * 100, 2) if spot > 0 else 0.0,

        'prob_up_5pct':     round(prob_up_5pct, 4),
        'prob_up_10pct':    round(prob_up_10pct, 4),
        'prob_up_15pct':    round(prob_up_15pct, 4),
        'prob_dn_5pct':     round(prob_dn_5pct, 4),
        'prob_dn_10pct':    round(prob_dn_10pct, 4),
        'prob_dn_15pct':    round(prob_dn_15pct, 4),

        'implied_skewness': round(skew_implied, 4),
        'implied_kurtosis': round(kurt_implied, 4),

        'methodology':      'breeden_litzenberger_1978',
        'note':             'Risk-neutral density. Not a prediction. Reflects market pricing of outcomes.',
    }


# ── Structure Comparison Engine ──────────────────────────────────────────────

def _nearest_listed_strike(chain: pd.DataFrame, target: float) -> float:
    """Find the nearest listed strike to target in the chain."""
    strikes = chain['strike'].unique()
    if len(strikes) == 0:
        return target
    return float(strikes[np.argmin(np.abs(strikes - target))])


def _price_structure(
    legs:             list,      # [(strike, 'c'|'p', +1|-1), ...]
    chain:            pd.DataFrame,
    spot:             float,
    forward:          float,
    T:                float,
    rate:             float,
    expected_move_up: float,
    expected_move_dn: float,
) -> dict:
    """
    Price a multi-leg structure and compute P&L at expected moves.
    Uses bs_price() from pricing.py for all calculations.

    Returns dict with cost, max_loss, break_even, and P&L at expected moves.
    """
    total_cost = 0.0
    pnl_at_up = 0.0
    pnl_at_dn = 0.0

    spot_up = spot * (1 + expected_move_up)
    spot_dn = spot * (1 - expected_move_dn)

    for strike, opt_type, sign in legs:
        # Get market mid for this option
        type_filter = 'calls' if opt_type == 'c' else 'puts'
        if 'option_type' in chain.columns:
            leg_chain = chain[chain['option_type'] == type_filter]
        elif 'type' in chain.columns:
            type_val = 'call' if opt_type == 'c' else 'put'
            leg_chain = chain[chain['type'] == type_val]
        else:
            leg_chain = chain

        matched = leg_chain[leg_chain['strike'] == strike]
        if matched.empty:
            continue

        if 'mid' in matched.columns:
            entry_price = float(matched['mid'].iloc[0])
        elif 'bid' in matched.columns and 'ask' in matched.columns:
            entry_price = float((matched['bid'].iloc[0] + matched['ask'].iloc[0]) / 2)
        elif 'lastPrice' in matched.columns:
            entry_price = float(matched['lastPrice'].iloc[0])
        else:
            continue

        # Get IV for this strike
        if 'iv' in matched.columns:
            sigma = float(matched['iv'].iloc[0])
        elif 'impliedVolatility' in matched.columns:
            sigma = float(matched['impliedVolatility'].iloc[0])
        else:
            sigma = 0.20  # fallback

        # If IV stored as percentage (>1.0), convert to decimal
        if sigma > 1.0:
            sigma = sigma / 100.0

        total_cost += sign * entry_price

        # P&L at expected moves (intrinsic value at expiry approximation)
        if opt_type == 'c':
            pnl_at_up += sign * (max(0, spot_up - strike) - entry_price)
            pnl_at_dn += sign * (max(0, spot_dn - strike) - entry_price)
        else:
            pnl_at_up += sign * (max(0, strike - spot_up) - entry_price)
            pnl_at_dn += sign * (max(0, strike - spot_dn) - entry_price)

    # Max loss for long positions = total cost (premium paid)
    max_loss = abs(total_cost) if total_cost > 0 else abs(total_cost)

    # Break-even approximation: spot + cost for calls, spot - cost for puts
    # For multi-leg this is approximate
    be_pct_up = None
    be_pct_dn = None
    if len(legs) == 1:
        strike, opt_type, sign = legs[0]
        if sign > 0:
            if opt_type == 'c':
                be_pct_up = ((strike + abs(total_cost)) / spot - 1) * 100
            else:
                be_pct_dn = (1 - (strike - abs(total_cost)) / spot) * 100

    return {
        'cost':       round(total_cost * 100, 2),   # per contract (100 shares)
        'max_loss':   round(max_loss * 100, 2),
        'pnl_at_up':  round(pnl_at_up * 100, 2),
        'pnl_at_dn':  round(pnl_at_dn * 100, 2),
        'be_pct_up':  round(be_pct_up, 2) if be_pct_up is not None else None,
        'be_pct_dn':  round(be_pct_dn, 2) if be_pct_dn is not None else None,
        'legs':       [(s, t, sgn) for s, t, sgn in legs],
    }


def generate_structure_comparison(
    thesis:   TradeThesisInput,
    panels:   dict,
    chain:    pd.DataFrame,
    spot:     float,
    forward:  float,
    rate:     float,
) -> dict:
    """
    For user's stated expected move magnitude and max loss budget,
    compute P&L profiles for candidate structures.

    All structures shown side-by-side. User selects structure and direction.
    No directional recommendation.

    Uses bs_price() from pricing.py — no local pricer.
    """
    T = thesis.thesis_days / 365.0

    target_strike_up   = forward * (1 + thesis.expected_move)
    target_strike_down = forward * (1 - thesis.expected_move)
    atm_strike = _nearest_listed_strike(chain, forward)
    otm_call_strike = _nearest_listed_strike(chain, target_strike_up)
    otm_put_strike  = _nearest_listed_strike(chain, target_strike_down)

    structures = {}
    common_args = dict(
        chain=chain, spot=spot, forward=forward, T=T, rate=rate,
        expected_move_up=thesis.expected_move,
        expected_move_dn=thesis.expected_move,
    )

    # Structure 1a: Long ATM Call
    structures['long_atm_call'] = _price_structure(
        legs=[(atm_strike, 'c', +1)], **common_args)

    # Structure 1b: Long ATM Put
    structures['long_atm_put'] = _price_structure(
        legs=[(atm_strike, 'p', +1)], **common_args)

    # Structure 2a: Long OTM Call
    structures['long_otm_call'] = _price_structure(
        legs=[(otm_call_strike, 'c', +1)], **common_args)

    # Structure 2b: Long OTM Put
    structures['long_otm_put'] = _price_structure(
        legs=[(otm_put_strike, 'p', +1)], **common_args)

    # Structure 3a: Call Spread
    structures['call_spread'] = _price_structure(
        legs=[(atm_strike, 'c', +1), (otm_call_strike, 'c', -1)], **common_args)

    # Structure 3b: Put Spread
    structures['put_spread'] = _price_structure(
        legs=[(atm_strike, 'p', +1), (otm_put_strike, 'p', -1)], **common_args)

    # Structure 4: Straddle
    structures['long_straddle'] = _price_structure(
        legs=[(atm_strike, 'c', +1), (atm_strike, 'p', +1)], **common_args)

    # Filter by max_loss_budget
    affordable = {k: v for k, v in structures.items()
                  if v['max_loss'] <= thesis.max_loss_budget}

    return {
        'all_structures': structures,
        'affordable':     affordable,
        'thesis':         {
            'ticker':         thesis.ticker,
            'expected_move':  thesis.expected_move,
            'thesis_days':    thesis.thesis_days,
            'catalyst_type':  thesis.catalyst_type,
            'max_loss_budget': thesis.max_loss_budget,
        },
        'strikes_used': {
            'atm':      atm_strike,
            'otm_call': otm_call_strike,
            'otm_put':  otm_put_strike,
        },
        'note': ('Straddle earns on both ±move scenarios. All other structures are '
                 'directional. Select structure and direction based on your thesis.'),
    }


# ── Pre-Trade Memo Generation ────────────────────────────────────────────────

def generate_memo(
    thesis:       TradeThesisInput,
    signals:      dict,
    panels:       dict,
    structures:   dict,
    distribution: dict,
    flow_result:  Optional[dict] = None,
) -> dict:
    """
    Assemble all panel outputs into a structured pre-trade memo.
    Writes JSON to data/outputs/pretrade_memo.json.

    No directional labels. Cost basis comparison only.
    """
    import json
    from pathlib import Path
    from config import OUTPUTS_DIR

    memo = {
        'ticker':      thesis.ticker,
        'date':        datetime.now().strftime('%Y-%m-%d'),
        'written_at':  datetime.now().isoformat(),

        'thesis_parameters': {
            'expected_move':      thesis.expected_move,
            'thesis_days':        thesis.thesis_days,
            'catalyst_type':      thesis.catalyst_type,
            'max_loss_budget':    thesis.max_loss_budget,
            'expected_move_sign': thesis.expected_move_sign,
        },

        'market_state': {
            'vol_level':      panels.get('vol_level'),
            'term_structure': panels.get('term_structure'),
            'skew':           panels.get('skew'),
            'flow':           flow_result,
            'distribution':   distribution,
        },

        'structure_comparison': structures,

        'data_warning': '⚠ Data: yfinance 15–20 min delayed. Not for live pre-trade decisions.',
        'methodology_notes': [
            "Vol level uses analytic theta approximation (ATM N'(d1) ≈ N'(0)).",
            'Term structure interpolation is linear between 30/60/180d points.',
            'BL density is risk-neutral — not a prediction of outcomes.',
            'Structure P&L uses intrinsic-value-at-expiry approximation.',
            'All mid prices from yfinance — apply 5-10% manual haircut.',
        ],
    }

    # Write to output contract location
    out_path = Path(OUTPUTS_DIR) / 'pretrade_memo.json'
    out_path.write_text(json.dumps(memo, indent=2, default=str))
    logger.info("Pre-trade memo written to {}", out_path)

    return memo
