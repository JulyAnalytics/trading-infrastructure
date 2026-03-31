"""
Database layer — DuckDB for fast analytical queries.
Run this once to create the schema. Safe to re-run (CREATE IF NOT EXISTS).

Usage:
    python utils/db.py
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import duckdb
import pandas as pd
from loguru import logger
from config import DUCKDB_PATH


def get_connection(db_path: str = DUCKDB_PATH) -> duckdb.DuckDBPyConnection:
    """Return a connection to the specified database (defaults to macro.db)."""
    return duckdb.connect(db_path)


def initialize_schema():
    """Create all tables. Safe to call on every startup."""
    conn = get_connection()
    logger.info(f"Initializing schema at {DUCKDB_PATH}")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_series (
            series_id   VARCHAR NOT NULL,
            series_name VARCHAR NOT NULL,
            date        DATE    NOT NULL,
            value       DOUBLE,
            pct_chg_1m  DOUBLE,
            pct_chg_3m  DOUBLE,
            pct_chg_12m DOUBLE,
            z_score_1y  DOUBLE,
            z_score_5y  DOUBLE,
            updated_at  TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (series_id, date)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS regime_history (
            date            DATE PRIMARY KEY,
            regime          VARCHAR NOT NULL,
            regime_score    DOUBLE,
            vix             DOUBLE,
            hy_spread       DOUBLE,
            yield_curve     DOUBLE,
            breakeven_10y   DOUBLE,
            unemp_delta     DOUBLE,
            composite_score DOUBLE,
            notes           VARCHAR,
            updated_at      TIMESTAMP DEFAULT current_timestamp
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS cot_positioning (
            instrument  VARCHAR NOT NULL,
            date        DATE    NOT NULL,
            net_spec    DOUBLE,   -- speculative net long (contracts)
            net_spec_pct DOUBLE,  -- as % of open interest
            z_score_1y  DOUBLE,
            z_score_3y  DOUBLE,
            updated_at  TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (instrument, date)
        )
    """)

    # Phase 2: add component score columns (safe to run on existing databases)
    for col in ["vol_score", "credit_score", "curve_score",
                "inflation_score", "labor_score", "positioning_score"]:
        conn.execute(f"ALTER TABLE regime_history ADD COLUMN IF NOT EXISTS {col} DOUBLE")

    for col in ["vol_as_of", "credit_as_of", "curve_as_of",
                "inflation_as_of", "labor_as_of", "positioning_as_of"]:
        conn.execute(f"ALTER TABLE regime_history ADD COLUMN IF NOT EXISTS {col} DATE")

    conn.execute("ALTER TABLE regime_history ADD COLUMN IF NOT EXISTS confidence VARCHAR")
    conn.execute("ALTER TABLE regime_history ADD COLUMN IF NOT EXISTS divergence_type VARCHAR")
    conn.execute("ALTER TABLE regime_history ADD COLUMN IF NOT EXISTS divergence_severity VARCHAR")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS fetch_log (
            series_id    VARCHAR NOT NULL,
            fetched_at   TIMESTAMP DEFAULT current_timestamp,
            rows_updated INTEGER,
            status       VARCHAR,
            error_msg    VARCHAR
        )
    """)

    # Phase 4: macro calendar
    conn.execute("""
        CREATE TABLE IF NOT EXISTS macro_calendar (
            event_name    VARCHAR NOT NULL,
            event_date    DATE    NOT NULL,
            category      VARCHAR NOT NULL,
            importance    INTEGER NOT NULL,
            component     VARCHAR,
            source        VARCHAR,
            updated_at    TIMESTAMP DEFAULT current_timestamp,
            PRIMARY KEY (event_name, event_date)
        )
    """)

    conn.close()
    logger.info("Schema initialized successfully.")


def upsert_series(conn: duckdb.DuckDBPyConnection, series_id: str,
                  series_name: str, df: pd.DataFrame):
    """
    Insert or replace rows for a given series.
    df must have columns: date, value (at minimum).
    """
    df = df.copy()
    df["series_id"] = series_id
    df["series_name"] = series_name

    # Compute z-scores if enough history (always initialize columns so SQL SELECT works)
    df["z_score_1y"] = None
    df["z_score_5y"] = None
    if len(df) >= 252:
        df["z_score_1y"] = (
            (df["value"] - df["value"].rolling(252).mean())
            / df["value"].rolling(252).std()
        )
    if len(df) >= 252 * 5:
        df["z_score_5y"] = (
            (df["value"] - df["value"].rolling(252 * 5).mean())
            / df["value"].rolling(252 * 5).std()
        )

    # Compute % changes (using approximate trading day counts)
    df["pct_chg_1m"]  = df["value"].pct_change(21)  * 100
    df["pct_chg_3m"]  = df["value"].pct_change(63)  * 100
    df["pct_chg_12m"] = df["value"].pct_change(252) * 100

    conn.execute("""
        INSERT OR REPLACE INTO macro_series
            (series_id, series_name, date, value,
             pct_chg_1m, pct_chg_3m, pct_chg_12m,
             z_score_1y, z_score_5y)
        SELECT
            series_id, series_name, date, value,
            pct_chg_1m, pct_chg_3m, pct_chg_12m,
            z_score_1y, z_score_5y
        FROM df
        WHERE value IS NOT NULL
    """)


def get_latest(conn: duckdb.DuckDBPyConnection, series_id: str) -> dict | None:
    """Return the most recent row for a series as a dict."""
    result = conn.execute("""
        SELECT date, value, z_score_1y, z_score_5y, pct_chg_1m, pct_chg_12m
        FROM macro_series
        WHERE series_id = ?
        ORDER BY date DESC
        LIMIT 1
    """, [series_id]).fetchone()

    if result is None:
        return None
    return dict(zip(
        ["date", "value", "z_1y", "z_5y", "chg_1m", "chg_12m"], result
    ))


def get_series_history(conn: duckdb.DuckDBPyConnection,
                       series_id: str, lookback_days: int = 756) -> pd.DataFrame:
    """Return recent history for a series as a DataFrame."""
    return conn.execute("""
        SELECT date, value, z_score_1y, pct_chg_12m
        FROM macro_series
        WHERE series_id = ?
          AND date >= current_date - INTERVAL (?) DAY
        ORDER BY date ASC
    """, [series_id, lookback_days]).df()


if __name__ == "__main__":
    import os
    os.makedirs("data/processed", exist_ok=True)
    initialize_schema()
    print("Database ready.")
