"""
One-time backfill: populate regime_history with daily scores
for all dates present in macro_series but missing from regime_history.

Run once: python scripts/backfill_regime_history.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

import pandas as pd
from systems.utils.db import get_connection
from systems.signals.regime_classifier import RegimeClassifier

conn = get_connection()
clf = RegimeClassifier()

# Load full history into memory once — avoids N DB round-trips
full_macro = conn.execute("SELECT * FROM macro_series ORDER BY date").df()
full_cot   = conn.execute("SELECT * FROM cot_positioning ORDER BY date").df()

BACKFILL_FROM = "2018-01-01"

# Include rows already in regime_history but missing component scores (vol_score IS NULL)
missing = conn.execute(f"""
    SELECT DISTINCT ms.date FROM macro_series ms
    WHERE ms.date >= '{BACKFILL_FROM}'
      AND (
          ms.date NOT IN (SELECT date FROM regime_history)
          OR ms.date IN (SELECT date FROM regime_history WHERE vol_score IS NULL)
      )
    ORDER BY ms.date
""").fetchall()

print(f"Backfilling {len(missing)} dates...")

for i, (d,) in enumerate(missing):
    ts = pd.Timestamp(d)
    snap_macro = full_macro[full_macro["date"] <= ts]
    snap_cot   = full_cot[full_cot["date"] <= ts]
    result = clf.classify_from_df(snap_macro, snap_cot)
    snap = result.snapshot
    conn.execute("""
        INSERT OR REPLACE INTO regime_history
            (date, regime, regime_score, composite_score,
             vix, hy_spread, yield_curve, breakeven_10y, unemp_delta,
             vol_score, credit_score, curve_score,
             inflation_score, labor_score, positioning_score,
             confidence)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, [d, result.regime, result.composite_score, result.composite_score,
          snap.vix, snap.hy_spread, snap.yield_curve_10_2,
          snap.breakeven_10y, snap.unemp_delta_3m,
          result.vol_score, result.credit_score, result.curve_score,
          result.inflation_score, result.labor_score, result.positioning_score,
          result.confidence])
    if (i + 1) % 100 == 0:
        print(f"  {i + 1}/{len(missing)} done...")

conn.close()
print("Done.")
