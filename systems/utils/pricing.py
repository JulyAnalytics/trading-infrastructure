# systems/utils/pricing.py
"""
Shared Black-Scholes pricing utilities.
Stage 1: forward_price, strike_to_delta, log_moneyness
Stage 2 extension: bs_greeks_full, bs_mispricing_flag, bs_price (added by Task 002)

All functions use analytic formulas. No finite differences.
Forward price uses continuous dividend yield: F = S × e^((r−q)×t)
"""
import numpy as np
from py_vollib.black_scholes.implied_volatility import implied_volatility as _pv_iv
from py_vollib.black_scholes.greeks.analytical import delta as _pv_delta


def forward_price(spot: float, rate: float, div_yield: float, dte: int) -> float:
    """
    F = S × e^((r - q) × t)

    rate:      annualized risk-free rate (decimal, e.g. 0.053)
    div_yield: annualized continuous dividend yield (decimal, e.g. 0.014)
               yfinance fast_info['dividend_yield'] returns trailing 12m decimal.
               Returns 0.0 for non-dividend payers — formula collapses to F = S × e^(r×t).
    dte:       calendar days to expiration (int)
    """
    t = dte / 365.0
    return spot * np.exp((rate - div_yield) * t)


def strike_to_delta(
    mid: float,
    spot: float,
    strike: float,
    rate: float,
    dte: int,
    flag: str,        # 'c' or 'p'
    bid: float = 0.0,
) -> float:
    """
    Two-pass delta: IV from market mid price → delta from that IV.
    Returns np.nan on any pricing failure or if bid is zero.
    """
    if mid <= 0 or bid <= 0:
        return np.nan
    t = dte / 365.0
    try:
        iv = _pv_iv(mid, spot, strike, t, rate, flag)
        d  = _pv_delta(flag, spot, strike, t, rate, iv)
        return float(d)
    except Exception:
        return np.nan


def log_moneyness(strike: float, forward: float) -> float:
    """ln(K/F) — stored for computation. Never displayed (UI uses delta space)."""
    if forward <= 0:
        return np.nan
    return float(np.log(strike / forward))


# ── Stage 2 additions to systems/utils/pricing.py ─────────────────────────────
# Appended by Task 002. Do not modify forward_price, strike_to_delta, log_moneyness above.

import numpy as _np_s2
from scipy.stats import norm as _norm_s2


def bs_price(
    flag: str,    # 'c' or 'p'
    S: float,     # spot
    K: float,     # strike
    t: float,     # time to expiry in years
    r: float,     # risk-free rate (decimal)
    q: float,     # dividend yield (decimal)
    sigma: float, # implied vol (decimal, e.g. 0.183)
) -> float:
    """
    Analytic Black-Scholes option price (Generalized BS with dividend yield).
    Canonical BS pricer for this codebase — used by scenario_engine.py and greeks_tool.py.
    At t≤0 returns intrinsic value.
    """
    if t <= 0:
        return max(S - K, 0.0) if flag == 'c' else max(K - S, 0.0)
    F   = S * _np_s2.exp((r - q) * t)
    d1  = (_np_s2.log(F / K) + 0.5 * sigma**2 * t) / (sigma * _np_s2.sqrt(t))
    d2  = d1 - sigma * _np_s2.sqrt(t)
    if flag == 'c':
        return float(_np_s2.exp(-r * t) * (F * _norm_s2.cdf(d1) - K * _norm_s2.cdf(d2)))
    else:
        return float(_np_s2.exp(-r * t) * (K * _norm_s2.cdf(-d2) - F * _norm_s2.cdf(-d1)))


def bs_greeks_full(
    flag: str,    S: float, K: float, t: float,
    r: float,     q: float, sigma: float,
) -> dict:
    """
    Full analytic BS greeks including second-order (Generalized BS with dividend yield).

    Sign conventions:
    - All greeks per UNIT (1 contract = 100 shares — apply multiplier outside).
    - For SHORT positions, multiply all greeks by -1 before aggregating.
    - Vanna: long call positive (delta rises as vol rises),
             long put negative (delta falls further as vol rises).
             Formula: -exp(-q*t) * n(d1) * d2 / sigma
    - Vega: per 1 vol point change (i.e. per 0.01 change in sigma decimal).
    """
    if t <= 0:
        raise ValueError(f"t must be positive, got {t}")
    if sigma <= 0:
        raise ValueError(f"sigma must be positive, got {sigma}")

    F   = _np_s2.exp((r - q) * t) * S
    d1  = (_np_s2.log(F / K) + 0.5 * sigma**2 * t) / (sigma * _np_s2.sqrt(t))
    d2  = d1 - sigma * _np_s2.sqrt(t)
    nd1 = _norm_s2.pdf(d1)

    Nd1 = _norm_s2.cdf(d1)  if flag == 'c' else _norm_s2.cdf(d1) - 1
    Nd2 = _norm_s2.cdf(d2)  if flag == 'c' else _norm_s2.cdf(d2) - 1

    delta = _np_s2.exp(-q * t) * Nd1
    gamma = _np_s2.exp(-q * t) * nd1 / (S * sigma * _np_s2.sqrt(t))

    if flag == 'c':
        theta = (
            -(S * _np_s2.exp(-q * t) * nd1 * sigma) / (2 * _np_s2.sqrt(t))
            - r * K * _np_s2.exp(-r * t) * _norm_s2.cdf(d2)
            + q * S * _np_s2.exp(-q * t) * _norm_s2.cdf(d1)
        )
    else:
        theta = (
            -(S * _np_s2.exp(-q * t) * nd1 * sigma) / (2 * _np_s2.sqrt(t))
            + r * K * _np_s2.exp(-r * t) * _norm_s2.cdf(-d2)
            - q * S * _np_s2.exp(-q * t) * _norm_s2.cdf(-d1)
        )

    vega  = S * _np_s2.exp(-q * t) * nd1 * _np_s2.sqrt(t) / 100.0
    # Vanna: sign carried by Nd1 (flag-dependent: +call, −put) so that
    # long call → positive (delta rises as vol rises) and
    # long put → negative (delta falls further as vol rises).
    vanna = Nd1 * nd1 * d2 / sigma
    charm = _np_s2.exp(-q * t) * nd1 * (
        (r - q) / (sigma * _np_s2.sqrt(t)) - d2 / (2 * t)
    )
    vomma = vega * d1 * d2 / sigma

    return {
        'delta':       float(delta),
        'gamma':       float(gamma),
        'theta_daily': float(theta / 365.0),
        'vega':        float(vega),
        'vanna':       float(vanna),
        'charm':       float(charm),
        'vomma':       float(vomma),
    }


def bs_mispricing_flag(
    option_delta: float,
    skew_25d_rr: float,
) -> dict:
    """
    Skew-conditional BS reliability threshold.
    When skew is steep, BS misprices options well inside the fixed 15-delta boundary.
    """
    abs_skew = abs(skew_25d_rr)
    if abs_skew < 2.0:
        threshold = 0.10;  skew_regime = 'flat'
    elif abs_skew < 4.0:
        threshold = 0.15;  skew_regime = 'normal'
    elif abs_skew < 6.0:
        threshold = 0.20;  skew_regime = 'steep'
    else:
        threshold = 0.25;  skew_regime = 'extreme'

    flagged = abs(option_delta) < threshold
    return {
        'bs_mispricing_flagged':  flagged,
        'skew_regime':            skew_regime,
        'reliability_threshold':  threshold,
        'warning': (
            f"BS greeks unreliable at this delta given {skew_regime} skew "
            f"({abs_skew:.1f} vpts 25\u0394 RR). SABR or local vol required for accuracy."
        ) if flagged else None,
    }
