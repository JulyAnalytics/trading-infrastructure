# research/signals/vol_surface.py
"""
Vol surface construction from enriched options chain.
All ATM extraction uses forward price (corrected from build sequence v1).
Moneyness stored as log_moneyness; displayed as delta.

Note on chain_data format: keys are '{exp_str}_c' and '{exp_str}_p'.
build_term_structure collects both per DTE and passes them to extract_atm_iv
for call/put averaging — do not revert to single-chain iteration.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from loguru import logger
from py_vollib.black_scholes.implied_volatility import implied_volatility as _pv_iv


def extract_atm_iv(
    calls_df: pd.DataFrame,
    puts_df: pd.DataFrame,
    forward: float,
    dte: int,
    rate: float,
) -> float | None:
    """
    Extract ATM implied vol for a single expiration.
    Accepts both calls and puts DataFrames for averaging.
    Uses the listed strike closest to the forward price (not spot).
    Averages call and put IV at that ATM strike for robustness.

    Both DataFrames must have an 'iv' column (renamed from impliedVolatility
    by options_feed.py). Requires non-empty DataFrames with 'strike' and 'iv'.
    """
    all_strikes = pd.concat([
        calls_df[['strike']] if not calls_df.empty else pd.DataFrame(),
        puts_df[['strike']]  if not puts_df.empty  else pd.DataFrame(),
    ]).drop_duplicates()

    if all_strikes.empty:
        return None

    strikes = all_strikes['strike'].values
    atm_strike = float(strikes[np.argmin(np.abs(strikes - forward))])
    t = dte / 365.0
    spot = forward   # acceptable approximation for ATM IV extraction (F ≈ S near ATM)

    ivs = []
    for flag, df in [('c', calls_df), ('p', puts_df)]:
        if df.empty or 'iv' not in df.columns:
            continue
        rows = df[df['strike'] == atm_strike]
        if rows.empty:
            continue
        row = rows.iloc[0]
        # Use stored iv column first; fall back to BS implied from mid price
        if pd.notna(row.get('iv')) and row['iv'] > 0.001:
            # yfinance iv is already in decimal (e.g. 0.183 = 18.3%)
            iv_vpts = float(row['iv']) * 100.0
            if 0.5 < iv_vpts < 500:
                ivs.append(iv_vpts)
        elif row.get('bid', 0) > 0:
            try:
                mid = (row['bid'] + row['ask']) / 2.0
                iv_decimal = _pv_iv(mid, spot, atm_strike, t, rate, flag)
                iv_vpts = iv_decimal * 100.0
                if 0.5 < iv_vpts < 500:
                    ivs.append(iv_vpts)
            except Exception:
                pass

    return float(np.mean(ivs)) if ivs else None


def build_term_structure(chain_data: dict, spot: float, rate: float) -> dict:
    """
    Build ATM IV term structure from enriched chain data.

    chain_data: output of options_feed.fetch_options_chain()['chains']
    Keys are '{exp_str}_c' and '{exp_str}_p'. Both are collected per DTE
    and passed together to extract_atm_iv for call/put averaging.

    Returns: {dte_int: atm_iv_float} — vol points (e.g. {30: 18.3, 60: 19.1})
    """
    # Collect calls and puts DataFrames per DTE
    dte_calls: dict[int, pd.DataFrame] = {}
    dte_puts:  dict[int, pd.DataFrame] = {}

    for key, df in chain_data.items():
        if df.empty or 'dte' not in df.columns:
            continue
        dte = int(df['dte'].iloc[0])
        if dte <= 0:
            continue
        if key.endswith('_c'):
            dte_calls[dte] = df
        elif key.endswith('_p'):
            dte_puts[dte] = df

    # Build term structure using both legs per DTE
    ts = {}
    all_dtes = set(dte_calls.keys()) | set(dte_puts.keys())

    for dte in sorted(all_dtes):
        calls = dte_calls.get(dte, pd.DataFrame())
        puts  = dte_puts.get(dte,  pd.DataFrame())

        if calls.empty and puts.empty:
            continue

        # Use forward from whichever leg is available
        forward_ref = None
        for df in [calls, puts]:
            if not df.empty and 'forward' in df.columns:
                forward_ref = float(df['forward'].iloc[0])
                break
        if forward_ref is None:
            from systems.utils.pricing import forward_price as _fp
            forward_ref = _fp(spot, rate, 0.0, dte)

        iv = extract_atm_iv(calls, puts, forward_ref, dte, rate)
        if iv is not None:
            ts[dte] = iv

    return ts


def extract_skew_slice(
    calls_df: pd.DataFrame,
    puts_df: pd.DataFrame,
) -> dict:
    """
    Extract 25Δ and 10Δ skew from a single expiration.
    Requires delta column (populated by options_feed).
    Requires iv column (renamed from impliedVolatility by options_feed).
    """
    def find_near_delta(df: pd.DataFrame, target_abs_delta: float) -> float | None:
        df = df.dropna(subset=['delta', 'iv'])
        if df.empty:
            return None
        df = df.copy()
        df['delta_dist'] = (df['delta'].abs() - target_abs_delta).abs()
        row = df.loc[df['delta_dist'].idxmin()]
        iv_raw = row.get('iv', 0)
        if iv_raw > 0:
            # yfinance iv is decimal; convert to vol points
            return float(iv_raw) * 100.0
        return None

    put_25d  = find_near_delta(puts_df,  0.25)
    call_25d = find_near_delta(calls_df, 0.25)
    put_10d  = find_near_delta(puts_df,  0.10)

    rr_25d = (call_25d - put_25d) if (call_25d and put_25d) else None

    ratio_1025 = None
    if put_25d and put_10d and put_10d > 0:
        ratio_1025 = put_25d / put_10d

    return {
        'skew_25d_put':    put_25d,
        'skew_25d_call':   call_25d,
        'skew_25d_rr':     rr_25d,
        'skew_1025_ratio': ratio_1025,
    }
