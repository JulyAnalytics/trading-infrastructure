"""Jobs API — trigger pipeline runs, poll status, browse history."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

from systems.orchestration.jobs import JOB_SPECS, MANAGER, get_job, list_jobs

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("/specs")
def specs() -> dict:
    return JOB_SPECS


@router.get("")
def recent(limit: int = 50) -> dict:
    return {"jobs": list_jobs(limit=limit), "running": MANAGER.current()}


@router.post("")
def submit(body: dict = Body(...)) -> dict:
    """Body: {name, requested_by?, depends_on?, args?}.

    args is a per-run JSON object handed to the child through JOB_ARGS_JSON —
    e.g. {"tickers": ["AMD","PLTR"]} to run sarah_daily_vol over an ad-hoc
    batch instead of the configured daily universe.
    """
    name = body.get("name")
    if not name:
        raise HTTPException(422, "body.name required")
    args = body.get("args")
    if args is not None and not isinstance(args, dict):
        raise HTTPException(422, "body.args must be an object")
    try:
        return MANAGER.submit(
            str(name),
            requested_by=str(body.get("requested_by") or "gui"),
            depends_on=body.get("depends_on"),
            args=args,
        )
    except KeyError as e:
        raise HTTPException(404, str(e))


@router.get("/{job_id}")
def one(job_id: str) -> dict:
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, f"no job {job_id}")
    return job
