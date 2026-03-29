#!/usr/bin/env python
"""
Usage: python scripts/check_data.py
Quick diagnostic: shows how fresh each key series is.
Run this any time data looks stale.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from systems.utils.db import get_connection
from datetime import date

conn = get_connection()

print(f"\nData freshness check — today is {date.today()}\n")

df = conn.execute("""
    SELECT series_id,
           MAX(date)                          AS last_date,
           current_date - MAX(date)           AS days_stale
    FROM macro_series
    WHERE series_id IN (
        'vix', 'hy_spread', 'ig_spread',
        'treasury_10y', 'treasury_2y',
        'yield_curve_10_2', 'fed_funds',
        'unemployment', 'spy', 'spy_drawdown'
    )
    GROUP BY series_id
    ORDER BY days_stale DESC
""").df()

for _, row in df.iterrows():
    stale = int(row["days_stale"]) if row["days_stale"] is not None else 999
    flag = "  ✓" if stale <= 1 else f"  ⚠ {stale} days stale"
    print(f"  {row['series_id']:<25} last: {row['last_date']}{flag}")

print()

# Also show last cron run
log_path = "logs/cron.log"
if os.path.exists(log_path):
    with open(log_path) as f:
        lines = f.readlines()
    last_run = next((l.strip() for l in reversed(lines) if "started:" in l), None)
    if last_run:
        print(f"Last cron run: {last_run.replace('Cron pipeline started: ', '')}")
else:
    print("No cron log found — pipeline has not run via cron yet.")

conn.close()
