"""Alex ops API — alert feed, weekly review archive, scheduler status."""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
WEEKLY_DIR = REPO_ROOT / "reports" / "weekly"

router = APIRouter(prefix="/api/ops", tags=["ops"])


@router.get("/alerts")
def alerts(limit: int = 50, unacked_only: bool = False) -> dict:
    from systems.orchestration.alerts import list_alerts
    return {"alerts": list_alerts(limit=limit, unacked_only=unacked_only)}


@router.post("/alerts/{alert_id}/ack")
def ack(alert_id: str) -> dict:
    from systems.orchestration.alerts import ack_alert
    ack_alert(alert_id)
    return {"acked": alert_id}


@router.get("/weekly-reviews")
def weekly_reviews() -> dict:
    if not WEEKLY_DIR.exists():
        return {"reviews": []}
    files = sorted(WEEKLY_DIR.glob("weekly_review_*.md"), reverse=True)
    return {"reviews": [
        {"name": f.stem, "markdown": f.name,
         "pdf": f.with_suffix(".pdf").name
                if f.with_suffix(".pdf").exists() else None,
         "modified": f.stat().st_mtime}
        for f in files
    ]}


@router.get("/weekly-reviews/{name}")
def weekly_review_content(name: str) -> dict:
    # name is the stem, e.g. weekly_review_2026-07-18 — no path traversal
    if "/" in name or ".." in name:
        raise HTTPException(422, "invalid name")
    p = WEEKLY_DIR / f"{name}.md"
    if not p.exists():
        raise HTTPException(404, f"no review '{name}'")
    return {"name": name, "markdown": p.read_text()}


@router.get("/schedule")
def schedule() -> dict:
    """Current scheduler v2 configuration + last outcome per scheduled job."""
    from systems.orchestration.jobs import list_jobs
    from systems.params import get_params
    ops = get_params("ops")
    entries = [
        {"job": "fred_incremental → marcus_classify → snapshot_pdf",
         "when": f"weekdays {ops.daily_pipeline_time} "
                 f"(snapshot {ops.snapshot_time})"},
        {"job": "sarah_daily_vol → jordan_daily_check",
         "when": f"weekdays {ops.vol_run_time} — Sarah blocks on Marcus "
                 "success when the regime is stale"},
        {"job": "fred_full", "when": f"Sunday {ops.weekly_refresh_time}"},
        {"job": "weekly_review",
         "when": f"Friday {getattr(ops, 'weekly_review_time', '17:00')}"},
    ]
    last: dict = {}
    for j in list_jobs(limit=200):
        if j["name"] not in last:
            last[j["name"]] = {"status": j["status"],
                               "created_at": j["created_at"],
                               "requested_by": j["requested_by"]}
    return {"enabled": bool(getattr(ops, "scheduler_enabled", True)),
            "retries": {"max": ops.job_max_retries,
                        "wait_s": ops.job_retry_wait_seconds},
            "entries": entries,
            "last_runs": last}
