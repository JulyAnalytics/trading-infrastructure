"""
Operational alerting (Phase 6 / Alex).

Two sinks per alert: a persisted feed in trading.db (`alerts` table — the GUI
reads this) and a best-effort macOS notification via osascript. Alerting must
never take down the caller: every path degrades to a log line.

Sources today: job failures after retries are exhausted (JobManager) and
Jordan limit breaches (jordan_daily_check job). Anything can call
raise_alert() — keep `source` stable per producer so the feed is filterable.
"""
from __future__ import annotations

import subprocess
import time
import uuid
from datetime import datetime
from pathlib import Path

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

_ALERTS_DDL = """
CREATE TABLE IF NOT EXISTS alerts (
    id         VARCHAR PRIMARY KEY,
    created_at TIMESTAMP,
    source     VARCHAR,      -- 'jobs' | 'jordan_limits' | ...
    severity   VARCHAR,      -- 'warning' | 'error'
    message    VARCHAR,
    acked      BOOLEAN DEFAULT FALSE
)
"""


def _conn(read_only: bool = False):
    import duckdb
    from config import VOL_DB_PATH
    path = str(REPO_ROOT / VOL_DB_PATH) if not Path(VOL_DB_PATH).is_absolute() \
        else VOL_DB_PATH
    last = None
    for _ in range(6):
        try:
            if read_only:
                return duckdb.connect(path, read_only=True)
            conn = duckdb.connect(path)
            conn.execute(_ALERTS_DDL)
            return conn
        except Exception as e:
            last = e
            time.sleep(0.25)
    raise last


def _notify_macos(title: str, message: str) -> None:
    try:
        subprocess.run(
            ["osascript", "-e",
             f'display notification {message!r} with title {title!r}'],
            capture_output=True, timeout=5,
        )
    except Exception as e:
        logger.debug(f"osascript notification failed (non-fatal): {e}")


def raise_alert(source: str, severity: str, message: str,
                notify: bool = True) -> "str | None":
    """Persist an alert and (optionally) pop a macOS notification.
    Never raises. Returns the alert id, or None if persistence failed."""
    alert_id = uuid.uuid4().hex[:12]
    logger.warning(f"ALERT [{source}/{severity}] {message}")
    try:
        conn = _conn()
        try:
            conn.execute(
                "INSERT INTO alerts (id, created_at, source, severity, message)"
                " VALUES (?, ?, ?, ?, ?)",
                [alert_id, datetime.now(), source, severity, message[:2000]],
            )
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"alert persistence failed: {e}")
        alert_id = None
    if notify:
        _notify_macos(f"Leopold — {source}", message[:180])
    return alert_id


def list_alerts(limit: int = 50, unacked_only: bool = False) -> "list[dict]":
    try:
        conn = _conn(read_only=True)
    except Exception:
        return []
    try:
        where = "WHERE NOT acked" if unacked_only else ""
        rows = conn.execute(f"""
            SELECT id, created_at, source, severity, message, acked
            FROM alerts {where} ORDER BY created_at DESC LIMIT ?
        """, [limit]).fetchall()
    except Exception:
        return []   # table not created yet
    finally:
        conn.close()
    keys = ["id", "created_at", "source", "severity", "message", "acked"]
    return [{**dict(zip(keys, r)), "created_at": str(r[1])} for r in rows]


def ack_alert(alert_id: str) -> None:
    conn = _conn()
    try:
        conn.execute("UPDATE alerts SET acked = TRUE WHERE id = ?", [alert_id])
    finally:
        conn.close()
