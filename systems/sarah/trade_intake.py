# systems/sarah/trade_intake.py
"""
Sarah ← RCS trade intake (spec: sarah-rcs-trade-intake-spec.md).

When a trade is committed in RCS, Sarah should be able to analyse it. Three
things stood in the way, and this module closes all three:

  1. The vol data may not exist — a trade on a ticker outside
     `sarah.vol_tickers` has no vol_signals/vol_surface rows. Intake enqueues
     a `sarah_daily_vol` batch for exactly that ticker.
  2. Some inputs are nowhere in either system. Sarah's discipline is *she
     prices; you supply the belief* — `expected_move` is the user's forecast
     and has no derivation. It lives in `sarah_trade_inputs`, trading-side.
  3. Nothing connected the two. A trade going idea→active (and, when
     `sarah.intake_fire_on_idea` is on, being created as an idea) is recorded
     in RCS `entity_events`; this module reads that read-only and enqueues.

Two phases, deliberately split so no analysis waits on judgment:
  Phase A — data-ready: the moment the job succeeds, the vol monitor and the
            greeks/scenario lab for the exact position are live. Zero input.
  Phase B — memo-ready: only the pre-trade memo waits, and only for
            `expected_move`.

Compliance:
  - ADR-003 — RCS is opened `mode=ro` via `systems.risk.rcs_bridge`. Every
    Class-C and provenance field lives in trading.db. RCS is never written.
  - Single-writer discipline — the poll does no vol writes; it reads RCS and
    submits onto the existing single job queue. The metadata writes here are
    small and lock-tolerant (same pattern as the jobs table and Jordan book).
  - ADR-005 — this is the deterministic `trade → Sarah` analysis seam. The
    future LLM layer calls the same entry points instead of improvising.
"""
from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

from loguru import logger

from config import VOL_DB_PATH
from systems.params import get_params
from systems.utils.db import get_connection

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Only option trades need a vol pull; an equity activation is skipped by
# design (spec §10).
_OPTION_INSTRUMENT_TYPE = "option"

# The epoch used when the watermark has never been set — reads the whole
# entity_events history once, then advances.
EPOCH = "1970-01-01T00:00:00Z"

# Class-C fields the memo needs. `expected_move` is the only one with no
# derivation at all; the rest are pre-filled from Class A/B and only surface
# when the derivation came back empty.
_MEMO_REQUIRED = ("expected_move", "thesis_days", "catalyst_type",
                  "max_loss_budget")

_COLUMNS = (
    "rcs_trade_ulid", "ticker", "expected_move", "expected_move_sign",
    "thesis_days", "catalyst_type", "max_loss_budget", "flow_json",
    "source", "created_at", "updated_at", "last_error", "rcs_instrument",
    "user_overrides", "rcs_synced_at",
)

# Fields RCS (or the auto-resolvers) own. A re-pull refreshes these unless the
# user explicitly overrode them — that is what `user_overrides` records.
# `expected_move` is deliberately NOT here: it has no derivation, so nothing
# upstream can ever set or refresh it.
_RCS_DERIVED = ("expected_move_sign", "thesis_days", "catalyst_type",
                "max_loss_budget")


# ── trading.db access ────────────────────────────────────────────────────────

def _connect_write(retries: int = 4, backoff_s: float = 0.4):
    """Writable trading.db connection with a short retry — a running pipeline
    subprocess holds the write lock in brief bursts, and an intake metadata
    write should wait rather than fail. A persistently held lock still raises
    so real contention stays loud."""
    last = None
    for attempt in range(retries):
        try:
            return get_connection(VOL_DB_PATH)
        except Exception as e:
            last = e
            if attempt < retries - 1:
                time.sleep(backoff_s * (attempt + 1))
    raise last


def _connect_read():
    """Read-only trading.db connection for pure reads.

    DuckDB allows one writer OR many readers, so a GET that took the writable
    path would contend with a running pipeline job for no reason. Falls back
    to the writable path only when the intake tables do not exist yet (their
    DDL lives there), which happens at most once.
    """
    import duckdb
    try:
        conn = duckdb.connect(_abs(VOL_DB_PATH), read_only=True)
    except Exception:
        conn = _connect_write()
        _ensure_schema(conn)
        return conn
    try:
        # Probe the newest column: ALTER TABLE lives on the writable path, so
        # a DB predating a migration has to be routed through it once.
        conn.execute("SELECT rcs_instrument FROM sarah_trade_inputs LIMIT 1")
        conn.execute("SELECT last_occurred_at FROM sarah_intake_watermark LIMIT 1")
        return conn
    except Exception:
        conn.close()
        conn = _connect_write()
        _ensure_schema(conn)
        return conn


def _ensure_schema(conn) -> None:
    from systems.sarah.vol_db import (
        SARAH_INTAKE_WATERMARK_DDL, SARAH_TRADE_INPUTS_DDL,
        _SARAH_TRADE_INPUTS_MIGRATIONS,
    )
    conn.execute(SARAH_TRADE_INPUTS_DDL)
    conn.execute(SARAH_INTAKE_WATERMARK_DDL)
    for stmt in _SARAH_TRADE_INPUTS_MIGRATIONS:
        conn.execute(stmt)


def _row_to_dict(row) -> "dict | None":
    if row is None:
        return None
    d = dict(zip(_COLUMNS, row))
    for k in ("created_at", "updated_at", "rcs_synced_at"):
        d[k] = str(d[k]) if d[k] is not None else None
    d["flow"] = json.loads(d["flow_json"]) if d["flow_json"] else None
    try:
        d["user_overrides"] = json.loads(d["user_overrides"] or "[]")
    except ValueError:
        d["user_overrides"] = []
    return d


# ── Watermark ────────────────────────────────────────────────────────────────

def get_watermark() -> str:
    """Last processed RCS event timestamp, in RCS's own text format so it can
    be compared lexicographically against `entity_events.occurred_at`."""
    conn = _connect_read()
    try:
        row = conn.execute(
            "SELECT last_occurred_at FROM sarah_intake_watermark WHERE id = 1"
        ).fetchone()
    finally:
        conn.close()
    if not row or row[0] is None:
        return EPOCH
    return _to_rcs_ts(row[0])


def set_watermark(occurred_at: str) -> None:
    """Advance the watermark. Never moves backwards — a re-run of an old
    explicit intake must not cause the poll to replay history."""
    current = get_watermark()
    if occurred_at <= current:
        return
    conn = _connect_write()
    try:
        _ensure_schema(conn)
        conn.execute(
            """INSERT INTO sarah_intake_watermark (id, last_occurred_at)
               VALUES (1, ?)
               ON CONFLICT (id) DO UPDATE SET last_occurred_at = excluded.last_occurred_at""",
            [_from_rcs_ts(occurred_at)],
        )
    finally:
        conn.close()


def _from_rcs_ts(ts: str) -> "datetime.datetime":
    """'2026-08-03T18:10:26Z' → naive UTC datetime for the TIMESTAMP column."""
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).replace(
        tzinfo=None)


def _to_rcs_ts(dt) -> str:
    """TIMESTAMP → RCS's text format. Whole seconds, matching how RCS writes
    them, so the round trip is exact and no event is replayed or skipped."""
    if isinstance(dt, str):
        return dt if dt.endswith("Z") else dt.replace(" ", "T") + "Z"
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


# ── Class-A/B derivation (§6) ────────────────────────────────────────────────

def resolve_ticker(instrument: str) -> str:
    """Position ticker → the options-liquid underlier Sarah analyses.

    Leveraged/inverse ETFs and thin names have no yfinance options chain; the
    user maps them once in `sarah.underlier_map` and it is reused for every
    trade on that ticker. Unmapped tickers pass through unchanged — if they
    turn out to have no chain, the vol job fails for them and the failure is
    recorded as the blocking "which underlier?" question (§11).
    """
    t = (instrument or "").strip().upper()
    mapping = {k.upper(): v.upper()
               for k, v in (get_params("sarah").underlier_map or {}).items()}
    return mapping.get(t, t)


def _sign_from_legs(trade: dict) -> "int | None":
    """Single long call → +1, single long put → −1. Spreads/straddles/ratios
    are ambiguous and stay None — the memo treats the sign as optional, and it
    only affects the skew-cost read."""
    legs = trade.get("legs") or []
    meta = trade.get("options_meta") or {}
    if meta.get("strategy_type") and str(meta["strategy_type"]).lower() not in (
            "single", "long_call", "long_put"):
        return None
    if len(legs) != 1:
        return None
    leg = legs[0]
    if str(leg.get("direction", "")).lower() != "long":
        return None
    kind = str(leg.get("type", "")).lower()
    return {"call": 1, "put": -1}.get(kind)


def _total_contracts(trade: dict) -> int:
    return sum(int(l.get("contracts") or 0) for l in (trade.get("legs") or []))


def _max_loss_budget(trade: dict) -> "float | None":
    """$/contract budget, by the §6 precedence:
       1. trade_options_meta.max_loss_dollar when max_loss_defined, ÷ contracts
       2. else thesis.worst_case_dollar ÷ total contracts
       3. else None → Class-C prompt

    Contract-count handling, which is the trap here: legs that exist but sum
    to ZERO contracts is corrupt data, and dividing by a fallback of 1 would
    silently return the whole max-loss as if it were the per-contract figure.
    That returns None instead (→ prompt). No legs at all is different and
    legitimate — the trade hasn't been broken into contracts yet, so the
    worst case IS the position budget, divided by 1.
    """
    legs = trade.get("legs") or []
    contracts = _total_contracts(trade)
    if legs and contracts <= 0:
        logger.warning(
            "intake: {} has {} leg(s) summing to {} contracts — cannot derive a "
            "per-contract budget; leaving it as a user prompt.",
            trade.get("id"), len(legs), contracts)
        return None
    divisor = contracts if contracts > 0 else 1

    meta = trade.get("options_meta") or {}
    if meta.get("max_loss_defined") and meta.get("max_loss_dollar") is not None:
        return round(float(meta["max_loss_dollar"]) / divisor, 2)
    thesis = trade.get("thesis") or {}
    if thesis.get("worst_case_dollar") is not None:
        return round(float(thesis["worst_case_dollar"]) / divisor, 2)
    return None


def _dominant_expiry_dte(trade: dict) -> "int | None":
    """DTE of the single dominant leg expiry, offered as the thesis_days
    default when the catalyst resolver comes back empty (§6)."""
    expiries = {l.get("expiry") for l in (trade.get("legs") or [])
                if l.get("expiry")}
    if len(expiries) != 1:
        return None
    try:
        exp = datetime.date.fromisoformat(str(next(iter(expiries)))[:10])
    except ValueError:
        return None
    dte = (exp - datetime.date.today()).days
    return dte if dte > 0 else None


def _abs(path: str) -> str:
    p = Path(path)
    return str(p if p.is_absolute() else _REPO_ROOT / p)


def _macro_readonly():
    """Read-only macro.db connection for the catalyst resolver.

    resolve_catalyst() opens a WRITABLE connection when handed none, which
    would have the poll (running inside the API process) contend for macro.db's
    single write lock with the FRED jobs. Reading is all it needs.
    Returns None if macro.db is unavailable — the caller degrades to a prompt.
    """
    try:
        import duckdb

        from config import DUCKDB_PATH
        return duckdb.connect(_abs(DUCKDB_PATH), read_only=True)
    except Exception as e:
        logger.warning("intake: macro.db unavailable for catalyst lookup — {}", e)
        return None


def derive_prefills(trade: dict, ticker: str, macro_conn=None,
                    skip_catalyst: bool = False) -> dict:
    """Everything Class A/B can fill so the user is never asked for it.

    skip_catalyst: leave `catalyst_type`/`thesis_days` unresolved. The
    catalyst lookup hits yfinance, so the periodic re-sync passes this when a
    catalyst is already known — re-deriving it every five minutes for every
    open trade would earn a rate-limit for no new information. The leg/meta
    derivations below are pure SQLite reads and always run.

    Never raises — a catalyst lookup that fails degrades to a Class-C prompt
    rather than blocking the vol pull, which needs none of this.
    """
    out: dict = {
        "expected_move_sign": _sign_from_legs(trade),
        "max_loss_budget": _max_loss_budget(trade),
        "catalyst_type": None,
        "thesis_days": None,
    }
    if skip_catalyst:
        dte = _dominant_expiry_dte(trade)
        if dte is not None:
            out["thesis_days"] = dte
            out["thesis_days_source"] = "dominant leg expiry (DTE)"
        return out

    own_conn = None
    if macro_conn is None:
        own_conn = macro_conn = _macro_readonly()
    try:
        from systems.sarah.catalyst_calendar import resolve_catalyst
        cat = resolve_catalyst(ticker, macro_conn=macro_conn)
        if not cat.get("requires_manual") and cat.get("primary"):
            out["catalyst_type"] = cat["primary"]["catalyst_type"]
            out["thesis_days"] = cat["primary"]["thesis_days"]
            out["catalyst_detail"] = cat["primary"]
        else:
            out["catalyst_note"] = cat.get("note")
    except Exception as e:   # network/DB hiccup must not block intake
        logger.warning("intake: catalyst resolution failed for {} — {}",
                       ticker, e)
        out["catalyst_note"] = f"catalyst lookup failed: {e}"
    finally:
        if own_conn is not None:
            own_conn.close()

    if out["thesis_days"] is None:
        # No catalyst, but a single dominant expiry is still a defensible
        # horizon default — the position expires when it expires.
        dte = _dominant_expiry_dte(trade)
        if dte is not None:
            out["thesis_days"] = dte
            out["thesis_days_source"] = "dominant leg expiry (DTE)"
    return out


# ── sarah_trade_inputs read/write ────────────────────────────────────────────

def get_trade_inputs(rcs_trade_ulid: str) -> "dict | None":
    conn = _connect_read()
    try:
        row = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM sarah_trade_inputs "
            "WHERE rcs_trade_ulid = ?", [rcs_trade_ulid]).fetchone()
    finally:
        conn.close()
    return _row_to_dict(row)


def list_trade_inputs(limit: int = 100) -> "list[dict]":
    conn = _connect_read()
    try:
        rows = conn.execute(
            f"SELECT {', '.join(_COLUMNS)} FROM sarah_trade_inputs "
            "ORDER BY updated_at DESC LIMIT ?", [limit]).fetchall()
    finally:
        conn.close()
    return [_row_to_dict(r) for r in rows]


def upsert_from_rcs(rcs_trade_ulid: str, ticker: str, rcs_instrument: str,
                    prefills: dict) -> dict:
    """Create or **re-pull** the intake row from RCS-derived values.

    Merge rule — per-field provenance, not "never overwrite":

      - `expected_move` is never touched. It has no derivation; nothing
        upstream can set it, so a re-pull can never disturb your belief.
      - Every other Class-A/B field (`thesis_days`, `catalyst_type`,
        `max_loss_budget`, `expected_move_sign`) is **refreshed from RCS**
        unless it appears in `user_overrides` — i.e. unless you set it
        deliberately through the PUT endpoint.
      - `ticker` / `rcs_instrument` always refresh (the underlier map may have
        gained an entry since).

    The earlier rule here was "any stored value wins", which froze Class-B
    data: capture a leg or a defined max loss in RCS after the first intake
    and the refreshed value was discarded. That is the bug this fixes — RCS
    owns the position, you own the belief, and the two no longer collide.

    A derivation that comes back None never blanks a stored value: a catalyst
    lookup failing offline must not erase a good horizon.
    """
    existing = get_trade_inputs(rcs_trade_ulid)
    overrides = set(existing.get("user_overrides") or []) if existing else set()

    merged = {"expected_move": existing.get("expected_move") if existing else None,
              "flow_json": existing.get("flow_json") if existing else None,
              "source": "rcs_intake"}
    for field in _RCS_DERIVED:
        stored = existing.get(field) if existing else None
        fresh = prefills.get(field)
        if field in overrides:
            merged[field] = stored          # your explicit choice wins
        elif fresh is not None:
            merged[field] = fresh           # RCS/resolver is the owner
        else:
            merged[field] = stored          # nothing new — keep what we had

    if existing and existing.get("source") == "user":
        merged["source"] = "user"

    conn = _connect_write()
    try:
        _ensure_schema(conn)
        conn.execute("""
            INSERT INTO sarah_trade_inputs (
                rcs_trade_ulid, ticker, rcs_instrument, expected_move,
                expected_move_sign, thesis_days, catalyst_type,
                max_loss_budget, flow_json, source, user_overrides,
                created_at, updated_at, rcs_synced_at, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, now(), now(), now(), NULL)
            ON CONFLICT (rcs_trade_ulid) DO UPDATE SET
                ticker             = excluded.ticker,
                rcs_instrument     = excluded.rcs_instrument,
                expected_move      = excluded.expected_move,
                expected_move_sign = excluded.expected_move_sign,
                thesis_days        = excluded.thesis_days,
                catalyst_type      = excluded.catalyst_type,
                max_loss_budget    = excluded.max_loss_budget,
                flow_json          = excluded.flow_json,
                source             = excluded.source,
                updated_at         = now(),
                rcs_synced_at      = now(),
                last_error         = NULL
        """, [
            rcs_trade_ulid, ticker.upper(), (rcs_instrument or "").upper(),
            merged["expected_move"], merged["expected_move_sign"],
            merged["thesis_days"], merged["catalyst_type"],
            merged["max_loss_budget"], merged["flow_json"], merged["source"],
            json.dumps(sorted(overrides)),
        ])
    finally:
        conn.close()
    return get_trade_inputs(rcs_trade_ulid)


def update_user_inputs(rcs_trade_ulid: str, fields: dict,
                       source: str = "user") -> dict:
    """Apply the user's Class-C answers. Only the fields present in `fields`
    are touched; the row must already exist (intake creates it).

    Each Class-A/B field set here is recorded in `user_overrides`, which is
    what stops a later re-pull from reverting your deliberate choice. Setting
    a field back to null REMOVES the override — that is how you hand a field
    back to RCS and let the derivation own it again.

    `expected_move` is validated as an unsigned decimal fraction here as well
    as at the endpoint — 0.20 means ±20%, and a stray 20 would price a 2000%
    move through forward*(1±expected_move).
    """
    existing = get_trade_inputs(rcs_trade_ulid)
    if not existing:
        raise KeyError(f"no intake row for trade {rcs_trade_ulid}")
    overrides = set(existing.get("user_overrides") or [])

    allowed = ("expected_move", "expected_move_sign", "thesis_days",
               "catalyst_type", "max_loss_budget", "flow_json", "ticker")
    sets, vals = [], []
    for k in allowed:
        if k not in fields:
            continue
        v = fields[k]
        if k == "expected_move" and v is not None:
            v = validate_expected_move(v)
        if k == "ticker" and v is not None:
            v = str(v).upper()
        if k == "flow_json" and isinstance(v, (dict, list)):
            v = json.dumps(v)
        if k in _RCS_DERIVED:
            overrides.add(k) if v is not None else overrides.discard(k)
        sets.append(f"{k} = ?")
        vals.append(v)
    if not sets:
        return get_trade_inputs(rcs_trade_ulid)
    sets.append("user_overrides = ?")
    vals.append(json.dumps(sorted(overrides)))
    sets.append("source = ?")
    vals.append(source)
    sets.append("updated_at = now()")
    vals.append(rcs_trade_ulid)

    conn = _connect_write()
    try:
        _ensure_schema(conn)
        conn.execute(
            f"UPDATE sarah_trade_inputs SET {', '.join(sets)} "
            "WHERE rcs_trade_ulid = ?", vals)
    finally:
        conn.close()
    return get_trade_inputs(rcs_trade_ulid)


def record_error(rcs_trade_ulid: str, message: "str | None") -> None:
    """Record (or clear) the per-trade blocking failure — a vol pull that
    failed even after the underlier map. Surfaced through `needs_user` in the
    same channel as the "which underlier?" prompt rather than leaving Sarah
    silently empty (§11)."""
    conn = _connect_write()
    try:
        _ensure_schema(conn)
        conn.execute(
            "UPDATE sarah_trade_inputs SET last_error = ?, updated_at = now() "
            "WHERE rcs_trade_ulid = ?", [message, rcs_trade_ulid])
    finally:
        conn.close()


MAX_EXPECTED_MOVE = 1.5
# Below this the memo is arithmetically degenerate rather than merely small:
# candidate strikes are forward*(1 ± expected_move), so a zero move collapses
# the ATM and both OTM strikes onto one another, makes every spread a
# long-and-short of the identical contract (cost 0), and evaluates "P&L at
# +move" and "at −move" at the same unchanged spot. The memo still renders,
# which is what makes it dangerous — it looks like an answer.
MIN_EXPECTED_MOVE = 0.001


def validate_expected_move(value) -> float:
    """Unsigned decimal fraction, 0.001 ≤ x ≤ 1.5.

    Upper bound catches percent-vs-decimal entry errors: 20 (meaning 20%)
    must be rejected, not silently priced as a 2000% move.

    Lower bound catches the empty-field case. A UI that sends
    `Number("") === 0` used to produce a fully-rendered memo built on a ±0%
    forecast, with every structure degenerate — see MIN_EXPECTED_MOVE.
    """
    if value is None or value == "":
        raise ValueError(
            "expected_move is required — it is your forecast of the move's "
            "magnitude, and nothing in either system can derive it for you.")
    try:
        v = float(value)
    except (TypeError, ValueError):
        raise ValueError(f"expected_move must be a number, got {value!r}")
    if v != v:
        raise ValueError("expected_move must be a number, got NaN")
    if v < 0:
        raise ValueError(
            f"expected_move={v} is negative. It is the UNSIGNED magnitude you "
            f"expect (0.20 = ±20%); direction goes in expected_move_sign.")
    if v < MIN_EXPECTED_MOVE:
        raise ValueError(
            f"expected_move={v} is zero (or effectively zero). The memo prices "
            f"candidate structures at forward*(1 ± expected_move), so a zero "
            f"move collapses every strike onto ATM and makes the whole "
            f"structure comparison meaningless. Enter the magnitude you "
            f"actually believe in, as a decimal fraction (0.20 = ±20%).")
    if v > MAX_EXPECTED_MOVE:
        raise ValueError(
            f"expected_move={v} out of range — it is an unsigned DECIMAL "
            f"FRACTION (0.20 = ±20%), not a percent. Allowed: "
            f"{MIN_EXPECTED_MOVE} ≤ x ≤ {MAX_EXPECTED_MOVE}.")
    return v


# ── What still blocks a memo ─────────────────────────────────────────────────

def needs_user(row: dict) -> "list[str]":
    """The exact list of Class-C fields still blocking a memo, so the UI can
    render only those. Phase-A analysis (vol monitor, greeks, scenarios) needs
    none of them and is never gated on this list."""
    if not row:
        return list(_MEMO_REQUIRED)
    missing = [f for f in _MEMO_REQUIRED if row.get(f) is None]
    if row.get("last_error"):
        # No chain for this ticker even after the map → the one question the
        # system genuinely cannot answer: which underlier should Sarah use?
        missing.insert(0, "underlier")
    return missing


def has_vol_data(ticker: str, today_only: bool = False) -> bool:
    """Any vol_signals row for the ticker, or (today_only) one for today.

    today_only is what decides whether a re-pull needs to spend an
    options-chain fetch: re-pulling to pick up a leg captured in RCS should
    not re-download a chain already fetched this session.
    """
    try:
        conn = _connect_read()
    except Exception:
        return False
    try:
        sql = "SELECT 1 FROM vol_signals WHERE ticker = ?"
        args = [ticker.upper()]
        if today_only:
            sql += " AND date = ?"
            args.append(datetime.date.today().isoformat())
        row = conn.execute(sql + " LIMIT 1", args).fetchone()
    except Exception:
        return False
    finally:
        conn.close()
    return row is not None


def implied_move_reference(ticker: str, thesis_days: "int | None") -> "dict | None":
    """The market's implied move over the thesis horizon, from the stored ATM
    IV — shown BESIDE the `expected_move` field as reference, never as its
    default. Pre-filling the implied move would collapse the user's
    independent forecast onto the market's, which is the one comparison the
    memo exists to make.
    """
    if not thesis_days or thesis_days <= 0:
        return None
    try:
        conn = _connect_read()
    except Exception:
        return None
    try:
        row = conn.execute(
            "SELECT atm_iv_30d, date FROM vol_signals WHERE ticker = ? "
            "AND atm_iv_30d IS NOT NULL ORDER BY date DESC LIMIT 1",
            [ticker.upper()]).fetchone()
    except Exception:
        return None
    finally:
        conn.close()
    if not row or row[0] is None:
        return None
    import math
    iv = float(row[0]) / 100.0          # vol points → decimal
    move = iv * math.sqrt(thesis_days / 365.0)
    return {
        "implied_move": round(move, 4),
        "atm_iv_30d": round(float(row[0]), 2),
        "horizon_days": int(thesis_days),
        "as_of": str(row[1])[:10],
        "basis": "ATM IV 30d scaled to the thesis horizon (√t)",
        "note": "Reference only — do not adopt it as your forecast. The memo "
                "compares your belief against what is implied.",
    }


# ── Trigger (§5) ─────────────────────────────────────────────────────────────

def _regime_is_stale() -> bool:
    import json as _json
    from pathlib import Path
    from config import OUTPUTS_DIR
    p = Path(OUTPUTS_DIR) / "regime_state.json"
    if not p.exists():
        return True
    try:
        written = datetime.datetime.fromisoformat(
            _json.loads(p.read_text())["written_at"])
    except Exception:
        return True
    age_h = (datetime.datetime.now() - written).total_seconds() / 3600.0
    try:
        limit = float(get_params("sarah").regime_staleness_hours)
    except Exception:
        limit = 80.0
    return age_h > limit


def _skip_regime_check() -> bool:
    """Intake is screening, not execution. On a weekend with a stale regime
    the run is still worth having (the regime has not moved, it is just old),
    so the gate is relaxed — matching the batch-scan spec's behaviour. On a
    weekday a stale regime remains a hard failure: CLAUDE.md rule 4 stands."""
    return _regime_is_stale() and datetime.date.today().weekday() >= 5


def _submit_vol_job(tickers: "list[str]", ulids: "list[str]",
                    requested_by: str) -> "dict | None":
    from systems.orchestration.jobs import MANAGER
    if not tickers:
        return None
    return MANAGER.submit(
        "sarah_daily_vol",
        requested_by=requested_by,
        args={
            "tickers": sorted(set(tickers)),
            "source": "rcs_intake",
            "rcs_trade_ulids": sorted(set(ulids)),
            "skip_regime_check": _skip_regime_check(),
        },
    )


def intake_trade(rcs_trade_ulid: str, submit_job: bool = True,
                 requested_by: str = "api", macro_conn=None,
                 refresh_vol: "bool | None" = None,
                 skip_catalyst: bool = False) -> dict:
    """Steps 2–3 of §5 for one trade — the explicit "analyse this now" path,
    the **re-pull** path for a trade whose RCS record has since changed, and
    the hook an RCS "Send to Sarah" button or the LLM layer calls.

    It is safe to call repeatedly. Re-pulling re-reads RCS and refreshes every
    Class-A/B field you have not explicitly overridden (see upsert_from_rcs),
    which is how a leg or a defined max-loss captured *after* the first intake
    reaches Sarah.

    refresh_vol:
        None (default) — enqueue the vol pull only if the ticker has no
        signals row for today. Re-pulling to pick up a leg should not cost a
        redundant chain fetch.
        True  — always enqueue.  False — never enqueue (metadata only).

    Raises KeyError if the trade is not in RCS, ValueError if it is not an
    option trade (equities need no vol pull, by design).
    """
    from systems.risk import rcs_bridge

    trade = rcs_bridge.fetch_trade(rcs_trade_ulid)
    if trade is None:
        raise KeyError(f"no RCS trade {rcs_trade_ulid}")
    if str(trade.get("instrument_type")) != _OPTION_INSTRUMENT_TYPE:
        raise ValueError(
            f"trade {rcs_trade_ulid} is instrument_type="
            f"'{trade.get('instrument_type')}' — intake only runs the vol pull "
            "for option trades.")

    instrument = trade.get("instrument") or ""
    ticker = resolve_ticker(instrument)
    if not ticker:
        # Fail loudly rather than upserting a blank ticker and enqueuing a vol
        # job for "", which would fail deep inside the pipeline with no clue
        # as to why.
        raise ValueError(
            f"trade {rcs_trade_ulid} has no instrument recorded in RCS — "
            "nothing to analyse. Set the instrument on the trade first.")
    before = get_trade_inputs(rcs_trade_ulid)
    prefills = derive_prefills(trade, ticker, macro_conn=macro_conn,
                               skip_catalyst=skip_catalyst)
    row = upsert_from_rcs(rcs_trade_ulid, ticker, instrument, prefills)

    changed = {k: {"from": (before or {}).get(k), "to": row.get(k)}
               for k in ("ticker", *_RCS_DERIVED)
               if before and (before.get(k) != row.get(k))}

    if refresh_vol is None:
        # Ticker changed (underlier map edited) or no data for today → pull.
        refresh_vol = not has_vol_data(ticker, today_only=True)
    job = None
    if submit_job and refresh_vol:
        job = _submit_vol_job([ticker], [rcs_trade_ulid], requested_by)

    logger.info("intake: {} → {} (from {}), job {}", rcs_trade_ulid, ticker,
                instrument, (job or {}).get("id", "none"))
    return {
        "rcs_trade_ulid": rcs_trade_ulid,
        "ticker": ticker,
        "rcs_instrument": instrument.upper(),
        "underlier_mapped": ticker != instrument.upper(),
        "trade": {
            "name": trade.get("name"),
            "status": trade.get("status"),
            "instrument_type": trade.get("instrument_type"),
            "legs": trade.get("legs") or [],
            "strategy_type": (trade.get("options_meta") or {}).get("strategy_type"),
        },
        "job_id": (job or {}).get("id"),
        "prefilled": {k: row.get(k) for k in (
            "expected_move_sign", "thesis_days", "catalyst_type",
            "max_loss_budget")},
        "user_overrides": row.get("user_overrides") or [],
        "repull": before is not None,
        "changed": changed,
        "vol_refresh_queued": bool(job),
        "catalyst_note": prefills.get("catalyst_note"),
        "thesis_days_source": prefills.get("thesis_days_source"),
        "needs_user": needs_user(row),
        "has_vol_data": has_vol_data(ticker),
        "legs_captured": bool(trade.get("legs")),
        "note": (
            "Phase A (vol monitor, greeks, scenarios) is live as soon as the "
            "job succeeds — it needs no input. Only the memo waits, and only "
            "for expected_move."
            if trade.get("legs") else
            "No option legs captured in RCS yet: the ticker-level vol pull "
            "still runs, but the greeks/scenario surfaces have no position to "
            "price until the leg is recorded in RCS."),
    }


def resync_known_trades(requested_by: str = "sarah_intake_poll",
                        limit: int = 50) -> dict:
    """Re-derive Class-A/B for trades already intaken, from the live RCS row.

    **Why this exists.** RCS does not emit a usable event when option legs are
    captured: inserting a leg fires no trigger at all, and *editing* one fires
    an `entity_events` row whose `entity_id` is `leg:<leg_id>` — not the trade
    ULID — so the watermarked event poll can never see it. Since we do not
    modify RCS (ADR-003), the only way a leg captured after the first intake
    reaches Sarah is for us to re-read the trades we already track.

    Cheap by construction: pure SQLite reads against the journal, and the
    yfinance catalyst lookup is skipped whenever a catalyst is already known.
    No vol job is submitted unless the resolved ticker actually changed —
    re-syncing metadata must not trigger chain fetches.
    """
    from systems.risk import rcs_bridge

    out: dict = {"checked": 0, "updated": [], "errors": []}
    if not rcs_bridge.available():
        return out

    for row in list_trade_inputs(limit):
        ulid = row["rcs_trade_ulid"]
        try:
            trade = rcs_bridge.fetch_trade(ulid)
            if trade is None:
                continue
            # A closed or discarded trade is history; stop re-deriving it.
            if str(trade.get("status")) not in ("idea", "active"):
                continue
            out["checked"] += 1
            result = intake_trade(
                ulid, submit_job=False, requested_by=requested_by,
                refresh_vol=False,
                # Only pay for the network catalyst lookup if we still lack one.
                skip_catalyst=row.get("catalyst_type") is not None,
            )
            if result["changed"]:
                out["updated"].append({"rcs_trade_ulid": ulid,
                                       "ticker": result["ticker"],
                                       "changed": result["changed"]})
                logger.info("intake resync: {} ({}) — {}", ulid,
                            result["ticker"], result["changed"])
                # The underlier map changed under us: the new ticker has no
                # data, so this one genuinely needs a pull.
                if "ticker" in result["changed"] and not has_vol_data(
                        result["ticker"], today_only=True):
                    job = _submit_vol_job([result["ticker"]], [ulid],
                                          requested_by)
                    out.setdefault("jobs", []).append((job or {}).get("id"))
        except ValueError:
            continue                      # equity trade — nothing to sync
        except Exception as e:
            out["errors"].append(f"{ulid}: {e}")
    return out


def poll_activations(requested_by: str = "sarah_intake_poll") -> dict:
    """Steps 1–4 of §5 — the scheduled trigger.

    Reads new trade lifecycle events from RCS past the trading-side
    watermark, upserts intake rows for the option trades among them, and
    submits ONE coalesced `sarah_daily_vol` job with the union of tickers (an
    earnings week activates several trades at once; one job, not N).

    The watermark advances only over events actually examined, so a failure
    mid-cycle replays rather than silently dropping a trade.
    """
    from systems.risk import rcs_bridge

    out: dict = {"polled_at": datetime.datetime.now().isoformat(),
                 "events": 0, "intaken": [], "skipped": [], "errors": [],
                 "job_id": None}

    if not rcs_bridge.available():
        out["errors"].append("RCS database not available")
        return out

    fire_on_idea = bool(getattr(get_params("sarah"), "intake_fire_on_idea", True))
    watermark = get_watermark()
    try:
        events = rcs_bridge.fetch_trade_activations(
            watermark, include_ideas=fire_on_idea)
    except Exception as e:
        out["errors"].append(f"entity_events read failed: {e}")
        return out

    out["events"] = len(events)
    out["watermark_before"] = watermark

    # Always re-sync trades we already track, event or not — RCS cannot tell
    # us a leg was captured (see resync_known_trades).
    try:
        out["resync"] = resync_known_trades(requested_by)
    except Exception as e:
        out["errors"].append(f"resync failed: {e}")

    if not events:
        return out

    tickers: "list[str]" = []
    ulids: "list[str]" = []
    high_water = watermark
    seen: "set[str]" = set()

    for ev in events:
        tid = ev["entity_id"]
        # A trade created and then activated inside one poll window produces
        # two events for the same trade. Intake it once — the derivation is a
        # network lookup and the row is the same either way.
        if tid in seen:
            high_water = max(high_water, ev["occurred_at"])
            continue
        try:
            result = intake_trade(tid, submit_job=False,
                                  requested_by=requested_by)
        except ValueError as e:          # not an option trade — by design
            out["skipped"].append({"rcs_trade_ulid": tid, "reason": str(e)})
            seen.add(tid)
            high_water = max(high_water, ev["occurred_at"])
            continue
        except KeyError:
            # The event outlives the trade: entity_events is append-only, but
            # a discarded test row can be deleted outright. Nothing to analyse
            # and nothing wrong — skip it and move the watermark on.
            out["skipped"].append({"rcs_trade_ulid": tid,
                                   "reason": "trade no longer present in RCS"})
            seen.add(tid)
            high_water = max(high_water, ev["occurred_at"])
            continue
        except Exception as e:
            # Do NOT advance past an event we failed to process for an
            # unexpected reason — it must be retried next cycle.
            out["errors"].append(f"{tid}: {e}")
            logger.exception("intake poll: {} failed — {}", tid, e)
            break
        seen.add(tid)
        tickers.append(result["ticker"])
        ulids.append(tid)
        out["intaken"].append({"rcs_trade_ulid": tid,
                               "ticker": result["ticker"],
                               "event": ev["event_type"],
                               "new_status": ev["new_status"]})
        high_water = max(high_water, ev["occurred_at"])

    if tickers:
        job = _submit_vol_job(tickers, ulids, requested_by)
        out["job_id"] = (job or {}).get("id")
        out["tickers"] = sorted(set(tickers))

    if high_water > watermark:
        set_watermark(high_water)
        out["watermark_after"] = high_water

    logger.info("intake poll: {} event(s), {} intaken, {} skipped, job {}",
                out["events"], len(out["intaken"]), len(out["skipped"]),
                out["job_id"] or "none")
    return out
