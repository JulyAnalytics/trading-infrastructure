"""
Shared API helpers — read-only DB access with graceful lock handling.

DuckDB allows either one writer or many readers per file. Pipeline jobs run
as subprocess writers, so API reads open READ-ONLY, short-lived connections
and translate a lock collision into HTTP 503 rather than a stack trace.
"""
from __future__ import annotations

import time
from pathlib import Path

import duckdb
from fastapi import HTTPException

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _abs(path: str) -> str:
    p = Path(path)
    return str(p if p.is_absolute() else REPO_ROOT / p)


def open_readonly(db_path: str, retries: int = 3) -> duckdb.DuckDBPyConnection:
    last = None
    for _ in range(retries):
        try:
            return duckdb.connect(_abs(db_path), read_only=True)
        except Exception as e:
            last = e
            time.sleep(0.15)
    raise HTTPException(
        status_code=503,
        detail=f"database busy (a pipeline job is writing): {last}",
    )


def macro_conn() -> duckdb.DuckDBPyConnection:
    from config import DUCKDB_PATH
    return open_readonly(DUCKDB_PATH)


def trading_conn() -> duckdb.DuckDBPyConnection:
    from config import VOL_DB_PATH
    return open_readonly(VOL_DB_PATH)


def rows_as_dicts(rel) -> "list[dict]":
    cols = [d[0] for d in rel.description]
    return [dict(zip(cols, (str(v) if hasattr(v, "isoformat") else v for v in row)))
            for row in rel.fetchall()]
