# systems/sarah/vol_db.py
"""
Schema and write helpers for trading.db (Sarah's vol surface database).
Uses get_connection(config.VOL_DB_PATH) — never calls duckdb.connect() directly.

Schema note: extends v3.0 spec with spot_price, risk_free_rate, div_yield
for forward price traceability. See architecture deviation note in task spec.
"""
from __future__ import annotations
import json
import time
from loguru import logger
from systems.utils.db import get_connection
from config import VOL_DB_PATH


def _connect_write(retries: int = 4, backoff_s: float = 0.4):
    """
    Writable trading.db connection with a short retry. Transient lock
    collisions (API metadata writes, a jobs-table update) lasting <2s
    should not fail a pipeline ticker; a persistently held lock still
    raises so real contention stays loud.
    """
    last = None
    for attempt in range(retries):
        try:
            return get_connection(VOL_DB_PATH)
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(backoff_s * (attempt + 1))
    raise last


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
    next_earnings_date  DATE,          -- nearest upcoming earnings at run time

    -- Raw storage (JSON strings)
    term_structure_json VARCHAR,
    skew_by_delta_json  VARCHAR,
    pc_oi_ratio_json    VARCHAR,

    -- Provenance ('yfinance' for the daily/batch run, 'unusual_whales' for the
    -- historical backfill). Lets the UW import's overlap-day calibration
    -- separate live yfinance rows from EOD UW rows without guessing, and lets
    -- readers pick the authoritative source when both exist for a date.
    data_source         VARCHAR DEFAULT 'yfinance',

    PRIMARY KEY (ticker, date)
);
"""

# Migrations applied to vol_signals after its original shape. Idempotent —
# every writable connection re-runs them. next_earnings_date is the batch-compare
# earnings flag (avoids a network call in the read path); data_source is the
# provenance tag the UW import needs to honour its "today's yfinance row wins"
# guardrail.
_VOL_SIGNALS_MIGRATIONS = (
    "ALTER TABLE vol_signals ADD COLUMN IF NOT EXISTS next_earnings_date DATE",
    "ALTER TABLE vol_signals ADD COLUMN IF NOT EXISTS "
    "data_source VARCHAR DEFAULT 'yfinance'",
)

# ── UW-import contract (binding constraint for the future UW backfill) ───────
# When systems/data_feeds/uw_feed.py lands, its write path MUST produce rows in
# the SAME shape as upsert_vol_signals() below:
#   • term_structure_json — the {dte: atm_iv} dict from build_term_structure
#     (parsed back at sarah.py /charts/term-structure); never a UW-native array.
#   • ts_shape / ts_front_slope / ts_back_slope — derived via the SAME
#     term_structure_slopes() function, not recomputed from UW fields.
#   • iv_rank / iv_percentile / ivr_ivp_confidence — via iv_context() over the
#     backfilled ATM IV series, NOT UW's own IVR field (different lookback would
#     produce two conflicting IVRs and break the confidence gating).
#   • conflict semantics — ON CONFLICT (ticker,date) DO NOTHING for history
#     writes; only refresh_latest_ivr() updates in place, and never spot/IV.
#     A yfinance-written today-row MUST survive a subsequent UW refresh.
# One shape, one classifier, one parser — every reader (the compare endpoints,
# vol monitor, analog search) then works on UW-backed names for free.

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


PRETRADE_MEMOS_DDL = """
CREATE TABLE IF NOT EXISTS pretrade_memos (
    memo_id            VARCHAR PRIMARY KEY,   -- stable, e.g. PTM-20260717-SPY-001
    ticker             VARCHAR,
    date               DATE,
    created_at         TIMESTAMP,
    catalyst_type      VARCHAR,
    expected_move      FLOAT,
    thesis_days        INTEGER,
    max_loss_budget    FLOAT,
    expected_move_sign INTEGER,
    memo_json          VARCHAR,               -- full memo contract as JSON
    param_hashes       VARCHAR                -- registry hashes at build time
);
"""

# Migrations applied to pretrade_memos after its original v1.0 shape.
# rcs_trade_ulid is the citation key back to the RCS trade the memo prices
# (trade-intake spec §7 item 10). Trading-side only — ADR-003 holds, RCS is
# never written.
_PRETRADE_MEMOS_MIGRATIONS = (
    "ALTER TABLE pretrade_memos ADD COLUMN IF NOT EXISTS rcs_trade_ulid VARCHAR",
)


# ── RCS trade intake (trade-intake spec §4) ──────────────────────────────────
# Class-C (user judgment) inputs plus the A/B pre-fills for one RCS trade.
# Keyed by the RCS trade ULID; FK-by-convention only — the two databases are
# deliberately not coupled (ADR-005), and nothing here is ever written back
# to RCS (ADR-003).
SARAH_TRADE_INPUTS_DDL = """
CREATE TABLE IF NOT EXISTS sarah_trade_inputs (
    rcs_trade_ulid    VARCHAR PRIMARY KEY,   -- FK-by-convention to RCS trade.id
    ticker            VARCHAR NOT NULL,      -- options-liquid underlier analysed
    -- The one genuinely user-only field. UNSIGNED DECIMAL FRACTION, exactly as
    -- TradeThesisInput.expected_move: 0.20 = ±20%, NOT 20. The UI converts
    -- percent→decimal on entry; the memo builder does forward*(1±expected_move),
    -- so a stray "20" would price a 2000% move. NULL until the user supplies it.
    expected_move     DOUBLE CHECK(expected_move IS NULL OR expected_move >= 0),
    -- Pre-filled from Class A/B, user may override; NULL = accept the auto value:
    expected_move_sign INTEGER CHECK(expected_move_sign IN (-1, 1) OR expected_move_sign IS NULL),
    thesis_days        INTEGER,              -- NULL → catalyst resolver / option expiry
    catalyst_type      VARCHAR,              -- NULL → catalyst resolver
    max_loss_budget    DOUBLE,               -- $/contract; NULL → derive from RCS
    flow_json          VARCHAR,              -- optional FlowObservation payload, JSON
    -- provenance
    source             VARCHAR NOT NULL DEFAULT 'user',  -- 'user' | 'rcs_intake' | 'llm'
    created_at         TIMESTAMP NOT NULL DEFAULT now(),
    updated_at         TIMESTAMP NOT NULL DEFAULT now()
);
"""

# Columns added after the table's first shape (kept as migrations so an
# existing trading.db picks them up on the next initialize_vol_schema()).
_SARAH_TRADE_INPUTS_MIGRATIONS = (
    # Set when the vol pull for this ticker fails (delisted, thin, throttled)
    # even after the underlier map — surfaced as a blocking item rather than
    # leaving Sarah silently empty (spec §11, batch failure).
    "ALTER TABLE sarah_trade_inputs ADD COLUMN IF NOT EXISTS last_error VARCHAR",
    # Original RCS instrument, before underlier-map resolution, so the UI can
    # show "AMDL analysed as AMD" rather than losing the position ticker.
    "ALTER TABLE sarah_trade_inputs ADD COLUMN IF NOT EXISTS rcs_instrument VARCHAR",
    # JSON list of field names the user set EXPLICITLY. Without per-field
    # provenance a re-pull cannot tell "the user chose this" from "RCS derived
    # this last time", so it must either clobber judgment or freeze stale
    # Class-B data. This column is what lets a re-pull refresh everything RCS
    # owns while leaving every deliberate override alone.
    "ALTER TABLE sarah_trade_inputs ADD COLUMN IF NOT EXISTS user_overrides VARCHAR",
    # Last time the row was re-derived from RCS (distinct from updated_at,
    # which also moves on user edits).
    "ALTER TABLE sarah_trade_inputs ADD COLUMN IF NOT EXISTS rcs_synced_at TIMESTAMP",
)

# Trading-side watermark over RCS entity_events. It lives here (not in RCS)
# because RCS's own export_watermarks table does not cover the trade entity,
# and because ADR-003 forbids writing research.db at all.
SARAH_INTAKE_WATERMARK_DDL = """
CREATE TABLE IF NOT EXISTS sarah_intake_watermark (
    id               INTEGER PRIMARY KEY CHECK(id = 1),
    last_occurred_at TIMESTAMP
);
"""


def initialize_vol_schema() -> None:
    """Create vol tables in trading.db if they do not exist. Idempotent."""
    conn = _connect_write()
    try:
        conn.execute(VOL_SIGNALS_DDL)
        conn.execute(VOL_SURFACE_DDL)
        conn.execute(PRETRADE_MEMOS_DDL)
        conn.execute(SARAH_TRADE_INPUTS_DDL)
        conn.execute(SARAH_INTAKE_WATERMARK_DDL)
        for stmt in (_PRETRADE_MEMOS_MIGRATIONS + _SARAH_TRADE_INPUTS_MIGRATIONS
                     + _VOL_SIGNALS_MIGRATIONS):
            conn.execute(stmt)
    finally:
        conn.close()
    logger.info("vol_db schema initialized in {}", VOL_DB_PATH)


def upsert_vol_signals(signals: dict) -> None:
    """
    Write one ticker's daily signals to vol_signals table.
    Uses explicit column names for schema-change safety (not positional params).
    INSERT OR REPLACE for idempotency.
    """
    conn = _connect_write()
    conn.execute("""
        INSERT OR REPLACE INTO vol_signals (
            ticker, date,
            spot_price, forward_price, risk_free_rate, div_yield, atm_iv_30d,
            iv_rank, iv_percentile, ivr_ivp_confidence, ivr_regime_bias,
            skew_25d_rr, skew_25d_put, skew_25d_call, skew_1025_ratio,
            ts_iv_30d, ts_iv_60d, ts_iv_180d, ts_front_slope, ts_back_slope, ts_shape,
            rv_21d, vrp_proxy_bkwd, vrp_proxy_signal,
            macro_regime, next_earnings_date,
            term_structure_json, skew_by_delta_json, pc_oi_ratio_json,
            data_source
        ) VALUES (
            ?, ?,
            ?, ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            ?, ?, ?,
            ?, ?,
            ?, ?, ?,
            ?
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
        signals.get('next_earnings_date'),
        json.dumps(signals.get('term_structure_json', {})),
        json.dumps(signals.get('skew_by_delta_json', {})),
        json.dumps(signals.get('pc_oi_ratio_json', {})),
        signals.get('data_source', 'yfinance'),
    ])
    conn.close()


def upsert_vol_surface(ticker: str, date: str, chain_data: dict) -> int:
    """
    Persist the full strike × expiration surface for one (ticker, date) from
    the enriched chain dict ({exp_str}_c / {exp_str}_p DataFrames).

    IV is stored in VOL POINTS (18.3 = 18.3%) to match vol_signals; the raw
    chain 'iv' column is decimal. Rows without a positive IV are skipped.
    Delete-then-insert keeps the write idempotent per (ticker, date).

    Returns number of rows written.
    """
    rows = []
    for key, df in chain_data.items():
        if df.empty:
            continue
        option_type = 'call' if key.endswith('_c') else 'put'
        exp_str = key[:-2]
        for _, r in df.iterrows():
            iv = r.get('iv')
            if iv is None or not (0.005 < float(iv) < 5.0):
                continue
            rows.append([
                ticker, date, exp_str,
                int(r['dte']) if r.get('dte') is not None else None,
                float(r['strike']),
                float(r['log_moneyness']) if r.get('log_moneyness') is not None else None,
                float(r['delta']) if r.get('delta') == r.get('delta') else None,  # NaN guard
                option_type,
                round(float(iv) * 100.0, 4),
                float(r['bid']) if r.get('bid') is not None else None,
                float(r['ask']) if r.get('ask') is not None else None,
                int(r['volume']) if r.get('volume') == r.get('volume') else None,
                int(r['openInterest']) if r.get('openInterest') == r.get('openInterest') else None,
            ])

    conn = _connect_write()
    try:
        conn.execute(
            "DELETE FROM vol_surface WHERE ticker = ? AND date = ?",
            [ticker, date],
        )
        if rows:
            conn.executemany("""
                INSERT OR REPLACE INTO vol_surface (
                    ticker, date, expiration, dte, strike, log_moneyness,
                    delta, option_type, iv, bid, ask, volume, open_interest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, rows)
    finally:
        conn.close()
    logger.info("{}: vol_surface — {} strike/expiry rows written", ticker, len(rows))
    return len(rows)


def save_pretrade_memo(memo: dict, param_hashes: dict | None = None,
                       rcs_trade_ulid: str | None = None) -> str:
    """
    Persist a pre-trade memo with a stable, human-readable ID
    (PTM-YYYYMMDD-TICKER-NNN) for RCS cross-links. Returns the memo_id.

    rcs_trade_ulid, when the memo was built for an RCS trade, is the citation
    key back to that trade. It is stored HERE, not in RCS — the RCS-side
    citation stays the user's own note (ADR-003).
    """
    ticker = memo['ticker']
    date_s = memo['date']
    thesis = memo.get('thesis_parameters', {})

    conn = _connect_write()
    try:
        conn.execute(PRETRADE_MEMOS_DDL)
        for stmt in _PRETRADE_MEMOS_MIGRATIONS:
            conn.execute(stmt)
        n = conn.execute(
            "SELECT COUNT(*) FROM pretrade_memos WHERE ticker = ? AND date = ?",
            [ticker, date_s],
        ).fetchone()[0]
        memo_id = f"PTM-{date_s.replace('-', '')}-{ticker}-{n + 1:03d}"
        memo = {**memo, 'memo_id': memo_id}
        if rcs_trade_ulid:
            memo['rcs_trade_ulid'] = rcs_trade_ulid
        conn.execute("""
            INSERT INTO pretrade_memos (
                memo_id, ticker, date, created_at, catalyst_type,
                expected_move, thesis_days, max_loss_budget,
                expected_move_sign, memo_json, param_hashes, rcs_trade_ulid
            ) VALUES (?, ?, ?, current_timestamp, ?, ?, ?, ?, ?, ?, ?, ?)
        """, [
            memo_id, ticker, date_s,
            thesis.get('catalyst_type'),
            thesis.get('expected_move'),
            thesis.get('thesis_days'),
            thesis.get('max_loss_budget'),
            thesis.get('expected_move_sign'),
            json.dumps(memo, default=str),
            json.dumps(param_hashes or {}),
            rcs_trade_ulid,
        ])
    finally:
        conn.close()
    logger.info("pretrade memo persisted: {}{}", memo_id,
                f" ← rcs trade {rcs_trade_ulid}" if rcs_trade_ulid else "")
    return memo_id
