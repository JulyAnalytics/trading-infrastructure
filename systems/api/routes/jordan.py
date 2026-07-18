"""Jordan workspace API — book, live risk analysis, limits, intake, sizing."""
from __future__ import annotations

from fastapi import APIRouter, Body, HTTPException

router = APIRouter(prefix="/api/jordan", tags=["jordan"])


@router.get("/book")
def book() -> dict:
    from systems.risk.book import load_book
    return load_book()


@router.post("/analyze")
def analyze(body: dict = Body(default={})) -> dict:
    """
    Live-price the book (yfinance, delayed), evaluate limits, and optionally
    stress it. Body: {"include_stress": bool}
    """
    from systems.risk.book import analyze_book
    from systems.risk.limits import evaluate_limits
    analysis = analyze_book()
    result = {"analysis": analysis, "limits": evaluate_limits(analysis)}
    if body.get("include_stress"):
        from systems.risk.stress import stress_book
        result["stress"] = stress_book(analysis)
    return result


@router.post("/positions")
def add_position(body: dict = Body(...)) -> dict:
    from systems.risk.book import add_manual_position
    required = {"ticker", "asset_type", "quantity", "long_short"}
    missing = required - set(k for k, v in body.items() if v not in (None, ""))
    if missing:
        raise HTTPException(422, f"missing fields: {sorted(missing)}")
    if body["asset_type"] == "option":
        for f in ("flag", "strike", "expiration"):
            if not body.get(f):
                raise HTTPException(422, f"option positions require '{f}'")
    return add_manual_position(body)


@router.post("/positions/{position_id}/close")
def close_position(position_id: str) -> dict:
    from systems.risk.book import close_manual_position
    close_manual_position(position_id)
    return {"closed": position_id}


@router.get("/verdict-intake")
def verdict_intake() -> dict:
    from systems.risk.verdict_intake import intake
    return intake()


@router.post("/size")
def size(body: dict = Body(...)) -> dict:
    from systems.risk.verdict_intake import suggest_size
    try:
        return suggest_size(
            entry=float(body["entry"]),
            stop=float(body["stop"]),
            risk_pct=float(body["risk_pct"]) if body.get("risk_pct") else None,
        )
    except (KeyError, TypeError):
        raise HTTPException(422, "body requires numeric 'entry' and 'stop'")
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.get("/rcs-activity")
def rcs_activity(days: int = 7) -> dict:
    from systems.risk.rcs_bridge import weekly_activity
    return weekly_activity(days=days)
