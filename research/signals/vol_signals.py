# research/signals/vol_signals.py
"""
Vol signal extraction — v3.0 spec.

v3.0 changes from build sequence placeholder:
  - Two term structure slopes (front + back) replacing single ts_slope
  - 6-state ts_shape enum
  - VRP relabeled: vrp_proxy_bkwd, vrp_proxy_signal (6-state)
  - IVR/IVP includes regime bias flag
  - All directional labels removed
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from loguru import logger


def term_structure_slopes(atm_iv_by_dte: dict) -> dict:
    """
    Two-slope term structure characterization.
    front_slope: iv_60 − iv_30 (positive = contango, normal)
    back_slope:  iv_180 − iv_60 (positive = sustained macro premium in back)
    ts_shape:    6-state enum
    """
    sorted_dtes = sorted(atm_iv_by_dte.keys())
    if len(sorted_dtes) < 2:
        return {'error': 'insufficient expirations for term structure'}

    def interpolate_iv(target_dte: int) -> float:
        dtes = sorted_dtes
        if target_dte <= dtes[0]:
            return atm_iv_by_dte[dtes[0]]
        if target_dte >= dtes[-1]:
            return atm_iv_by_dte[dtes[-1]]
        for i in range(len(dtes) - 1):
            if dtes[i] <= target_dte <= dtes[i+1]:
                w = (target_dte - dtes[i]) / (dtes[i+1] - dtes[i])
                return atm_iv_by_dte[dtes[i]] * (1 - w) + atm_iv_by_dte[dtes[i+1]] * w
        return atm_iv_by_dte[dtes[-1]]

    iv_30  = interpolate_iv(30)
    iv_60  = interpolate_iv(60)
    iv_180 = interpolate_iv(180)

    front_slope = iv_60  - iv_30
    back_slope  = iv_180 - iv_60

    return {
        'iv_30':       iv_30,
        'iv_60':       iv_60,
        'iv_180':      iv_180,
        'front_slope': front_slope,
        'back_slope':  back_slope,
        'ts_shape':    _classify_ts_shape(front_slope, back_slope),
    }


def _classify_ts_shape(front: float, back: float) -> str:
    if front >= 1.5 and back >= 1.0:
        return 'steep_contango'
    elif front > 0.5 and back > 0.5:
        return 'mild_contango'
    elif abs(front) <= 0.5 and abs(back) <= 0.5:
        return 'flat'
    elif front < -1.0 and back < -0.5:
        return 'full_backwardation'
    elif front < -1.0 and back >= -0.5:
        return 'humped'
    elif front >= -0.5 and back < -1.0:
        return 'inverted_back'
    else:
        return 'mixed'


def backward_vrp_proxy(
    atm_iv_30d: float,
    hist_prices: pd.Series,
    window: int = 21,
) -> dict:
    """
    Backward-looking VRP proxy: 21-day realized vol vs 30-day ATM IV.
    NOT matched-maturity VRP.
    """
    log_returns = np.log(hist_prices / hist_prices.shift(1)).dropna()
    rv_21d = float(log_returns.tail(window).std() * np.sqrt(252) * 100)
    spread = atm_iv_30d - rv_21d

    if spread > 5.0:
        signal = 'significantly_elevated'
    elif spread > 2.0:
        signal = 'moderately_elevated'
    elif spread > -0.5:
        signal = 'near_parity'
    elif spread > -2.0:
        signal = 'moderately_compressed'
    elif spread > -5.0:
        signal = 'compressed'
    else:
        signal = 'inverted'

    return {
        'rv_21d':           rv_21d,
        'atm_iv_30d':       atm_iv_30d,
        'vrp_proxy_bkwd':   spread,
        'vrp_proxy_signal': signal,
        'vrp_note':         'backward-looking 21d RV vs 30d IV — not matched-maturity VRP',
    }


def iv_context(
    current_iv: float,
    history: pd.Series,
    current_vix: float,
    min_history_days: int = 60,
) -> dict:
    """
    IV Rank and IV Percentile with regime bias documentation.
    Known systematic biases are documented, not suppressed.
    """
    if len(history) == 0 or history.max() == history.min():
        return {
            'iv_rank': None, 'iv_percentile': None,
            'history_days': len(history), 'confidence': 'insufficient',
            'regime_bias': None,
        }

    ivr = float((current_iv - history.min()) / (history.max() - history.min()))
    ivp = float((history < current_iv).mean())

    confidence = 'low'    if len(history) < min_history_days else \
                 'medium' if len(history) < 120 else 'standard'

    recent_avg = history.tail(63).mean()
    bias_flag = None
    if recent_avg < 15 and current_vix < 15:
        bias_flag = 'low_vol_anchor: IVR/IVP may overstate current vol relative to true history'
    elif recent_avg > 25 and current_vix > 25:
        bias_flag = 'stress_anchor: IVR/IVP may understate current vol relative to true history'

    return {
        'iv_rank':       ivr,
        'iv_percentile': ivp,
        'history_days':  len(history),
        'confidence':    confidence,
        'regime_bias':   bias_flag,
    }
