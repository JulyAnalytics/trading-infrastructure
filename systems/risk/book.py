"""
Jordan's positions book.

Sources:
  1. RCS active trades (read-only bridge) — option legs become option
     positions, equity trades become share positions.
  2. Manual positions in trading.db `jordan_positions` (for anything not
     journaled in RCS).

`analyze_book()` prices the book live (yfinance via Sarah's GreeksTool) and
aggregates greeks + dollar exposures. Per-position failures degrade to an
errors list — one dead ticker must not blind the whole risk board.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime

from loguru import logger

_MANUAL_DDL = """
CREATE TABLE IF NOT EXISTS jordan_positions (
    id          VARCHAR PRIMARY KEY,
    ticker      VARCHAR NOT NULL,
    asset_type  VARCHAR NOT NULL,      -- 'option' | 'equity'
    flag        VARCHAR,               -- 'c' | 'p' (options)
    strike      DOUBLE,
    expiration  DATE,
    quantity    DOUBLE NOT NULL,       -- contracts (options) or shares
    long_short  VARCHAR NOT NULL,      -- 'long' | 'short'
    entry_price DOUBLE,
    entry_date  DATE,
    note        VARCHAR,
    status      VARCHAR NOT NULL DEFAULT 'active',
    created_at  TIMESTAMP DEFAULT current_timestamp
)
"""


def _conn():
    from config import VOL_DB_PATH
    from systems.utils.db import get_connection
    conn = get_connection(VOL_DB_PATH)
    conn.execute(_MANUAL_DDL)
    return conn


# ── Manual positions CRUD ────────────────────────────────────────────────────

def add_manual_position(p: dict) -> dict:
    pid = uuid.uuid4().hex[:12]
    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO jordan_positions
               (id, ticker, asset_type, flag, strike, expiration, quantity,
                long_short, entry_price, entry_date, note)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            [pid, p["ticker"].upper(), p["asset_type"], p.get("flag"),
             p.get("strike"), p.get("expiration"), float(p["quantity"]),
             p["long_short"], p.get("entry_price"),
             p.get("entry_date") or str(date.today()), p.get("note")],
        )
    finally:
        conn.close()
    return {"id": pid}


def close_manual_position(position_id: str) -> None:
    conn = _conn()
    try:
        conn.execute(
            "UPDATE jordan_positions SET status = 'closed' WHERE id = ?",
            [position_id],
        )
    finally:
        conn.close()


def _manual_positions() -> "list[dict]":
    conn = _conn()
    try:
        rows = conn.execute("""
            SELECT id, ticker, asset_type, flag, strike, expiration, quantity,
                   long_short, entry_price, entry_date, note
            FROM jordan_positions WHERE status = 'active' ORDER BY created_at
        """).fetchall()
    finally:
        conn.close()
    keys = ["id", "ticker", "asset_type", "flag", "strike", "expiration",
            "quantity", "long_short", "entry_price", "entry_date", "note"]
    out = []
    for r in rows:
        d = dict(zip(keys, r))
        d["expiration"] = str(d["expiration"])[:10] if d["expiration"] else None
        d["entry_date"] = str(d["entry_date"])[:10] if d["entry_date"] else None
        d["source"] = "manual"
        out.append(d)
    return out


# ── Book assembly ────────────────────────────────────────────────────────────

def _rcs_positions() -> "tuple[list[dict], dict]":
    from systems.risk import rcs_bridge
    if not rcs_bridge.available():
        return [], {"available": False, "reason": "RCS database not found"}
    try:
        trades = rcs_bridge.fetch_active_trades()
    except Exception as e:
        logger.warning(f"RCS positions unavailable: {e}")
        return [], {"available": False, "reason": str(e)}

    positions = []
    for t in trades:
        base = {
            "source": "rcs",
            "rcs_trade_id": t["id"],
            "rcs_url": None,
            "trade_name": t.get("name") or t.get("instrument") or t["id"],
            "ticker": (t.get("instrument") or "").upper(),
        }
        try:
            from systems.risk.rcs_bridge import entity_url
            base["rcs_url"] = entity_url("trade", t["id"])
        except Exception:
            pass

        open_legs = [l for l in t["legs"] if not l.get("date_closed")]
        if t["instrument_type"] == "option" and open_legs:
            for leg in open_legs:
                positions.append({
                    **base,
                    "id": f"rcs:{leg['id']}",
                    "asset_type": "option",
                    "flag": "c" if leg["type"] == "call" else "p",
                    "strike": float(leg["strike"]),
                    "expiration": str(leg["expiry"])[:10],
                    "quantity": float(leg["contracts"]),
                    "long_short": leg["direction"],
                    "entry_price": leg.get("entry_premium"),
                    "entry_date": str(leg.get("date_opened"))[:10],
                })
        elif t.get("net_size"):
            qty = float(t["net_size"])
            positions.append({
                **base,
                "id": f"rcs:{t['id']}",
                "asset_type": "equity",
                "flag": None, "strike": None, "expiration": None,
                "quantity": abs(qty),
                "long_short": "long" if qty >= 0 else "short",
                "entry_price": t.get("avg_entry_price"),
                "entry_date": str(t.get("created_at"))[:10],
            })
    return positions, {"available": True, "active_trades": len(trades)}


def load_book() -> dict:
    rcs_positions, rcs_status = _rcs_positions()
    manual = _manual_positions()
    return {
        "positions": rcs_positions + manual,
        "rcs": rcs_status,
        "counts": {"rcs": len(rcs_positions), "manual": len(manual)},
    }


# ── Live analysis ────────────────────────────────────────────────────────────

def analyze_book(book: "dict | None" = None) -> dict:
    """
    Price every position live and aggregate. Options go through
    GreeksTool.analyze_position; equities contribute delta only.
    """
    from systems.sarah.greeks_tool import GreeksTool

    book = book or load_book()
    tool = GreeksTool()
    analyses, errors = [], []
    option_results = []
    gross_notional = 0.0
    net_delta_dollars = 0.0
    net_vega_dollars = 0.0
    spot_cache: "dict[str, float]" = {}

    def spot_of(ticker: str) -> float:
        if ticker not in spot_cache:
            import yfinance as yf
            info = yf.Ticker(ticker).fast_info
            spot_cache[ticker] = float(
                info.get("lastPrice") or info.get("previousClose"))
        return spot_cache[ticker]

    for pos in book["positions"]:
        try:
            if pos["asset_type"] == "option":
                if not pos.get("expiration") or date.fromisoformat(
                        pos["expiration"]) <= date.today():
                    raise ValueError("expired or missing expiration")
                res = tool.analyze_position(
                    ticker=pos["ticker"], flag=pos["flag"],
                    strike=float(pos["strike"]), expiration=pos["expiration"],
                    quantity=int(pos["quantity"]), long_short=pos["long_short"],
                )
                spot = res["market"]["spot"]
                delta_sh = res["greeks_scaled"]["delta"]
                notional = abs(float(pos["strike"])) * pos["quantity"] * 100
                entry = {
                    "position": pos,
                    "market": res["market"],
                    "greeks_scaled": res["greeks_scaled"],
                    "delta_dollars": round(delta_sh * spot, 2),
                    "vega_dollars": round(res["greeks_scaled"]["vega"], 2),
                    "notional": round(notional, 2),
                    "bs_flag": res["bs_flag"],
                }
                option_results.append(res)
            else:
                spot = spot_of(pos["ticker"])
                sign = 1 if pos["long_short"] == "long" else -1
                delta_sh = sign * pos["quantity"]
                notional = abs(pos["quantity"]) * spot
                entry = {
                    "position": pos,
                    "market": {"spot": spot},
                    "greeks_scaled": {"delta": delta_sh, "gamma": 0.0,
                                      "theta_daily": 0.0, "vega": 0.0,
                                      "vanna": 0.0, "charm": 0.0, "vomma": 0.0},
                    "delta_dollars": round(delta_sh * spot, 2),
                    "vega_dollars": 0.0,
                    "notional": round(notional, 2),
                    "bs_flag": None,
                }
            gross_notional += entry["notional"]
            net_delta_dollars += entry["delta_dollars"]
            net_vega_dollars += entry["vega_dollars"]
            analyses.append(entry)
        except Exception as e:
            errors.append({"position": pos, "error": str(e)})
            logger.warning(f"book analysis failed for {pos.get('id')}: {e}")

    portfolio = GreeksTool().aggregate_portfolio(
        [{"greeks_scaled": a["greeks_scaled"]} for a in analyses]
    ) if analyses else {"net_greeks": {}, "concentration_flags": []}

    return {
        "as_of": datetime.now().isoformat(timespec="seconds"),
        "positions_analyzed": len(analyses),
        "errors": errors,
        "analyses": analyses,
        "net_greeks": portfolio["net_greeks"],
        "concentration_flags": portfolio["concentration_flags"],
        "net_delta_dollars": round(net_delta_dollars, 2),
        "net_vega_dollars": round(net_vega_dollars, 2),
        "gross_notional": round(gross_notional, 2),
        "rcs": book.get("rcs"),
        "data_warning": "yfinance 15–20 min delayed. Not for live pre-trade decisions.",
    }
