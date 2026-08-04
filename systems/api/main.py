"""
v1.0 workstation API.

Run:
    uvicorn systems.api.main:app --host 127.0.0.1 --port 8100
or:
    python -m systems.api.main
"""
from __future__ import annotations

import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
# All DB paths in config are repo-relative; pin the working directory so the
# API behaves identically no matter where uvicorn is launched from.
os.chdir(REPO_ROOT)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from systems.api.routes import (  # noqa: E402
    context, jobs, jordan, marcus, ops, params, priya, reports, sarah,
)
from systems.orchestration.instance import (  # noqa: E402
    acquire_instance_lock, release_instance_lock,
)
from systems.orchestration.jobs import MANAGER  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── startup ──
    # Singleton guard: take over from any stale API instance before we touch
    # the scheduler / JobManager / DuckDB. Kills a live stale owner by SIGTERM
    # (grace) then SIGKILL; cleans up a dead PID file from a `kill -9`.
    acquire_instance_lock()
    MANAGER.start()
    # Phase 6 scheduler v2 — OpsParams-driven; master switch:
    # ops.scheduler_enabled (Parameters page).
    from systems.orchestration.scheduler_v2 import SCHEDULER
    SCHEDULER.start()
    yield
    # ── shutdown ──
    # FastAPI routes SIGTERM/SIGINT through this block before exit, so the
    # scheduler thread stops cooperatively and the PID file is released only
    # if it still names us (a newer instance may have already taken over).
    SCHEDULER.stop()
    release_instance_lock()


app = FastAPI(
    title="Leopold API",
    version="1.0.0-phase1",
    description="FastAPI service layer over Marcus/Sarah/Priya/Jordan engines, "
                "the parameter registry, and the job runner.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173", "http://127.0.0.1:5173",   # vite dev
        "http://localhost:4173", "http://127.0.0.1:4173",   # vite preview
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(params.router)
app.include_router(jobs.router)
app.include_router(context.router)
app.include_router(marcus.router)
app.include_router(jordan.router)
app.include_router(sarah.router)
app.include_router(priya.router)
app.include_router(ops.router)
app.include_router(reports.router)


@app.get("/health")
def health() -> dict:
    from systems.params import all_active_hashes
    checks = {"api": "ok"}
    try:
        checks["param_hashes"] = all_active_hashes()
        checks["registry"] = "ok"
    except Exception as e:
        checks["registry"] = f"error: {e}"
    for label, path in [("macro_db", "data/processed/macro.db"),
                        ("trading_db", "data/processed/trading.db")]:
        checks[label] = "ok" if (REPO_ROOT / path).exists() else "missing"
    checks["job_running"] = MANAGER.current()
    return checks


if __name__ == "__main__":
    import uvicorn
    from config import API_HOST, API_PORT
    uvicorn.run(app, host=API_HOST, port=API_PORT)
