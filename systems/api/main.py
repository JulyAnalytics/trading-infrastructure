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
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
# All DB paths in config are repo-relative; pin the working directory so the
# API behaves identically no matter where uvicorn is launched from.
os.chdir(REPO_ROOT)

from fastapi import FastAPI  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

from systems.api.routes import context, jobs, jordan, marcus, params, sarah  # noqa: E402
from systems.orchestration.jobs import MANAGER  # noqa: E402

app = FastAPI(
    title="Trading Infrastructure Workstation",
    version="1.0.0-phase1",
    description="FastAPI service layer over Marcus/Sarah/Priya/Jordan engines, "
                "the parameter registry, and the job runner.",
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


@app.on_event("startup")
def _startup():
    MANAGER.start()


if __name__ == "__main__":
    import uvicorn
    from config import API_HOST, API_PORT
    uvicorn.run(app, host=API_HOST, port=API_PORT)
