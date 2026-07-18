"""
Parameter store — versioned persistence for the parameter registry.

Storage: `parameter_versions` table in trading.db (VOL_DB_PATH), one row per
saved version per component, exactly one row per component flagged active.

Concurrency notes (DuckDB is single-writer per file):
  - Connections are short-lived: open → query → close.
  - If trading.db is locked by a writer (e.g. the daily vol run), reads retry
    briefly and then FALL BACK TO CODE DEFAULTS with a loud warning — a locked
    registry must never crash a pipeline, but the fallback is logged so a
    silently-ignored edit is discoverable.
  - Writes (set_params / seeding) do not fall back; they raise.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime

from loguru import logger

from .models import MODEL_BY_COMPONENT, ParamsBase

_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS parameter_versions (
    component  VARCHAR NOT NULL,
    version    INTEGER NOT NULL,
    payload    VARCHAR NOT NULL,   -- canonical JSON (sorted keys)
    hash       VARCHAR NOT NULL,   -- 12-hex sha256 of payload
    note       VARCHAR,
    created_at TIMESTAMP DEFAULT current_timestamp,
    active     BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (component, version)
)
"""

_CACHE_TTL_SECONDS = 5.0
_cache: "dict[str, tuple[float, ParamsBase, str, int]]" = {}


def _connect():
    # Imported lazily to keep module import light and avoid any risk of an
    # import cycle through config (db.py imports only literal config names).
    from config import VOL_DB_PATH
    from systems.utils.db import get_connection
    return get_connection(VOL_DB_PATH)


def _canonical_json(payload: dict) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def payload_hash(payload: dict) -> str:
    return hashlib.sha256(_canonical_json(payload).encode()).hexdigest()[:12]


def _ensure_table(conn) -> None:
    conn.execute(_TABLE_DDL)


def _fetch_active(conn, component: str):
    return conn.execute(
        """SELECT version, payload, hash FROM parameter_versions
           WHERE component = ? AND active ORDER BY version DESC LIMIT 1""",
        [component],
    ).fetchone()


def _insert_version(conn, component: str, payload: dict, note: str) -> "tuple[int, str]":
    row = conn.execute(
        "SELECT coalesce(max(version), 0) FROM parameter_versions WHERE component = ?",
        [component],
    ).fetchone()
    version = int(row[0]) + 1
    h = payload_hash(payload)
    conn.execute(
        "UPDATE parameter_versions SET active = FALSE WHERE component = ?", [component]
    )
    conn.execute(
        """INSERT INTO parameter_versions
           (component, version, payload, hash, note, created_at, active)
           VALUES (?, ?, ?, ?, ?, ?, TRUE)""",
        [component, version, _canonical_json(payload), h, note, datetime.now()],
    )
    return version, h


def _model_for(component: str) -> type:
    try:
        return MODEL_BY_COMPONENT[component]
    except KeyError:
        raise KeyError(
            f"Unknown parameter component '{component}'. "
            f"Valid: {sorted(MODEL_BY_COMPONENT)}"
        ) from None


@dataclass
class ActiveParams:
    component: str
    version: int
    hash: str
    model: ParamsBase


def _load_active(component: str) -> ActiveParams:
    """Read the active version, seeding defaults on first use."""
    cls = _model_for(component)
    last_err = None
    for attempt in range(3):
        try:
            conn = _connect()
            try:
                _ensure_table(conn)
                row = _fetch_active(conn, component)
                if row is None:
                    defaults = cls()
                    version, h = _insert_version(
                        conn, component, defaults.to_dict(),
                        note="seed: code defaults (v0.5 config.py values)",
                    )
                    logger.info(f"params[{component}] seeded defaults as v{version} ({h})")
                    return ActiveParams(component, version, h, defaults)
                version, payload, h = int(row[0]), row[1], row[2]
                model = cls.from_dict(json.loads(payload))
                return ActiveParams(component, version, h, model)
            finally:
                conn.close()
        except Exception as e:  # lock contention or transient IO
            last_err = e
            time.sleep(0.1)
    defaults = cls()
    logger.warning(
        f"params[{component}]: registry unavailable ({last_err}); "
        f"FALLING BACK TO CODE DEFAULTS for this call. "
        f"Any GUI edits are NOT applied to this run."
    )
    return ActiveParams(component, 0, payload_hash(defaults.to_dict()), defaults)


def get_active(component: str) -> ActiveParams:
    """Active params + version metadata, with a short in-process cache."""
    now = time.monotonic()
    hit = _cache.get(component)
    if hit and hit[0] > now:
        _, model, h, version = hit
        return ActiveParams(component, version, h, model)
    active = _load_active(component)
    _cache[component] = (now + _CACHE_TTL_SECONDS, active.model, active.hash, active.version)
    return active


def get_params(component: str) -> ParamsBase:
    """The typed active parameter set for a component."""
    return get_active(component).model


def active_hash(component: str) -> str:
    """12-hex hash of the active parameter payload — stamp this on runs."""
    return get_active(component).hash


def all_active_hashes() -> "dict[str, str]":
    """Component → active hash, for stamping a run with its full parameter state."""
    return {c: active_hash(c) for c in MODEL_BY_COMPONENT}


def set_params(component: str, payload: dict, note: str = "") -> ActiveParams:
    """
    Validate and persist a new version, activating it.
    Raises ValueError with all violations if the payload fails validation.
    """
    cls = _model_for(component)
    current = get_params(component).to_dict()
    merged = {**current, **payload}
    model = cls.from_dict(merged)
    problems = model.validate()
    if problems:
        raise ValueError(
            f"params[{component}] rejected: " + "; ".join(problems)
        )
    conn = _connect()
    try:
        _ensure_table(conn)
        version, h = _insert_version(conn, component, model.to_dict(), note)
    finally:
        conn.close()
    invalidate_cache(component)
    guarded = [
        name for name in payload
        if (cls.FIELD_SPECS.get(name) or {}).get("guarded")
    ]
    if guarded:
        logger.warning(
            f"params[{component}] v{version} ({h}) changes GUARDED research-gate "
            f"fields {guarded} — note: {note or '(none)'}. All outputs produced "
            f"under this version carry its hash."
        )
    else:
        logger.info(f"params[{component}] v{version} activated ({h}) — {note or 'no note'}")
    return ActiveParams(component, version, h, model)


def get_history(component: str, limit: int = 50) -> "list[dict]":
    """Most-recent-first version history (payloads included)."""
    _model_for(component)
    conn = _connect()
    try:
        _ensure_table(conn)
        rows = conn.execute(
            """SELECT version, payload, hash, note, created_at, active
               FROM parameter_versions WHERE component = ?
               ORDER BY version DESC LIMIT ?""",
            [component, limit],
        ).fetchall()
    finally:
        conn.close()
    return [
        {
            "version": int(r[0]), "payload": json.loads(r[1]), "hash": r[2],
            "note": r[3], "created_at": str(r[4]), "active": bool(r[5]),
        }
        for r in rows
    ]


def activate_version(component: str, version: int, note: str = "") -> ActiveParams:
    """Roll back/forward by re-activating a stored version (as a new version row)."""
    _model_for(component)
    conn = _connect()
    try:
        _ensure_table(conn)
        row = conn.execute(
            "SELECT payload FROM parameter_versions WHERE component = ? AND version = ?",
            [component, version],
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        raise ValueError(f"params[{component}] has no version {version}")
    payload = json.loads(row[0])
    return set_params(component, payload,
                      note=note or f"re-activate v{version}")


def invalidate_cache(component: "str | None" = None) -> None:
    if component is None:
        _cache.clear()
    else:
        _cache.pop(component, None)
