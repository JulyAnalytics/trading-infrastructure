"""
Initialize the DuckDB database and create all required tables.
Run this once during setup: python systems/db_init.py
"""

import os
import duckdb
from dotenv import load_dotenv

load_dotenv()

DEFAULT_DB_PATH = "data/processed/main.db"
DB_PATH = os.getenv("DB_PATH", DEFAULT_DB_PATH)


def init_db(db_path: str = DB_PATH) -> None:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    con = duckdb.connect(db_path)

    con.execute("""
        CREATE TABLE IF NOT EXISTS macro_series (
            date        DATE NOT NULL,
            series_name VARCHAR NOT NULL,
            value       DOUBLE,
            updated_at  TIMESTAMP DEFAULT current_timestamp
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS options_chains (
            date          DATE NOT NULL,
            ticker        VARCHAR NOT NULL,
            expiration    DATE NOT NULL,
            strike        DOUBLE NOT NULL,
            option_type   VARCHAR NOT NULL,
            bid           DOUBLE,
            ask           DOUBLE,
            iv            DOUBLE,
            volume        INTEGER,
            open_interest INTEGER
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS vol_signals (
            date           DATE NOT NULL,
            ticker         VARCHAR NOT NULL,
            atm_iv         DOUBLE,
            skew_25d       DOUBLE,
            iv_rank        DOUBLE,
            iv_percentile  DOUBLE
        )
    """)

    con.execute("""
        CREATE TABLE IF NOT EXISTS trade_log (
            trade_id        UUID NOT NULL,
            timestamp       TIMESTAMP NOT NULL,
            strategy        VARCHAR,
            contract        VARCHAR,
            action          VARCHAR,
            quantity        INTEGER,
            fill_price      DOUBLE,
            regime_at_entry VARCHAR
        )
    """)

    con.close()
    print(f"Database initialized at: {db_path}")


if __name__ == "__main__":
    init_db()
