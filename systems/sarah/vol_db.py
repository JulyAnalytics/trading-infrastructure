# systems/sarah/vol_db.py
"""
Schema and write helpers for trading.db (Sarah's vol surface database).
Uses get_connection(config.VOL_DB_PATH) — never calls duckdb.connect() directly.

Schema note: extends v3.0 spec with spot_price, risk_free_rate, div_yield
for forward price traceability. See architecture deviation note in task spec.
"""
from __future__ import annotations
import json
from loguru import logger
from systems.utils.db import get_connection
from config import VOL_DB_PATH


VOL_SIGNALS_DDL = """
CREATE TABLE IF NOT EXISTS vol_signals (
    ticker              VARCHAR,
    date                DATE,

    -- ATM basis (forward-corrected)
    -- Note: spot_price, risk_free_rate, div_yield extend v3.0 spec for traceability
    spot_price          FLOAT,
    forward_price       FLOAT,         -- F = S × e^((r−q)×t) for 30d
    risk_free_rate      FLOAT,
    div_yield           FLOAT,
    atm_iv_30d          FLOAT,         -- ATM IV using forward-based strike (vol points)

    -- IV context
    iv_rank             FLOAT,
    iv_percentile       FLOAT,
    ivr_ivp_confidence  VARCHAR,       -- 'low' | 'medium' | 'standard' | 'insufficient'
    ivr_regime_bias     VARCHAR,       -- NULL or bias description string

    -- Skew (delta space)
    skew_25d_rr         FLOAT,         -- 25Δ call IV − 25Δ put IV (risk reversal)
    skew_25d_put        FLOAT,
    skew_25d_call       FLOAT,
    skew_1025_ratio     FLOAT,         -- 25/10Δ ratio (tail steepness)

    -- Term structure (two slopes — v3.0 schema)
    ts_iv_30d           FLOAT,
    ts_iv_60d           FLOAT,
    ts_iv_180d          FLOAT,
    ts_front_slope      FLOAT,         -- iv_60d − iv_30d
    ts_back_slope       FLOAT,         -- iv_180d − iv_60d
    ts_shape            VARCHAR,       -- 6-state enum

    -- VRP proxy (relabeled from v2.0)
    rv_21d              FLOAT,
    vrp_proxy_bkwd      FLOAT,         -- atm_iv_30d − rv_21d (vol points)
    vrp_proxy_signal    VARCHAR,       -- 6-state enum

    -- Macro context
    macro_regime        VARCHAR,

    -- Raw storage (JSON strings)
    term_structure_json VARCHAR,
    skew_by_delta_json  VARCHAR,
    pc_oi_ratio_json    VARCHAR,

    PRIMARY KEY (ticker, date)
);
"""

VOL_SURFACE_DDL = """
CREATE TABLE IF NOT EXISTS vol_surface (
    ticker          VARCHAR,
    date            DATE,
    expiration      DATE,
    dte             INTEGER,
    strike          FLOAT,
    log_moneyness   FLOAT,
    delta           FLOAT,
    option_type     VARCHAR,
    iv              FLOAT,
    bid             FLOAT,
    ask             FLOAT,
    volume          INTEGER,
    open_interest   INTEGER,
    PRIMARY KEY (ticker, date, expiration, strike, option_type)
);
"""


def initialize_vol_schema() -> None:
    """Create vol tables in trading.db if they do not exist. Idempotent."""
    conn = get_connection(VOL_DB_PATH)
    conn.execute(VOL_SIGNALS_DDL)
    conn.execute(VOL_SURFACE_DDL)
    conn.close()
    logger.info("vol_db schema initialized in {}", VOL_DB_PATH)


def upsert_vol_signals(signals: dict) -> None:
    """
    Write one ticker's daily signals to vol_signals table.
    Uses explicit column names for schema-change safety (not positional params).
    INSERT OR REPLACE for idempotency.
    """
    conn = get_connection(VOL_DB_PATH)
    conn.execute("""
        INSERT OR REPLACE INTO vol_signals (
            ticker, date,
            spot_price, forward_price, risk_free_rate, div_yield, atm_iv_30d,
            iv_rank, iv_percentile, ivr_ivp_confidence, ivr_regime_bias,
            skew_25d_rr, skew_25d_put, skew_25d_call, skew_1025_ratio,
            ts_iv_30d, ts_iv_60d, ts_iv_180d, ts_front_slope, ts_back_slope, ts_shape,
            rv_21d, vrp_proxy_bkwd, vrp_proxy_signal,
            macro_regime,
            term_structure_json, skew_by_delta_json, pc_oi_ratio_json
        ) VALUES (
            ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?,
            ?, ?, ?
        )
    """, [
        signals['ticker'],
        signals['date'],
        signals.get('spot_price'),
        signals.get('forward_price'),
        signals.get('risk_free_rate'),
        signals.get('div_yield'),
        signals.get('atm_iv_30d'),
        signals.get('iv_rank'),
        signals.get('iv_percentile'),
        signals.get('ivr_ivp_confidence'),
        signals.get('ivr_regime_bias'),
        signals.get('skew_25d_rr'),
        signals.get('skew_25d_put'),
        signals.get('skew_25d_call'),
        signals.get('skew_1025_ratio'),
        signals.get('ts_iv_30d'),
        signals.get('ts_iv_60d'),
        signals.get('ts_iv_180d'),
        signals.get('ts_front_slope'),
        signals.get('ts_back_slope'),
        signals.get('ts_shape'),
        signals.get('rv_21d'),
        signals.get('vrp_proxy_bkwd'),
        signals.get('vrp_proxy_signal'),
        signals.get('macro_regime'),
        json.dumps(signals.get('term_structure_json', {})),
        json.dumps(signals.get('skew_by_delta_json', {})),
        json.dumps(signals.get('pc_oi_ratio_json', {})),
    ])
    conn.close()
