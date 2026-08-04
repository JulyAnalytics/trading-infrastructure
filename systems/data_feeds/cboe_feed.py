# systems/data_feeds/cboe_feed.py
"""
VIX term structure ingestion from CBOE (via Yahoo Finance).
"""
from __future__ import annotations
import datetime
import yfinance as yf
from loguru import logger


VIX_TICKERS = {
    9:   '^VIX9D',
    30:  '^VIX',
    93:  '^VIX3M',
    182: '^VIX6M',
}


def fetch_vix_term_structure() -> dict | None:
    """
    Fetch current VIX levels for 9D, 30D, 3M, 6M tenors.

    Returns: {
        'as_of': str,
        'levels': {dte_int: vix_float},     # VIX as percentage (e.g. 18.3)
        'levels_decimal': {dte_int: float}, # as decimal (e.g. 0.183)
        'spot_vix': float,                  # 30D VIX — standard reference
    }
    Returns None if fetch fails entirely.
    """
    try:
        levels = {}
        for dte, sym in VIX_TICKERS.items():
            tk = yf.Ticker(sym)
            price = tk.fast_info.get('lastPrice') or tk.fast_info.get('previousClose')
            if price is None:
                logger.warning("Could not fetch {} ({})", sym, dte)
                continue
            levels[dte] = float(price)

        if not levels:
            return None

        return {
            'as_of':          datetime.date.today().isoformat(),
            'levels':         levels,
            'levels_decimal': {k: v / 100.0 for k, v in levels.items()},
            'spot_vix':       levels.get(30),
        }
    except Exception as e:
        logger.error("VIX term structure fetch failed — {}", e)
        return None


def fetch_vvix_daily() -> 'Optional[float]':
    """
    Fetch current VVIX value from CBOE free data.
    Falls back to yfinance ^VVIX.
    Stores in vvix_daily table in trading.db.

    Returns current VVIX value or None on failure.
    """
    from typing import Optional
    import yfinance as yf
    from config import VOL_DB_PATH
    from systems.utils.db import get_connection

    # Ensure table exists
    conn = get_connection(VOL_DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS vvix_daily (
            date DATE PRIMARY KEY,
            vvix FLOAT,
            vix  FLOAT,
            vvix_vix_ratio FLOAT,
            source VARCHAR
        )
    """)

    try:
        # Primary: yfinance ^VVIX
        vvix_data = yf.Ticker('^VVIX')
        hist = vvix_data.history(period='5d')
        if hist.empty:
            logger.warning("VVIX fetch returned empty data")
            conn.close()
            return None

        vvix_val = float(hist['Close'].iloc[-1])
        vvix_date = hist.index[-1].strftime('%Y-%m-%d')

        # Also fetch VIX for ratio
        vix_data = yf.Ticker('^VIX')
        vix_hist = vix_data.history(period='5d')
        vix_val = float(vix_hist['Close'].iloc[-1]) if not vix_hist.empty else None
        ratio = vvix_val / vix_val if vix_val and vix_val > 0 else None

        conn.execute("""
            INSERT OR REPLACE INTO vvix_daily (date, vvix, vix, vvix_vix_ratio, source)
            VALUES (?, ?, ?, ?, 'yfinance')
        """, [vvix_date, vvix_val, vix_val, ratio])
        conn.close()

        logger.info("VVIX fetched: {} (VIX: {}, ratio: {})", vvix_val, vix_val, ratio)
        return vvix_val

    except Exception as e:
        logger.warning("VVIX fetch failed: {}", e)
        conn.close()
        return None


VVIX_HISTORY_URL = (
    "https://cdn.cboe.com/api/global/us_indices/daily_prices/VVIX_History.csv"
)


def fetch_vvix_history() -> 'pd.DataFrame':
    """
    Download CBOE's free daily VVIX history (2007–present).
    Spec: U5.1 (sarah_vol_upgrade_path_stages_4_5_v2.md).

    Returns a DataFrame with columns ['date', 'vvix'] (date as 'YYYY-MM-DD'
    strings, ascending). Raises on download or parse failure — the caller
    (backfill script) should fail loudly, not write a partial backfill.
    """
    import io
    import pandas as pd
    import requests

    resp = requests.get(VVIX_HISTORY_URL, timeout=30)
    resp.raise_for_status()
    df = pd.read_csv(io.StringIO(resp.text))

    df.columns = [c.strip().lower() for c in df.columns]
    date_col = next(c for c in df.columns if 'date' in c)
    vvix_col = next(c for c in df.columns if 'vvix' in c or c in ('close', 'value'))

    out = pd.DataFrame({
        'date': pd.to_datetime(df[date_col]).dt.strftime('%Y-%m-%d'),
        'vvix': pd.to_numeric(df[vvix_col], errors='coerce'),
    }).dropna().sort_values('date').reset_index(drop=True)

    if len(out) < 1000:
        raise ValueError(
            f"VVIX history looks truncated: {len(out)} rows (expected 4000+). "
            "CBOE CSV format may have changed — inspect before loading."
        )
    logger.info("CBOE VVIX history: {} rows, {} → {}",
                len(out), out['date'].iloc[0], out['date'].iloc[-1])
    return out
