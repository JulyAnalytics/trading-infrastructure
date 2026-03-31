# systems/sarah/daily_vol_run.py
"""
Daily vol surface run — Stage 1 orchestrator.

Execution sequence:
  1. Read regime_state.json (prerequisite — fails loudly if missing or stale)
  2. Fetch risk-free rate from FRED (or fallback to cached)
  3. For each ticker in VOL_TICKERS:
     a. Fetch options chain
     b. Build term structure
     c. Extract skew
     d. Compute signals
     e. Write to trading.db
  4. Write vol_signals.json to data/outputs/

Run directly: python systems/sarah/daily_vol_run.py
Or call run_daily_vol() programmatically (from scheduler).
"""
from __future__ import annotations
import datetime
import json
import os
from pathlib import Path
from loguru import logger

from config import (
    OUTPUTS_DIR, VOL_DB_PATH, VOL_TICKERS,
    FRED_RISK_FREE_SERIES, VOL_IVR_MIN_HISTORY_DAYS,
)
from systems.utils.db import get_connection
from systems.utils.pricing import forward_price
from systems.data_feeds.options_feed import fetch_options_chain
from systems.data_feeds.cboe_feed import fetch_vix_term_structure, fetch_vvix_daily
from research.signals.vol_surface import build_term_structure, extract_skew_slice
from research.signals.vol_signals import (
    term_structure_slopes, backward_vrp_proxy, iv_context
)
from systems.sarah.vol_db import initialize_vol_schema, upsert_vol_signals


# 80h covers overnight weekday cycle (~14h) and full weekend (Friday→Monday ~62h).
# Friday's regime is the correct most-recent signal for Monday; this is not staleness.
# Future: add morning refresh_output_contract() to reduce this threshold.
MAX_REGIME_STATE_AGE_HOURS = 80


def _load_regime_state() -> dict:
    """Load and validate regime_state.json. Fails loudly if missing or too stale."""
    p = Path(OUTPUTS_DIR) / 'regime_state.json'
    assert p.exists(), (
        f"MISSING: {p}\n"
        "Marcus pipeline must run and write regime_state.json first. "
        "See Task 000 for setup."
    )
    data = json.loads(p.read_text())
    written = datetime.datetime.fromisoformat(data['written_at'])
    age_h = (datetime.datetime.now() - written).total_seconds() / 3600
    assert age_h < MAX_REGIME_STATE_AGE_HOURS, (
        f"STALE: regime_state.json is {age_h:.1f}h old "
        f"(limit: {MAX_REGIME_STATE_AGE_HOURS}h). Run Marcus pipeline."
    )
    return data


def _fetch_risk_free_rate() -> float:
    """Fetch DTE-matched risk-free rate from FRED. Falls back to 0.045 if unavailable."""
    try:
        import requests
        fred_key = os.environ.get('FRED_API_KEY')
        if not fred_key:
            raise ValueError("FRED_API_KEY not set")
        url = (
            f"https://api.stlouisfed.org/fred/series/observations"
            f"?series_id={FRED_RISK_FREE_SERIES}&api_key={fred_key}"
            f"&file_type=json&sort_order=desc&limit=1"
        )
        resp = requests.get(url, timeout=10)
        resp.raise_for_status()
        obs = resp.json()['observations']
        rate = float(obs[0]['value']) / 100.0
        logger.info("Risk-free rate from FRED ({}): {:.3f}", FRED_RISK_FREE_SERIES, rate)
        return rate
    except Exception as e:
        fallback = 0.045
        logger.warning("FRED rate fetch failed ({}). Using fallback {:.3f}", e, fallback)
        return fallback


def _get_iv_history(ticker: str, days: int = 252) -> 'pd.Series':
    """Pull ATM IV history from trading.db for IVR/IVP calculation."""
    import pandas as pd
    try:
        conn = get_connection(VOL_DB_PATH)
        df = conn.execute(
            "SELECT date, atm_iv_30d FROM vol_signals "
            "WHERE ticker = ? AND atm_iv_30d IS NOT NULL "
            "ORDER BY date DESC LIMIT ?",
            [ticker, days]
        ).df()
        conn.close()
        return pd.Series(df['atm_iv_30d'].values) if not df.empty else pd.Series([], dtype=float)
    except Exception:
        import pandas as pd
        return pd.Series([], dtype=float)


def _get_price_history(ticker: str, days: int = 30) -> 'pd.Series':
    """Pull spot price history from yfinance for RV calculation."""
    try:
        import yfinance as yf
        hist = yf.Ticker(ticker).history(period=f"{days+5}d")
        return hist['Close'].tail(days + 2)
    except Exception as e:
        import pandas as pd
        logger.warning("{}: price history fetch failed — {}", ticker, e)
        return pd.Series([], dtype=float)


def run_daily_vol() -> dict:
    """
    Run the full daily vol pipeline. Returns summary dict.
    Raises AssertionError if prerequisites are not met.
    """
    logger.info("=== Daily Vol Run starting ===")

    regime_data = _load_regime_state()
    macro_regime = regime_data['regime_state']
    logger.info("Regime: {}", macro_regime)

    initialize_vol_schema()  # idempotent

    rate = _fetch_risk_free_rate()

    vix_ts = fetch_vix_term_structure()
    spot_vix = vix_ts['spot_vix'] if vix_ts else None

    fetch_vvix_daily()  # idempotent — stores in vvix_daily table in trading.db

    today = datetime.date.today().isoformat()
    all_ticker_signals = {}
    failures = []

    for ticker in VOL_TICKERS:
        logger.info("Processing {}", ticker)
        try:
            chain_result = fetch_options_chain(ticker, rate)
            if chain_result is None:
                failures.append(ticker)
                continue

            spot      = chain_result['spot']
            div_yield = chain_result['div_yield']
            chains    = chain_result['chains']

            # Term structure
            ts_dict = build_term_structure(chains, spot, rate)
            ts_signals = term_structure_slopes(ts_dict) if len(ts_dict) >= 2 else {}
            atm_iv_30d = ts_signals.get('iv_30')

            # Forward price — computed from inputs, NOT from ts_dict
            # (ts_dict maps {dte: atm_iv}; ts_dict.get(30) is an IV, not a price)
            fwd_30d = forward_price(spot, rate, div_yield, 30)

            # Skew — nearest expiration with both calls and puts
            skew_signals = {}
            for exp_key_c in sorted(k for k in chains if k.endswith('_c')):
                exp_key_p = exp_key_c.replace('_c', '_p')
                if exp_key_p in chains:
                    skew_signals = extract_skew_slice(chains[exp_key_c], chains[exp_key_p])
                    break

            # IVR/IVP
            iv_hist = _get_iv_history(ticker)
            vix_for_bias = spot_vix or (atm_iv_30d or 18.0)
            ivr_data = iv_context(
                atm_iv_30d or 0.0, iv_hist, vix_for_bias,
                min_history_days=VOL_IVR_MIN_HISTORY_DAYS,
            )

            # VRP proxy
            price_hist = _get_price_history(ticker)
            vrp_data = {}
            if atm_iv_30d and len(price_hist) >= 22:
                vrp_data = backward_vrp_proxy(atm_iv_30d, price_hist)

            signals = {
                'ticker':         ticker,
                'date':           today,
                'spot_price':     spot,
                'forward_price':  fwd_30d,          # ← corrected from v1.0
                'risk_free_rate': rate,
                'div_yield':      div_yield,
                'atm_iv_30d':     atm_iv_30d,
                'iv_rank':        ivr_data.get('iv_rank'),
                'iv_percentile':  ivr_data.get('iv_percentile'),
                'ivr_ivp_confidence': ivr_data.get('confidence'),
                'ivr_regime_bias':    ivr_data.get('regime_bias'),
                'skew_25d_rr':    skew_signals.get('skew_25d_rr'),
                'skew_25d_put':   skew_signals.get('skew_25d_put'),
                'skew_25d_call':  skew_signals.get('skew_25d_call'),
                'skew_1025_ratio': skew_signals.get('skew_1025_ratio'),
                'ts_iv_30d':      ts_signals.get('iv_30'),
                'ts_iv_60d':      ts_signals.get('iv_60'),
                'ts_iv_180d':     ts_signals.get('iv_180'),
                'ts_front_slope': ts_signals.get('front_slope'),
                'ts_back_slope':  ts_signals.get('back_slope'),
                'ts_shape':       ts_signals.get('ts_shape'),
                'rv_21d':         vrp_data.get('rv_21d'),
                'vrp_proxy_bkwd': vrp_data.get('vrp_proxy_bkwd'),
                'vrp_proxy_signal': vrp_data.get('vrp_proxy_signal'),
                'macro_regime':   macro_regime,
                'term_structure_json': ts_dict,
                'skew_by_delta_json':  {},
                'pc_oi_ratio_json':    {},
            }

            upsert_vol_signals(signals)
            all_ticker_signals[ticker] = signals
            logger.info(
                "{}: OK — ATM IV 30d: {}, ts_shape: {}, fwd_30d: {:.2f}",
                ticker, atm_iv_30d, ts_signals.get('ts_shape'), fwd_30d
            )

        except Exception as e:
            logger.error("{}: processing failed — {}", ticker, e)
            failures.append(ticker)

    output = {
        'as_of':        today,
        'written_at':   datetime.datetime.now().isoformat(),
        'macro_regime': macro_regime,
        'data_warning': '⚠ yfinance 15–20 min delayed. Not for live pre-trade decisions.',
        'signals':      {
            t: {
                'atm_iv_30d':       s.get('atm_iv_30d'),
                'rv_21d':           s.get('rv_21d'),
                'vrp_proxy_bkwd':   s.get('vrp_proxy_bkwd'),
                'vrp_proxy_signal': s.get('vrp_proxy_signal'),
                'vrp_note':         'backward-looking 21d RV vs 30d IV — not matched-maturity VRP',
                'skew_25d_rr':      s.get('skew_25d_rr'),
                'iv_rank':          s.get('iv_rank'),
                'iv_percentile':    s.get('iv_percentile'),
                'ivr_confidence':   s.get('ivr_ivp_confidence'),
                'ts_front_slope':   s.get('ts_front_slope'),
                'ts_back_slope':    s.get('ts_back_slope'),
                'ts_shape':         s.get('ts_shape'),
                'vol_regime':       _classify_vol_regime(s.get('atm_iv_30d'), spot_vix),
            }
            for t, s in all_ticker_signals.items()
        },
        'failures': failures,
    }

    out_path = Path(OUTPUTS_DIR) / 'vol_signals.json'
    out_path.write_text(json.dumps(output, indent=2, default=str))
    logger.info("vol_signals.json written to {}", out_path)
    logger.info(
        "=== Daily Vol Run complete — {} tickers, {} failures ===",
        len(all_ticker_signals), len(failures)
    )

    # ── Stage 5: VVIX fetch and pre-transition check ──────────────────────
    try:
        from systems.data_feeds.cboe_feed import fetch_vvix_daily
        vvix_val = fetch_vvix_daily()
        if vvix_val is not None:
            logger.info("VVIX fetched in daily pipeline: {}", vvix_val)
    except Exception as e:
        logger.warning("VVIX fetch failed in daily pipeline: {}", e)

    return output


def _classify_vol_regime(atm_iv: float | None, spot_vix: float | None) -> str:
    ref = spot_vix or atm_iv or 18.0
    if ref < 15:   return 'LOW_VOL'
    elif ref < 20: return 'NORMAL_VOL'
    elif ref < 30: return 'ELEVATED_VOL'
    else:          return 'HIGH_VOL'


if __name__ == '__main__':
    result = run_daily_vol()
    print(json.dumps(
        {k: v for k, v in result.items() if k != 'signals'},
        indent=2, default=str
    ))
