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
import time
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
        "description": "Full daily vol pipeline for all configured tickers, or "
                       "an ad-hoc batch via args.tickers (RCS trade intake / "
                       "earnings-week screening). Requires fresh "
                       "regime_state.json. Network (yfinance).",
        # Each batch ticker is an options-chain fetch (up to chain_max_expirations
        # requests) plus a price-history fetch, so an intake batch can be much
        # longer than the 5-ticker daily universe.
        "timeout_s": 3600,
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
    "backfill_vvix_history": {
        "label": "Sarah — backfill VVIX history (U5.1)",
        "description": "One-time bootstrap: download CBOE's free VVIX daily "
                       "history (2007+) and fill vvix_daily so z-scores and the "
                       "pre-transition monitor work day one. Idempotent — "
                       "existing rows are never overwritten. Network (CBOE CDN).",
        "timeout_s": 600,
        "writes": ["trading.db"],
    },
    "fred_full": {
        "label": "Marcus — FRED full refresh (weekly)",
        "description": "Full-history FRED pull + derived series + COT + "
                       "calendar. Scheduled Sundays. Network.",
        "timeout_s": 3600,
        "writes": ["macro.db"],
    },
    "jordan_daily_check": {
        "label": "Jordan — daily limit check",
        "description": "Price the book (yfinance) and evaluate limits; any "
                       "breach raises an alert (feed + macOS notification).",
        "timeout_s": 600,
        "writes": ["trading.db (alerts)"],
    },
    "weekly_review": {
        "label": "Alex — weekly review",
        "description": "Assemble the weekly review (regime week, vol summary, "
                       "research runs, risk flags, RCS activity) to markdown "
                       "+ PDF in reports/weekly/.",
        "timeout_s": 900,
        "writes": ["reports/weekly/"],
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
    path = (str(REPO_ROOT / VOL_DB_PATH)
            if not Path(VOL_DB_PATH).is_absolute() else VOL_DB_PATH)
    # A running pipeline subprocess briefly holds the trading.db write lock;
    # a submit() racing it must wait, not 500 (observed live 2026-07-18 when
    # a POST landed while jordan_daily_check was writing an alert).
    last = None
    for _ in range(20):
        try:
            conn = get_connection(path)
            break
        except Exception as e:
            last = e
            time.sleep(0.25)
    else:
        raise last
    conn.execute(_JOBS_DDL)
    # v1.0 Phase 6: dependency enforcement (Sarah blocks on Marcus success)
    conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS depends_on VARCHAR")
    # Per-job arguments as JSON (ad-hoc ticker batches, RCS intake provenance).
    # Passed to the child through JOB_ARGS_JSON, not argv, so the run_job
    # interface stays `python -m systems.orchestration.run_job <name>`.
    conn.execute("ALTER TABLE jobs ADD COLUMN IF NOT EXISTS args VARCHAR")
    return conn


def _read_conn():
    """
    Read-only connection for list/get. The jobs page polls these endpoints,
    and a writable connection per poll takes the exclusive DuckDB lock —
    which raced with running pipeline subprocesses (observed: a Sarah ticker
    write failing mid-job). Falls back to the writable path only if the
    jobs table does not exist yet.
    """
    import duckdb
    from config import VOL_DB_PATH
    path = (str(REPO_ROOT / VOL_DB_PATH)
            if not Path(VOL_DB_PATH).is_absolute() else VOL_DB_PATH)
    last = None
    for _ in range(3):
        try:
            conn = duckdb.connect(path, read_only=True)
            try:
                # Probe the newest column, not just the table: ALTER TABLE
                # lives in _conn(), so a DB predating a migration must be
                # routed through the writable path once to pick it up.
                conn.execute("SELECT args FROM jobs LIMIT 1")
            except (duckdb.CatalogException, duckdb.BinderException):
                conn.close()
                return _conn()   # first-ever call, or pre-migration schema
            return conn
        except duckdb.CatalogException:
            raise
        except Exception as e:
            last = e
            time.sleep(0.15)
    raise last


_JOB_COLS = """id, name, status, param_hashes, created_at, started_at,
               finished_at, exit_code, log_tail, error, requested_by,
               depends_on, args"""


def _row_to_dict(row) -> dict:
    keys = ["id", "name", "status", "param_hashes", "created_at", "started_at",
            "finished_at", "exit_code", "log_tail", "error", "requested_by",
            "depends_on", "args"]
    d = dict(zip(keys, row))
    for k in ("created_at", "started_at", "finished_at"):
        d[k] = str(d[k]) if d[k] is not None else None
    d["param_hashes"] = json.loads(d["param_hashes"]) if d["param_hashes"] else None
    d["args"] = json.loads(d["args"]) if d["args"] else None
    return d


def list_jobs(limit: int = 50) -> "list[dict]":
    conn = _read_conn()
    try:
        rows = conn.execute(
            f"SELECT {_JOB_COLS} FROM jobs ORDER BY created_at DESC LIMIT ?",
            [limit]
        ).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def get_job(job_id: str) -> "dict | None":
    conn = _read_conn()
    try:
        row = conn.execute(
            f"SELECT {_JOB_COLS} FROM jobs WHERE id = ?", [job_id]
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
            # Apply schema + migrations once via the writable path, so the
            # read-only list/get connections see every column (ALTER TABLE
            # lives in _conn(), which reads alone would never run).
            try:
                _conn().close()
            except Exception as e:
                logger.warning(f"jobs schema ensure failed (will retry on "
                               f"first write): {e}")
            self._thread = threading.Thread(
                target=self._worker, name="job-worker", daemon=True)
            self._thread.start()

    def submit(self, name: str, requested_by: str = "api",
               depends_on: "str | None" = None,
               args: "dict | None" = None) -> dict:
        """depends_on: a job id that must have SUCCEEDED before this job runs;
        otherwise this job fails with a dependency error (never runs).

        args: per-run arguments, persisted as JSON on the job row and handed
        to the child through the JOB_ARGS_JSON environment variable. Jobs that
        ignore it behave exactly as before, so scheduler_v2's existing callers
        are unaffected."""
        if name not in JOB_SPECS:
            raise KeyError(f"Unknown job '{name}'. Valid: {sorted(JOB_SPECS)}")
        from systems.params import all_active_hashes
        job_id = uuid.uuid4().hex[:12]
        args_json = json.dumps(args) if args else None
        conn = _conn()
        try:
            conn.execute(
                """INSERT INTO jobs (id, name, status, param_hashes, created_at,
                                     requested_by, depends_on, args)
                   VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)""",
                [job_id, name, json.dumps(all_active_hashes()),
                 datetime.now(), requested_by, depends_on, args_json],
            )
        finally:
            conn.close()
        self._queue.put(job_id)
        self.start()
        return {"id": job_id, "name": name, "status": "queued",
                "depends_on": depends_on, "args": args}

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

        # Phase 6 dependency enforcement: never run on a failed prerequisite.
        if job.get("depends_on"):
            dep = get_job(job["depends_on"])
            if dep is None or dep["status"] != "succeeded":
                dep_desc = (f"{dep['name']} ({dep['status']})" if dep
                            else f"missing job {job['depends_on']}")
                self._update(job_id, status="failed",
                             error=f"dependency not satisfied: {dep_desc}",
                             finished_at=datetime.now())
                logger.error(f"job {job_id} [{name}] blocked — {dep_desc}")
                try:
                    from systems.orchestration.alerts import raise_alert
                    raise_alert("jobs", "warning",
                                f"{name} skipped — dependency {dep_desc}")
                except Exception:
                    pass
                return

        with self._lock:
            self._current = job_id
        self._update(job_id, status="running", started_at=datetime.now())
        logger.info(f"job {job_id} [{name}] starting")

        env = None
        if job.get("args"):
            import os
            env = {**os.environ, "JOB_ARGS_JSON": json.dumps(job["args"])}

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "systems.orchestration.run_job", name],
                cwd=str(REPO_ROOT),
                capture_output=True, text=True,
                timeout=spec["timeout_s"],
                env=env,
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
                self._retry_or_alert(job, f"exit code {proc.returncode}")
        except subprocess.TimeoutExpired:
            self._update(job_id, status="failed", error="timeout",
                         finished_at=datetime.now())
            logger.error(f"job {job_id} [{name}] timed out")
            self._retry_or_alert(job, "timeout")

    def _retry_or_alert(self, job: dict, reason: str):
        """OpsParams-driven retries; alert only once retries are exhausted.
        Retry attempts are encoded in requested_by ('retry:<orig>:a<N>') so
        no schema change is needed and the chain is visible in the jobs list."""
        rb = job.get("requested_by") or ""
        attempts = 0
        if rb.startswith("retry:"):
            try:
                attempts = int(rb.rsplit(":a", 1)[1])
            except (ValueError, IndexError):
                attempts = 0
        try:
            from systems.params import get_params
            ops = get_params("ops")
            max_retries = int(ops.job_max_retries)
            wait_s = int(ops.job_retry_wait_seconds)
        except Exception:
            max_retries, wait_s = 0, 0

        if attempts < max_retries:
            logger.info(f"job {job['id']} [{job['name']}] retry "
                        f"{attempts + 1}/{max_retries} in {wait_s}s")
            time.sleep(min(wait_s, 300))
            origin = rb.split(":")[1] if rb.startswith("retry:") else job["id"]
            # Carry args forward: a retried batch job that lost its ticker
            # list would silently run the whole daily universe instead.
            self.submit(job["name"],
                        requested_by=f"retry:{origin}:a{attempts + 1}",
                        depends_on=job.get("depends_on"),
                        args=job.get("args"))
        else:
            try:
                from systems.orchestration.alerts import raise_alert
                raise_alert("jobs", "error",
                            f"job {job['name']} FAILED ({reason}) after "
                            f"{attempts + 1} attempt(s) — see Jobs page")
            except Exception as e:
                logger.error(f"failure alert could not be raised: {e}")

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
