"""Parameter registry API — read, edit (versioned), history, rollback."""
from __future__ import annotations

import dataclasses

from fastapi import APIRouter, Body, HTTPException

from systems import params as P

router = APIRouter(prefix="/api/params", tags=["params"])


def _component_or_404(component: str):
    if component not in P.MODEL_BY_COMPONENT:
        raise HTTPException(404, f"unknown component '{component}'; "
                                 f"valid: {sorted(P.MODEL_BY_COMPONENT)}")


def _describe(component: str) -> dict:
    active = P.get_active(component)
    cls = P.MODEL_BY_COMPONENT[component]
    return {
        "component": component,
        "version": active.version,
        "hash": active.hash,
        "payload": active.model.to_dict(),
        "specs": cls.FIELD_SPECS,
    }


@router.get("")
def all_params() -> dict:
    return {c: _describe(c) for c in P.COMPONENTS}


@router.get("/{component}")
def one_component(component: str) -> dict:
    _component_or_404(component)
    return _describe(component)


@router.put("/{component}")
def edit_component(component: str, body: dict = Body(...)) -> dict:
    """
    Body: {"payload": {<partial or full field dict>}, "note": "why"}
    Creates and activates a new version. 422 on validation failure.
    """
    _component_or_404(component)
    payload = body.get("payload")
    if not isinstance(payload, dict) or not payload:
        raise HTTPException(422, "body.payload must be a non-empty object")
    note = str(body.get("note") or "")
    cls = P.MODEL_BY_COMPONENT[component]
    unknown = [k for k in payload
               if k not in {f.name for f in dataclasses.fields(cls)}]
    if unknown:
        raise HTTPException(422, f"unknown field(s) for {component}: {unknown}")
    try:
        active = P.set_params(component, payload, note=note)
    except ValueError as e:
        raise HTTPException(422, str(e))
    guarded = [k for k in payload if (cls.FIELD_SPECS.get(k) or {}).get("guarded")]
    recompute = sorted({
        (cls.FIELD_SPECS.get(k) or {}).get("recompute")
        for k in payload
        if (cls.FIELD_SPECS.get(k) or {}).get("recompute")
    })
    return {
        **_describe(component),
        "activated_version": active.version,
        "guarded_fields_changed": guarded,
        "recompute_suggested": recompute,   # e.g. ["backfill_regime_history"]
    }


@router.get("/{component}/history")
def history(component: str, limit: int = 50) -> dict:
    _component_or_404(component)
    return {"component": component, "history": P.get_history(component, limit=limit)}


@router.post("/{component}/activate/{version}")
def activate(component: str, version: int, body: dict = Body(default={})) -> dict:
    _component_or_404(component)
    try:
        active = P.activate_version(component, version,
                                    note=str(body.get("note") or ""))
    except ValueError as e:
        raise HTTPException(404, str(e))
    return _describe(component) | {"activated_version": active.version}


@router.get("-hashes")
def hashes() -> dict:
    return P.all_active_hashes()
