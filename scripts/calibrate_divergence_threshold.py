"""
Calibrate divergence detection thresholds against backfilled regime history.
Run once after backfill_regime_history.py completes.

Prints: firing rate per threshold value, so you can choose a value that
fires ~5-15% of trading days for VC and ~3-8% for VL.

After reviewing the output, update DIVERGENCE_THRESHOLD_VC and
DIVERGENCE_THRESHOLD_VL in config.py.

Target firing rates:
  Config A (Vol calm, Credit stressed): ~5-10% of days
  Config B (Vol stressed, Credit calm): ~8-15% of days (higher FP tolerance)
  Vol/Labor (LABOR_LAG_WARNING):        ~3-8% of days
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from systems.utils.db import get_connection
import pandas as pd

conn = get_connection()
df = conn.execute("""
    SELECT date, vol_score, credit_score, labor_score, curve_score
    FROM regime_history
    WHERE date >= '2018-01-01'
      AND vol_score IS NOT NULL
    ORDER BY date
""").df()
conn.close()

if df.empty:
    print("No data in regime_history with component scores.")
    print("Run backfill_regime_history.py first, then re-run this script.")
    sys.exit(1)

df["spread_vc"] = abs(df["vol_score"] - df["credit_score"])
df["spread_vl"] = abs(df["vol_score"] - df["labor_score"])
df["config_a"]  = (df["vol_score"] > 0) & (df["credit_score"] < 0)
df["config_b"]  = (df["vol_score"] < 0) & (df["credit_score"] > 0)

total = len(df)
print(f"\nTotal trading days: {total}")
print(f"Date range: {df['date'].min()} → {df['date'].max()}")

print(f"\n── Vol/Credit Spread Distribution ──")
print(f"  {'Threshold':>10}  {'Config A (High)':>20}  {'Config B (Medium)':>20}")
for t in [0.4, 0.5, 0.6, 0.7, 0.8, 0.9]:
    fires_a = ((df["spread_vc"] >= t) & df["config_a"]).sum()
    fires_b = ((df["spread_vc"] >= t) & df["config_b"]).sum()
    print(f"  {t:.1f}            "
          f"{fires_a:>4}d ({fires_a/total*100:5.1f}%)         "
          f"{fires_b:>4}d ({fires_b/total*100:5.1f}%)")

print(f"\n── Vol/Labor Spread Distribution ──")
print(f"  (Only counts when vol < 0, labor > 0)")
print(f"  {'Threshold':>10}  {'Fires':>10}")
for t in [0.5, 0.6, 0.7, 0.8, 0.9, 1.0]:
    fires = ((df["spread_vl"] >= t) & (df["vol_score"] < 0) & (df["labor_score"] > 0)).sum()
    print(f"  {t:.1f}            {fires:>4}d ({fires/total*100:5.1f}%)")

print("\n── Current config.py thresholds ──")
from config import DIVERGENCE_THRESHOLD_VC, DIVERGENCE_THRESHOLD_VL
print(f"  DIVERGENCE_THRESHOLD_VC = {DIVERGENCE_THRESHOLD_VC}")
print(f"  DIVERGENCE_THRESHOLD_VL = {DIVERGENCE_THRESHOLD_VL}")
print("\nUpdate DIVERGENCE_THRESHOLD_VC and DIVERGENCE_THRESHOLD_VL in config.py.")
