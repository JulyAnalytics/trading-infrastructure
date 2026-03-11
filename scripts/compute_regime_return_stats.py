"""
Compute median/percentile asset returns conditioned on regime state.
Run once after backfill_regime_history.py completes.
Re-run monthly or when backfill history extends.

Output: regime_return_stats table in macro.db

LOOKBACK NOTE: History starts 2018-01-01. One full cycle captured
(2018 tightening, 2020 COVID crash, 2021-22 inflation regime, 2022-23 tightening).
Missing: 2015-16 EM scare, pre-2018 tightening cycle.
Statistics on regimes with N<20 observations are unreliable — flagged in UI.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import yfinance as yf
import pandas as pd
import numpy as np
from systems.utils.db import get_connection

ASSETS = {
    "SPY": "Equities",
    "TLT": "Long Duration",
    "GLD": "Gold",
    "HYG": "HY Credit",
    "UUP": "USD",
}
HORIZONS  = {"1M": 21, "3M": 63}   # trading days
START     = "2017-01-01"            # 1yr before regime history to warm up fwd returns

conn = get_connection()
conn.execute("""
    CREATE TABLE IF NOT EXISTS regime_return_stats (
        regime         VARCHAR,
        asset          VARCHAR,
        asset_label    VARCHAR,
        horizon        VARCHAR,
        median_return  DOUBLE,
        pct_25         DOUBLE,
        pct_75         DOUBLE,
        n_observations INTEGER,
        history_start  DATE,
        computed_at    TIMESTAMP DEFAULT current_timestamp,
        PRIMARY KEY (regime, asset, horizon)
    )
""")

regimes_df = conn.execute(
    "SELECT date, regime FROM regime_history WHERE date >= '2018-01-01' ORDER BY date"
).df()
regimes_df["date"] = pd.to_datetime(regimes_df["date"])

if regimes_df.empty:
    print("No regime history found. Run backfill_regime_history.py first.")
    conn.close()
    sys.exit(1)

print(f"Regime history: {len(regimes_df)} rows, "
      f"{regimes_df['date'].min().date()} → {regimes_df['date'].max().date()}")
print(f"Regimes found: {sorted(regimes_df['regime'].unique())}\n")

for ticker, label in ASSETS.items():
    print(f"Fetching {ticker} ({label})...")
    try:
        prices = yf.download(ticker, start=START, progress=False, auto_adjust=True)["Close"]
        prices = prices.squeeze()
    except Exception as e:
        print(f"  ERROR fetching {ticker}: {e}")
        continue

    for horizon_label, days in HORIZONS.items():
        fwd_returns = prices.pct_change(days).shift(-days) * 100
        fwd_returns.index = fwd_returns.index.normalize()

        merged = regimes_df.copy()
        merged = merged.set_index("date").join(
            fwd_returns.rename("fwd_return"), how="left"
        ).reset_index()
        merged = merged.dropna(subset=["fwd_return"])

        for regime, grp in merged.groupby("regime"):
            returns = grp["fwd_return"].values
            n = len(returns)
            conn.execute("""
                INSERT OR REPLACE INTO regime_return_stats
                    (regime, asset, asset_label, horizon,
                     median_return, pct_25, pct_75, n_observations, history_start)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, [
                regime, ticker, label, horizon_label,
                round(float(np.median(returns)), 2),
                round(float(np.percentile(returns, 25)), 2),
                round(float(np.percentile(returns, 75)), 2),
                n,
                "2018-01-01",
            ])
            flag = " *" if n < 20 else ""
            print(f"  {regime:<22} | {ticker} | {horizon_label}: "
                  f"N={n}{flag}, median={np.median(returns):.1f}%")

conn.close()
print("\nDone. Regime return stats written to macro.db.")
print("Dashboard Returns tab will now populate on next refresh.")
