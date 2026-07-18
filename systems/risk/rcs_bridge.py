"""
Read-only bridge to the Research Capture System SQLite database.

HARD RULE (ADR-003): this repo NEVER writes research.db. Connections are
opened with SQLite's `mode=ro` URI flag, so writes are impossible at the
driver level, not just by convention. RCS backups/guards stay authoritative.

Schema referenced (research-capture-system/research/db/schema.sql):
  trade(id, name, instrument, instrument_type, thesis_id, status
        [idea|active|closed|discarded], created_at, closed_at, …)
  trade_entries(trade_id, date, price, size)   -- append-only
  trade_exits(trade_id, date, price, size)     -- append-only
  trade_option_legs(trade_id, direction[long|short], type[call|put],
        strike, expiry, contracts, entry_premium, exit_premium,
        date_opened, date_closed)
  trade_options_meta(trade_id, strategy_type, iv_at_entry, …)
  thesis(id, instrument, narrative, …) · review(id, …, created_at)
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger


def _db_path() -> Path:
    from config import RCS_DB_PATH
    return Path(RCS_DB_PATH)


def available() -> bool:
    return _db_path().exists()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    if not path.exists():
        raise FileNotFoundError(f"RCS database not found at {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=2.0)
    conn.row_factory = sqlite3.Row
    return conn


def fetch_active_trades() -> "list[dict]":
    """
    Active RCS trades with net open size, legs and options meta —
    the raw material for Jordan's positions book.
    """
    conn = _connect()
    try:
        trades = [dict(r) for r in conn.execute("""
            SELECT id, name, instrument, instrument_type, thesis_id,
                   status, created_at
            FROM trade WHERE status = 'active' ORDER BY created_at
        """)]
        for t in trades:
            tid = t["id"]
            entries = [dict(r) for r in conn.execute(
                "SELECT date, price, size FROM trade_entries WHERE trade_id = ? "
                "ORDER BY date", [tid])]
            exits = [dict(r) for r in conn.execute(
                "SELECT date, price, size FROM trade_exits WHERE trade_id = ? "
                "ORDER BY date", [tid])]
            entered = sum(e["size"] for e in entries)
            exited = sum(x["size"] for x in exits)
            t["net_size"] = entered - exited
            t["avg_entry_price"] = (
                sum(e["price"] * e["size"] for e in entries) / entered
                if entered else None
            )
            t["entries"] = entries
            t["exits"] = exits
            t["legs"] = [dict(r) for r in conn.execute("""
                SELECT id, direction, type, strike, expiry, contracts,
                       entry_premium, exit_premium, date_opened, date_closed
                FROM trade_option_legs WHERE trade_id = ? ORDER BY date_opened
            """, [tid])]
            meta = conn.execute(
                "SELECT * FROM trade_options_meta WHERE trade_id = ?", [tid]
            ).fetchone()
            t["options_meta"] = dict(meta) if meta else None
        return trades
    finally:
        conn.close()


def weekly_activity(days: int = 7) -> dict:
    """Journal activity counts for Alex's weekly review."""
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"window_days": days, "available": True}
    try:
        conn = _connect()
    except Exception as e:
        logger.warning(f"RCS bridge unavailable: {e}")
        return {"window_days": days, "available": False, "reason": str(e)}
    try:
        def count(sql: str) -> "int | None":
            try:
                return int(conn.execute(sql, [cutoff]).fetchone()[0])
            except Exception:
                return None

        out["trades_opened"] = count(
            "SELECT count(*) FROM trade WHERE created_at >= ?")
        out["trades_closed"] = count(
            "SELECT count(*) FROM trade WHERE closed_at >= ?")
        out["trades_active_now"] = int(conn.execute(
            "SELECT count(*) FROM trade WHERE status = 'active'").fetchone()[0])
        out["reviews_completed"] = count(
            "SELECT count(*) FROM review WHERE created_at >= ?")
        out["observations_captured"] = count(
            "SELECT count(*) FROM observation WHERE created_at >= ?")
        out["theses_updated"] = count(
            "SELECT count(*) FROM thesis WHERE last_updated >= ?")
        return out
    finally:
        conn.close()


def entity_url(entity: str, entity_id: str) -> str:
    """Deep link into the RCS UI."""
    from config import RCS_BASE_URL
    return f"{RCS_BASE_URL}/{entity}/{entity_id}"
