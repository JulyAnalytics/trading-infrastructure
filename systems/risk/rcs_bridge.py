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
  thesis(id, instrument, narrative, worst_case_dollar, …, last_updated)
  review(id, trade_id, closed_at NOT NULL, locked_at, …)
        -- NOTE: review has NO created_at column (verified against the live
        -- DB 2026-07-17); closed_at is stamped when the Phase-1 review is
        -- written at position close.
  entity_events(id, entity_type, entity_id, event_type
        [created|status_changed|updated|filed], old_status, new_status,
        occurred_at)   -- append-only, written by RCS triggers only
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
            _hydrate_trade(conn, t)
        return trades
    finally:
        conn.close()


def _hydrate_trade(conn: sqlite3.Connection, trade: dict) -> dict:
    """Attach legs, options meta and the thesis worst-case budget to one trade
    row. Shared by fetch_active_trades() and fetch_trade()."""
    tid = trade["id"]
    trade["legs"] = [dict(r) for r in conn.execute("""
        SELECT id, direction, type, strike, expiry, contracts,
               entry_premium, exit_premium, date_opened, date_closed
        FROM trade_option_legs WHERE trade_id = ? ORDER BY date_opened
    """, [tid])]
    meta = conn.execute(
        "SELECT * FROM trade_options_meta WHERE trade_id = ?", [tid]
    ).fetchone()
    trade["options_meta"] = dict(meta) if meta else None
    return trade


def fetch_trade(trade_id: str) -> "dict | None":
    """
    One RCS trade by ULID — any status (idea/active/closed/discarded), with
    legs, options meta, and the linked thesis's worst_case_dollar.

    fetch_active_trades() is deliberately active-only (it feeds Jordan's
    book); the Sarah intake seam also needs idea-stage trades, so this is the
    single-trade, status-agnostic read. Still strictly read-only (ADR-003).
    """
    conn = _connect()
    try:
        row = conn.execute("""
            SELECT id, name, instrument, instrument_type, thesis_id,
                   status, created_at, closed_at
            FROM trade WHERE id = ?
        """, [trade_id]).fetchone()
        if row is None:
            return None
        trade = _hydrate_trade(conn, dict(row))
        trade["thesis"] = None
        if trade.get("thesis_id"):
            th = conn.execute(
                "SELECT id, instrument, status, worst_case_dollar "
                "FROM thesis WHERE id = ?", [trade["thesis_id"]]).fetchone()
            trade["thesis"] = dict(th) if th else None
        return trade
    finally:
        conn.close()


def list_trades(query: "str | None" = None,
                statuses: "tuple[str, ...]" = ("idea", "active"),
                limit: int = 50) -> "list[dict]":
    """
    Browse/search RCS trades — the "find it without knowing the ULID" read.

    ULIDs are not memorable, so every path that takes one needs a way to get
    there from a ticker or a trade name. Matches case-insensitively on
    instrument, name, or the ULID itself.

    Returns lightweight rows (no entries/exits) plus a leg count, which is the
    field that tells you whether the position surfaces will have anything to
    price. Read-only (ADR-003).
    """
    where = [f"t.status IN ({', '.join('?' * len(statuses))})"]
    args: list = list(statuses)
    if query:
        where.append("(upper(t.instrument) LIKE ? OR upper(t.name) LIKE ? "
                     "OR upper(t.id) LIKE ?)")
        like = f"%{query.strip().upper()}%"
        args += [like, like, like]
    conn = _connect()
    try:
        rows = [dict(r) for r in conn.execute(f"""
            SELECT t.id, t.name, t.instrument, t.instrument_type, t.status,
                   t.created_at,
                   (SELECT count(*) FROM trade_option_legs l
                     WHERE l.trade_id = t.id) AS leg_count
            FROM trade t
            WHERE {' AND '.join(where)}
            ORDER BY t.created_at DESC
            LIMIT ?
        """, [*args, limit])]
    finally:
        conn.close()
    return rows


def fetch_trade_activations(since: str,
                            include_ideas: bool = False) -> "list[dict]":
    """
    Trade lifecycle events newer than `since`, oldest first — the read side of
    the Sarah intake trigger (trade-intake spec §5).

    since: ISO-8601 string compared against entity_events.occurred_at, which
    RCS stores as text ('YYYY-MM-DDTHH:MM:SSZ'), so a lexicographic '>' is a
    correct chronological comparison. Pass '1970-01-01' to read everything.

    include_ideas: also return `created` events (a trade entered as an idea).
    The memo's structure comparison is a chooser and is most useful before the
    legs are frozen, so firing at idea stage is the recommended default — but
    it is a registry toggle (sarah.intake_fire_on_idea), not a hardcode.

    The watermark lives on the trading side (sarah_intake_watermark): RCS's
    own export_watermarks table does not cover the trade entity, and ADR-003
    forbids writing research.db regardless.
    """
    event_types = ("status_changed", "created") if include_ideas \
        else ("status_changed",)
    placeholders = ", ".join("?" * len(event_types))
    conn = _connect()
    try:
        rows = conn.execute(f"""
            SELECT id, entity_id, event_type, old_status, new_status,
                   occurred_at
            FROM entity_events
            WHERE entity_type = 'trade'
              AND event_type IN ({placeholders})
              AND new_status IN ('active', 'idea')
              AND occurred_at > ?
            ORDER BY occurred_at
        """, [*event_types, since]).fetchall()
    finally:
        conn.close()
    # A 'created' event always carries new_status='idea'; a status_changed we
    # care about carries 'active'. Anything else (discarded, closed) is
    # filtered above — an intake must never fire on a trade being abandoned.
    return [dict(r) for r in rows
            if (r["event_type"] == "created" and r["new_status"] == "idea")
            or (r["event_type"] == "status_changed" and r["new_status"] == "active")]


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
        # review has no created_at; closed_at (NOT NULL) marks when the
        # Phase-1 review was written at position close.
        out["reviews_completed"] = count(
            "SELECT count(*) FROM review WHERE closed_at >= ?")
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
