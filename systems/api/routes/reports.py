"""Reports archive API — browseable listing + PDF serving for every generated report.

Adding a new report source is one entry in REPORT_SOURCES below; the listing
and viewer endpoints (and the frontend Reports page) pick it up automatically.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent

# Registry of report directories. Each entry: a stable URL key, a human label,
# and the directory to scan. New PDF sources → add one line here.
REPORT_SOURCES = [
    {"key": "snapshots", "label": "Marcus Snapshots",
     "dir": REPO_ROOT / "data" / "snapshots"},
    {"key": "weekly", "label": "Weekly Reviews",
     "dir": REPO_ROOT / "reports" / "weekly"},
]
_SOURCES_BY_KEY = {s["key"]: s for s in REPORT_SOURCES}

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
def list_reports() -> dict:
    """All PDF reports across every registered source, newest first."""
    items = []
    for src in REPORT_SOURCES:
        d: Path = src["dir"]
        if not d.exists():
            continue
        for f in d.glob("*.pdf"):
            st = f.stat()
            items.append({
                "category": src["key"],
                "category_label": src["label"],
                "name": f.name,
                "stem": f.stem,
                "size": st.st_size,
                "modified": st.st_mtime,
            })
    items.sort(key=lambda r: r["modified"], reverse=True)
    return {
        "reports": items,
        "categories": [{"key": s["key"], "label": s["label"]} for s in REPORT_SOURCES],
    }


@router.get("/{category}/{name}")
def serve_report(category: str, name: str):
    """Stream a single PDF. Path-traversal guarded two ways."""
    if category not in _SOURCES_BY_KEY:
        raise HTTPException(404, f"unknown report category '{category}'")
    # name is a filename only — reject any path separator or traversal outright.
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(422, "invalid name")
    src = _SOURCES_BY_KEY[category]
    base = src["dir"].resolve()
    p = (base / name).resolve()
    # Defence in depth: resolved path must stay inside the source dir.
    try:
        p.relative_to(base)
    except ValueError:
        raise HTTPException(422, "invalid name")
    if not p.exists() or p.suffix.lower() != ".pdf":
        raise HTTPException(404, f"no report '{name}'")
    return FileResponse(p, media_type="application/pdf", filename=name)
