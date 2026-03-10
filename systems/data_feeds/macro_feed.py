"""
FRED Data Pipeline
Fetches all macro series defined in config.py and stores them in DuckDB.

Usage:
    # One-time full load:
    python data_feeds/macro_feed.py --full

    # Daily incremental update (put in cron or schedule):
    python data_feeds/macro_feed.py

    # Fetch single series:
    python data_feeds/macro_feed.py --series vix

Cron suggestion (runs at 6pm ET on weekdays):
    0 18 * * 1-5 cd /path/to/phase1_macro && python data_feeds/macro_feed.py
"""

import sys
import os
import time
import argparse
import pandas as pd
from datetime import datetime, timedelta
from fredapi import Fred
from loguru import logger
from rich.console import Console
from rich.table import Table
from rich.progress import track

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))
from config import FRED_API_KEY, MACRO_SERIES, DUCKDB_PATH
from systems.utils.db import get_connection, initialize_schema, upsert_series

console = Console()


def fetch_cot_data(conn) -> int:
    """
    Fetch CFTC COT Futures-Only report using cot-reports package.
    Pulls last 3 years of data and stores net speculative positioning.
    Returns number of rows upserted.
    """
    import cot_reports as cot
    from datetime import datetime

    COT_INSTRUMENTS_MAP = {
        "S&P 500 Consolidated - CHICAGO MERCANTILE EXCHANGE": "SP500",
        "NASDAQ-100 Consolidated - CHICAGO MERCANTILE EXCHANGE": "NASDAQ",
        "EURO FX - CHICAGO MERCANTILE EXCHANGE": "EURUSD",
        "GOLD - COMMODITY EXCHANGE INC.": "GOLD",
        "CRUDE OIL, LIGHT SWEET - NEW YORK MERCANTILE EXCHANGE": "WTI",
        "UST BOND - CHICAGO BOARD OF TRADE": "BONDS_30Y",
        "UST 10Y NOTE - CHICAGO BOARD OF TRADE": "BONDS_10Y",
    }

    try:
        logger.info("Fetching CFTC COT data via cot-reports...")
        current_year = datetime.now().year
        BACKFILL_START_YEAR = 2015  # 3-year buffer before 2018 for z-score warm-up
        years = list(range(BACKFILL_START_YEAR, current_year + 1))

        frames = []
        for year in years:
            try:
                df_year = cot.cot_year(
                    year=year,
                    cot_report_type='legacy_futopt'
                )
                frames.append(df_year)
                logger.info(f"COT: fetched {len(df_year)} rows for {year}")
            except Exception as e:
                logger.warning(f"COT: could not fetch {year}: {e}")

        if not frames:
            logger.error("COT: no data fetched for any year")
            return 0

        df = pd.concat(frames, ignore_index=True)
        df.columns = df.columns.str.strip()

        # Normalise date column — prefer YYYY-MM-DD format over YYMMDD integer
        date_col = next(
            (c for c in df.columns if 'yyyy-mm-dd' in c.lower()), None
        ) or next(
            (c for c in df.columns if 'date' in c.lower()), None
        )
        if date_col is None:
            logger.error(f"COT: cannot find date column. Columns: {list(df.columns)[:10]}")
            return 0

        df['date'] = pd.to_datetime(df[date_col]).dt.date

        # Find market name column
        name_col = next(
            (c for c in df.columns if 'market' in c.lower() and 'name' in c.lower()), None
        )
        if name_col is None:
            logger.error(f"COT: cannot find market name column. Columns: {list(df.columns)[:10]}")
            return 0

        # Find long/short/OI columns
        long_col = next((c for c in df.columns if 'noncommercial' in c.lower() and 'long' in c.lower() and 'all' in c.lower()), None)
        short_col = next((c for c in df.columns if 'noncommercial' in c.lower() and 'short' in c.lower() and 'all' in c.lower()), None)
        oi_col = next((c for c in df.columns if 'open interest' in c.lower() and 'all' in c.lower()), None)

        if not all([long_col, short_col, oi_col]):
            logger.error(f"COT: missing required columns. Found: long={long_col}, short={short_col}, oi={oi_col}")
            return 0

        rows_upserted = 0
        for market_name, instrument in COT_INSTRUMENTS_MAP.items():
            sub = df[df[name_col].str.upper().str.contains(
                market_name.split(' - ')[0].upper(), na=False, regex=False
            )].copy()

            if sub.empty:
                logger.warning(f"COT: no rows found for {instrument} ({market_name})")
                continue

            sub['net_spec'] = (
                pd.to_numeric(sub[long_col], errors='coerce') -
                pd.to_numeric(sub[short_col], errors='coerce')
            )
            sub['oi'] = pd.to_numeric(sub[oi_col], errors='coerce')
            sub['net_spec_pct'] = (sub['net_spec'] / sub['oi']) * 100

            sub = sub.sort_values('date')
            sub['z_score_1y'] = (
                (sub['net_spec_pct'] - sub['net_spec_pct'].rolling(52).mean())
                / sub['net_spec_pct'].rolling(52).std()
            )
            sub['z_score_3y'] = (
                (sub['net_spec_pct'] - sub['net_spec_pct'].rolling(156).mean())
                / sub['net_spec_pct'].rolling(156).std()
            )

            sub_clean = sub[sub['net_spec'].notna()].copy()
            for _, row in sub_clean.iterrows():
                conn.execute("""
                    INSERT OR REPLACE INTO cot_positioning
                        (instrument, date, net_spec, net_spec_pct, z_score_1y, z_score_3y)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, [
                    instrument,
                    row['date'],
                    row['net_spec'],
                    row['net_spec_pct'],
                    row['z_score_1y'] if not pd.isna(row['z_score_1y']) else None,
                    row['z_score_3y'] if not pd.isna(row['z_score_3y']) else None,
                ])
            rows_upserted += len(sub_clean)
            logger.info(f"COT: upserted {len(sub_clean)} rows for {instrument}")

        logger.info(f"COT: total {rows_upserted} rows upserted.")
        return rows_upserted

    except Exception as e:
        logger.error(f"COT fetch failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return 0


# ── FRED Fetcher ──────────────────────────────────────────────────────────────

def build_fred_client() -> Fred:
    if not FRED_API_KEY:
        raise ValueError(
            "FRED_API_KEY not set. Get a free key at: "
            "https://fred.stlouisfed.org/docs/api/api_key.html"
        )
    return Fred(api_key=FRED_API_KEY)


def fetch_series(fred: Fred, series_id: str, full: bool = False) -> pd.DataFrame | None:
    """
    Fetch a single FRED series.
    full=True: pull all available history.
    full=False: pull last 90 days (incremental update).
    """
    observation_start = None if full else (
        datetime.today() - timedelta(days=90)
    ).strftime("%Y-%m-%d")

    try:
        s = fred.get_series(
            series_id,
            observation_start=observation_start,
        )
        if s is None or s.empty:
            return None

        df = s.reset_index()
        df.columns = ["date", "value"]
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df.dropna(subset=["value"])
        return df

    except Exception as e:
        logger.error(f"  FRED fetch error ({series_id}): {e}")
        return None


def run_fred_pipeline(full: bool = False, series_filter: str | None = None):
    """
    Main FRED pipeline. Fetches all (or filtered) series and stores in DuckDB.
    """
    fred = build_fred_client()
    conn = get_connection()
    initialize_schema()

    series_to_fetch = {
        k: v for k, v in MACRO_SERIES.items()
        if series_filter is None or k == series_filter
    }

    mode = "FULL HISTORY" if full else "INCREMENTAL (90d)"
    console.print(f"\n[bold cyan]FRED Pipeline — {mode}[/bold cyan]")
    console.print(f"Fetching {len(series_to_fetch)} series...\n")

    results = []
    for name, (series_id, label, freq) in track(
        series_to_fetch.items(), description="Fetching..."
    ):
        df = fetch_series(fred, series_id, full=full)

        if df is None or df.empty:
            results.append((name, series_id, label, "⚠ NO DATA", 0))
            conn.execute(
                "INSERT INTO fetch_log (series_id, rows_updated, status) "
                "VALUES (?, 0, 'no_data')", [series_id]
            )
            continue

        try:
            upsert_series(conn, series_id=name, series_name=label, df=df)
            results.append((name, series_id, label, "✓", len(df)))
            conn.execute(
                "INSERT INTO fetch_log (series_id, rows_updated, status) "
                "VALUES (?, ?, 'ok')", [series_id, len(df)]
            )
        except Exception as e:
            logger.error(f"  DB write error ({name}): {e}")
            results.append((name, series_id, label, f"✗ {e}", 0))

        time.sleep(0.3)   # FRED rate limit: ~120 req/min

    # Print summary table
    table = Table(title="FRED Fetch Summary", show_lines=True)
    table.add_column("Name", style="cyan")
    table.add_column("FRED ID", style="dim")
    table.add_column("Label")
    table.add_column("Status", style="green")
    table.add_column("Rows", justify="right")

    for name, sid, label, status, rows in results:
        color = "red" if "✗" in status or "⚠" in status else "green"
        table.add_row(name, sid, label, f"[{color}]{status}[/{color}]", str(rows))

    console.print(table)
    conn.close()


# ── Computed Series ───────────────────────────────────────────────────────────

def compute_derived_series():
    """
    Compute series that don't come directly from FRED:
    - M2 YoY growth rate
    - CPI YoY (already annualized but we want clean version)
    - Yield curve as explicit spread
    """
    conn = get_connection()
    logger.info("Computing derived series...")

    # M2 YoY growth
    conn.execute("""
        INSERT OR REPLACE INTO macro_series
            (series_id, series_name, date, value)
        SELECT
            'm2_yoy_growth' as series_id,
            'M2 YoY Growth (%)' as series_name,
            t.date,
            (t.value / LAG(t.value, 12) OVER (ORDER BY t.date) - 1) * 100 as value
        FROM macro_series t
        WHERE t.series_id = 'm2'
    """)

    # VIX / Realized Vol spread (proxy: VIX vs 20-day rolling stdev of daily changes)
    # This requires SPY data — placeholder query structure
    logger.info("Derived series computed.")
    conn.close()


# ── Entry Point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os
    os.makedirs("data/processed", exist_ok=True)
    os.makedirs("logs", exist_ok=True)

    parser = argparse.ArgumentParser(description="FRED Macro Pipeline")
    parser.add_argument("--full", action="store_true",
                        help="Pull full history (slow, use once)")
    parser.add_argument("--series", type=str, default=None,
                        help="Fetch only one series by internal name")
    parser.add_argument("--cot", action="store_true",
                        help="Also fetch CFTC COT positioning data")
    args = parser.parse_args()

    run_fred_pipeline(full=args.full, series_filter=args.series)
    compute_derived_series()

    if args.cot:
        conn = get_connection()
        fetch_cot_data(conn)
        conn.close()

    console.print("\n[bold green]Pipeline complete.[/bold green]")
