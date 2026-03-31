# systems/data_feeds/options_feed.py
"""
Options chain ingestion from yfinance.
Stage 1 data source. Not suitable for live pre-trade decisions (15–20 min delay).

Enriches raw yfinance chain with:
  - iv:            renamed from yfinance 'impliedVolatility' (critical — do not remove)
  - forward:       F = S × e^((r−q)×t) per expiration
  - log_moneyness: ln(K/F) — stored for computation
  - delta:         two-pass BS delta — displayed in UI
  - mid:           (bid + ask) / 2
  - dte:           calendar days to expiration
"""
from __future__ import annotations
import datetime
import numpy as np
import pandas as pd
import yfinance as yf
from loguru import logger
from systems.utils.pricing import forward_price, strike_to_delta, log_moneyness


DATA_WARNING = "⚠ Data: yfinance 15–20 min delayed. Not for live pre-trade decisions."


def fetch_options_chain(
    ticker: str,
    rate: float,
    max_expirations: int = 6,
) -> dict | None:
    """
    Fetch and enrich options chain for a single ticker.

    Returns: {
        'ticker': str,
        'spot': float,
        'div_yield': float,
        'rate': float,
        'as_of': str,
        'data_warning': str,
        'chains': {'{exp_str}_c': pd.DataFrame, '{exp_str}_p': pd.DataFrame},
    }
    Returns None if fetch fails.
    """
    try:
        tk = yf.Ticker(ticker)
        spot = tk.fast_info.get('lastPrice') or tk.fast_info.get('previousClose')
        div_yield = tk.fast_info.get('dividendYield') or 0.0

        if spot is None or spot <= 0:
            logger.warning("{}: could not determine spot price", ticker)
            return None

        expirations = tk.options[:max_expirations]
        chains = {}

        for exp_str in expirations:
            exp_date = datetime.datetime.strptime(exp_str, '%Y-%m-%d').date()
            dte = (exp_date - datetime.date.today()).days
            if dte <= 0:
                continue

            F = forward_price(spot, rate, div_yield, dte)
            chain_data = tk.option_chain(exp_str)

            for flag, raw_df, key_suffix in [
                ('c', chain_data.calls, '_c'),
                ('p', chain_data.puts,  '_p'),
            ]:
                df = raw_df.copy()

                # CRITICAL: yfinance uses 'impliedVolatility', not 'iv'
                # Rename immediately so all downstream code uses 'iv' consistently.
                if 'impliedVolatility' in df.columns:
                    df = df.rename(columns={'impliedVolatility': 'iv'})

                df['option_type'] = 'calls' if flag == 'c' else 'puts'
                df['dte']         = dte
                df['forward']     = F
                df['spot']        = spot
                df['log_moneyness'] = df['strike'].apply(
                    lambda k: log_moneyness(k, F)
                )
                df['mid'] = (df['bid'] + df['ask']) / 2.0
                df['delta'] = df.apply(
                    lambda row: strike_to_delta(
                        mid=row['mid'], spot=spot, strike=row['strike'],
                        rate=rate, dte=dte, flag=flag, bid=row['bid']
                    ),
                    axis=1
                )
                chains[f"{exp_str}{key_suffix}"] = df

        return {
            'ticker':       ticker,
            'spot':         spot,
            'div_yield':    div_yield,
            'rate':         rate,
            'as_of':        datetime.date.today().isoformat(),
            'data_warning': DATA_WARNING,
            'chains':       chains,
        }

    except Exception as e:
        logger.error("{}: options chain fetch failed — {}", ticker, e)
        return None
