"""
API-instance singleton enforcement.

The scheduler (scheduler_v2) and the job worker (JobManager) both live as
daemon threads inside the FastAPI process. Two API instances therefore means
two schedulers firing the same jobs AND two writers to DuckDB — the single-
writer discipline the whole v1.0 platform is built around collapses.

This module guarantees one API instance at a time. A new instance takes over
by SIGTERM-ing any stale owner (grace period, then SIGKILL), not by refusing
to start. The PID file also covers the `kill -9` case: a liveness check on
next startup detects the dead holder and takes over cleanly.

Stdlib only — os.kill, os.getpid, and `ps -p <pid> -o comm=` cover everything
on macOS/Linux. No psutil / filelock dependency.
"""
from __future__ import annotations

import os
import signal
import subprocess
import time
from pathlib import Path

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LOCK_FILE = REPO_ROOT / "data" / "api.pid"
TAKEOVER_TIMEOUT_S = 10.0   # SIGTERM grace period before SIGKILL
POLL_INTERVAL_S = 0.25


def _read_pid() -> "int | None":
    if not LOCK_FILE.exists():
        return None
    try:
        return int(LOCK_FILE.read_text().strip())
    except (ValueError, OSError):
        return None


def _alive(pid: int) -> bool:
    """
    True if `pid` refers to a live process.

    `os.kill(pid, 0)` sends no signal — it only checks existence. Two failure
    modes matter:
      - ProcessLookupError: the PID is gone → not alive (stale file, take over).
      - PermissionError: the process exists but we can't signal it (e.g. PID 1
        on macOS from a non-root caller) → it IS alive, just foreign. Treat as
        alive so we never try to take over from a process we can't inspect.
    """
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def _looks_like_ours(pid: int) -> bool:
    """
    Confirm the PID is one of our API processes before killing it.

    A PID can be reused by an unrelated process after the original dies, so a
    bare liveness check is unsafe — we'd risk SIGTERM-ing something innocent.
    Accept python/uvicorn command lines only.
    """
    try:
        out = subprocess.run(
            ["ps", "-p", str(pid), "-o", "comm="],
            capture_output=True, text=True, timeout=5,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        # ps unavailable — refuse to kill rather than risk a wrong target.
        return False
    comm = out.stdout.strip().lower()
    return bool(comm) and ("python" in comm or "uvicorn" in comm)


def _terminate(pid: int) -> None:
    """SIGTERM, poll for graceful exit, SIGKILL if it outlives the grace."""
    logger.info(f"instance lock: stale instance pid={pid} alive — SIGTERM")
    try:
        os.kill(pid, signal.SIGTERM)
    except (ProcessLookupError, PermissionError):
        return
    deadline = time.monotonic() + TAKEOVER_TIMEOUT_S
    while time.monotonic() < deadline:
        if not _alive(pid):
            logger.info(f"instance lock: pid={pid} exited cleanly")
            return
        time.sleep(POLL_INTERVAL_S)
    logger.warning(f"instance lock: pid={pid} did not exit in "
                   f"{TAKEOVER_TIMEOUT_S}s — SIGKILL")
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass
    # Let the OS reap it before we proceed to write our own PID.
    time.sleep(POLL_INTERVAL_S)


def acquire_instance_lock() -> None:
    """
    Take over as the sole API instance.

    Idempotent and safe against: no prior file, a stale (dead) PID, a live
    API that exits on SIGTERM, a live API that needs SIGKILL, and PID reuse
    by an unrelated process (refuses to kill, raises).
    """
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    pid = _read_pid()
    if pid is not None and _alive(pid):
        if not _looks_like_ours(pid):
            raise RuntimeError(
                f"instance lock held by pid={pid} which does not look like an "
                f"API process (PID reuse?). Refusing to kill it. Inspect "
                f"{LOCK_FILE} and remove it manually if you know it's stale."
            )
        _terminate(pid)
    elif pid is not None:
        logger.info(f"instance lock: stale pid={pid} is dead — taking over")
    LOCK_FILE.write_text(str(os.getpid()))
    logger.info(f"instance lock acquired (pid={os.getpid()}, file={LOCK_FILE})")


def release_instance_lock() -> None:
    """
    Release the lock iff the PID file still names us.

    A newer instance may have already taken over (SIGTERM'd us, wrote its own
    PID); in that case the file no longer belongs to us and must be left
    intact. Safe to call from a lifespan shutdown hook.
    """
    pid = _read_pid()
    if pid == os.getpid():
        try:
            LOCK_FILE.unlink()
            logger.info(f"instance lock released (pid={pid})")
        except FileNotFoundError:
            pass
