"""
Job model + single-worker subprocess executor.

Only the PARENT (API) process writes the jobs table, and only while no child
pipeline is running — children write their own pipeline tables (macro.db /
trading.db) and report back via exit code + captured output. This keeps
DuckDB's single-writer rule intact without any locking protocol.
"""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# name -> {label, description, timeout_s, writes}
JOB_SPECS: "dict[str, dict]" = {
    "marcus_classify": {
        "label": "Marcus — classify regime",
        "description": "Run the regime classifier against current macro.db data, "
                       "persist to regime_history, write regime_state.json.",
        "timeout_s": 300,
        "writes": ["macro.db", "data/outputs/regime_state.json"],
    },
    "fred_incremental": {
        "label": "Marcus — FRED incremental fetch",
        "description": "Incremental FRED pull + derived series + COT. Network.",
        "timeout_s": 1800,
        "writes": ["macro.db"],
    },
    "sarah_daily_vol": {
        "label": "Sarah — daily vol run",
        "description": "Full daily vol pipeline for all configured tickers. "
                       "Requires fresh regime_state.json. Network (yfinance).",
        "timeout_s": 1800,
        "writes": ["trading.db", "data/outputs/vol_signals.json"],
    },
    "snapshot_pdf": {
        "label": "Marcus — PDF snapshot",
        "description": "Generate the one-page regime snapshot PDF.",
        "timeout_s": 300,
        "writes": ["data/snapshots/"],
    },
    "backfill_regime_history": {
        "label": "Marcus — backfill regime history",
        "description": "Recompute regime_history from 2018 under the ACTIVE "
                       "parameter set. Run after changing weights/thresholds.",
        "timeout_s": 3600,
        "writes": ["macro.db"],
    },
    "calibrate_divergence": {
        "label": "Marcus — calibrate divergence thresholds",
        "description": "Run scripts/calibrate_divergence_threshold.py against "
                       "the backfill (report only; apply via the params page).",
        "timeout_s": 1800,
        "writes": [],
    },
}

_JOBS_DDL = """
CREATE TABLE IF NOT EXISTS jobs (
    id           VARCHAR PRIMARY KEY,
    name         VARCHAR NOT NULL,
    status       VARCHAR NOT NULL,       -- queued | running | succeeded | failed
    param_hashes VARCHAR,                -- JSON component->hash at launch
    created_at   TIMESTAMP,
    started_at   TIMESTAMP,
    finished_at  TIMESTAMP,
    exit_code    INTEGER,
    log_tail     VARCHAR,
    error        VARCHAR,
    requested_by VARCHAR
)
"""

_LOG_TAIL_CHARS = 4000


def _conn():
    from config import VOL_DB_PATH
    from systems.utils.db import get_connection
    conn = get_connection(str(REPO_ROOT / VOL_DB_PATH)
                          if not Path(VOL_DB_PATH).is_absolute() else VOL_DB_PATH)
    conn.execute(_JOBS_DDL)
    return conn


def _row_to_dict(row) -> dict:
    keys = ["id", "name", "status", "param_hashes", "created_at", "started_at",
            "finished_at", "exit_code", "log_tail", "error", "requested_by"]
    d = dict(zip(keys, row))
    for k in ("created_at", "started_at", "finished_at"):
        d[k] = str(d[k]) if d[k] is not None else None
    d["param_hashes"] = json.loads(d["param_hashes"]) if d["param_hashes"] else None
    return d


def list_jobs(limit: int = 50) -> "list[dict]":
    conn = _conn()
    try:
        rows = conn.execute(
            """SELECT id, name, status, param_hashes, created_at, started_at,
                      finished_at, exit_code, log_tail, error, requested_by
               FROM jobs ORDER BY created_at DESC LIMIT ?""", [limit]
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def get_job(job_id: str) -> "dict | None":
    conn = _conn()
    try:
        row = conn.execute(
            """SELECT id, name, status, param_hashes, created_at, started_at,
                      finished_at, exit_code, log_tail, error, requested_by
               FROM jobs WHERE id = ?""", [job_id]
        ).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row) if row else None


class JobManager:
    """Single background worker; one pipeline subprocess at a time."""

    def __init__(self):
        self._queue: "queue.Queue[str]" = queue.Queue()
        self._thread: "threading.Thread | None" = None
        self._current: "str | None" = None
        self._lock = threading.Lock()

    # ── public ────────────────────────────────────────────────────────────
    def start(self):
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(
                target=self._worker, name="job-worker", daemon=True)
            self._thread.start()

    def submit(self, name: str, requested_by: str = "api") -> dict:
        if name not in JOB_SPECS:
            raise KeyError(f"Unknown job '{name}'. Valid: {sorted(JOB_SPECS)}")
        from systems.params import all_active_hashes
        job_id = uuid.uuid4().hex[:12]
        conn = _conn()
        try:
            conn.execute(
                """INSERT INTO jobs (id, name, status, param_hashes, created_at,
                                     requested_by)
                   VALUES (?, ?, 'queued', ?, ?, ?)""",
                [job_id, name, json.dumps(all_active_hashes()),
                 datetime.now(), requested_by],
            )
        finally:
            conn.close()
        self._queue.put(job_id)
        self.start()
        return {"id": job_id, "name": name, "status": "queued"}

    def current(self) -> "str | None":
        with self._lock:
            return self._current

    # ── worker ────────────────────────────────────────────────────────────
    def _worker(self):
        while True:
            job_id = self._queue.get()
            try:
                self._run_one(job_id)
            except Exception as e:  # never kill the worker
                logger.exception(f"job worker error on {job_id}: {e}")
                self._update(job_id, status="failed", error=str(e),
                             finished_at=datetime.now())
            finally:
                with self._lock:
                    self._current = None
                self._queue.task_done()

    def _run_one(self, job_id: str):
        job = get_job(job_id)
        if job is None or job["status"] != "queued":
            return
        name = job["name"]
        spec = JOB_SPECS[name]
        with self._lock:
            self._current = job_id
        self._update(job_id, status="running", started_at=datetime.now())
        logger.info(f"job {job_id} [{name}] starting")

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "systems.orchestration.run_job", name],
                cwd=str(REPO_ROOT),
                capture_output=True, text=True,
                timeout=spec["timeout_s"],
            )
            tail = ((proc.stdout or "") + "\n" + (proc.stderr or ""))[-_LOG_TAIL_CHARS:]
            if proc.returncode == 0:
                self._update(job_id, status="succeeded", exit_code=0,
                             log_tail=tail, finished_at=datetime.now())
                logger.info(f"job {job_id} [{name}] succeeded")
            else:
                self._update(job_id, status="failed", exit_code=proc.returncode,
                             log_tail=tail, error=f"exit code {proc.returncode}",
                             finished_at=datetime.now())
                logger.error(f"job {job_id} [{name}] failed ({proc.returncode})")
        except subprocess.TimeoutExpired:
            self._update(job_id, status="failed", error="timeout",
                         finished_at=datetime.now())
            logger.error(f"job {job_id} [{name}] timed out")

    def _update(self, job_id: str, **fields):
        cols, vals = [], []
        for k, v in fields.items():
            cols.append(f"{k} = ?")
            vals.append(v)
        vals.append(job_id)
        # The child pipeline may briefly hold the trading.db write lock right
        # at start/end; retry a few times rather than losing the status update.
        import time as _t
        last = None
        for _ in range(20):
            try:
                conn = _conn()
                try:
                    conn.execute(f"UPDATE jobs SET {', '.join(cols)} WHERE id = ?", vals)
                    return
                finally:
                    conn.close()
            except Exception as e:
                last = e
                _t.sleep(0.25)
        logger.error(f"job {job_id}: could not persist status update: {last}")


MANAGER = JobManager()
