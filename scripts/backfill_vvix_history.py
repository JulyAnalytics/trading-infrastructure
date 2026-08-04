# scripts/backfill_vvix_history.py
"""
U5.1 — VVIX history bootstrap (spec: sarah_vol_upgrade_path_stages_4_5_v2.md).

Downloads CBOE's free VVIX daily history (2007–present) and backfills the
vvix_daily table in trading.db so the pre-transition monitor and VVIX z-score
normalization work from day one instead of after 252 days of organic
accumulation.

Rules:
  - Rows already present (from the live daily fetch) are NOT overwritten —
    the historical load only fills missing dates, with source='cboe_historical'.
  - The `vix` companion column is filled from macro.db's VIX series where a
    matching date exists; NULL otherwise (macro.db VIX starts ~2018).
  - Verification per spec: the 2020 VVIX spike must show z-score > 3.0
    against its preceding year, and total history must reach back to 2007.

Run as a job (single-writer discipline):
    POST /api/jobs {"name": "backfill_vvix_history"}
or directly when no API/job worker holds trading.db:
    venv/bin/python scripts/backfill_vvix_history.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from loguru import logger  # noqa: E402

from config import VOL_DB_PATH, DUCKDB_PATH  # noqa: E402
from systems.utils.db import get_connection  # noqa: E402
from systems.data_feeds.cboe_feed import fetch_vvix_history  # noqa: E402


def backfill_vvix_history() -> dict:
    import pandas as pd

    hist = fetch_vvix_history()

    # VIX companion values from macro.db (read-only usage pattern; short-lived)
    macro = get_connection(DUCKDB_PATH)
    try:
        vix_df = macro.execute(
            "SELECT date, value FROM macro_series WHERE series_id = 'vix'"
        ).fetchdf()
    finally:
        macro.close()
    vix_map = {}
    if not vix_df.empty:
        vix_df['date'] = pd.to_datetime(vix_df['date']).dt.strftime('%Y-%m-%d')
        vix_map = dict(zip(vix_df['date'], vix_df['value']))

    conn = get_connection(VOL_DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS vvix_daily (
                date DATE PRIMARY KEY,
                vvix FLOAT,
                vix  FLOAT,
                vvix_vix_ratio FLOAT,
                source VARCHAR
            )
        """)
        existing = {
            str(r[0]) for r in
            conn.execute("SELECT date FROM vvix_daily").fetchall()
        }

        rows = []
        for _, r in hist.iterrows():
            d = r['date']
            if d in existing:
                continue  # live-fetched rows stay authoritative
            vix = vix_map.get(d)
            ratio = (r['vvix'] / vix) if vix and vix > 0 else None
            rows.append([d, float(r['vvix']), vix, ratio, 'cboe_historical'])

        if rows:
            conn.executemany("""
                INSERT INTO vvix_daily (date, vvix, vix, vvix_vix_ratio, source)
                VALUES (?, ?, ?, ?, ?)
            """, rows)

        n_total, d_min, d_max = conn.execute(
            "SELECT COUNT(*), MIN(date), MAX(date) FROM vvix_daily"
        ).fetchone()
    finally:
        conn.close()

    logger.info("vvix_daily backfilled: +{} rows → {} total ({} … {})",
                len(rows), n_total, d_min, d_max)

    # ── Verification (spec U5.1): 2020 spike z-score > 3.0 vs preceding year ──
    s = hist.set_index('date')['vvix']
    spike_window = s.loc['2020-03-01':'2020-03-31']
    base_window = s.loc['2019-03-01':'2020-02-28']
    z_2020 = None
    if len(spike_window) and len(base_window) > 100:
        z_2020 = (spike_window.max() - base_window.mean()) / base_window.std()
        logger.info("2020 VVIX spike z-score vs preceding year: {:.2f}", z_2020)

    ok_depth = str(d_min) <= '2008-01-01'
    ok_spike = z_2020 is not None and z_2020 > 3.0
    if not ok_depth:
        logger.warning("History does not reach 2007 — earliest row {}", d_min)
    if not ok_spike:
        logger.warning("2020 spike z-score check failed ({}) — inspect data",
                       z_2020)

    return {
        'inserted': len(rows),
        'total_rows': n_total,
        'earliest': str(d_min),
        'latest': str(d_max),
        'z_2020_spike': round(float(z_2020), 2) if z_2020 is not None else None,
        'checks_passed': bool(ok_depth and ok_spike),
    }


if __name__ == '__main__':
    result = backfill_vvix_history()
    print(result)
    sys.exit(0 if result['checks_passed'] else 1)
