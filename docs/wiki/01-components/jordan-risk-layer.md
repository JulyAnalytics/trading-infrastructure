# Jordan — Risk Layer

**Status:** 🟡 unverified (built in v1.0; offline checks in `scripts/verify_jordan.py`)
**Code:** `systems/risk/` · **GUI:** workstation *Jordan* page · **Params:** registry component `jordan`

## Job

Stand between analysis and capital. Jordan (a) knows the real book, (b)
prices its aggregate risk, (c) enforces limits, (d) stress-tests it against
the historical shock library, and (e) is the *only* path by which a Priya
verdict becomes a position size — after re-checking that the verdict is
still fresh and regime-compatible.

## Modules

### `rcs_bridge.py` — the journal is the book
Opens the Research Capture System SQLite with `mode=ro` (writes are
impossible at the driver level — CLAUDE.md Rule 6 / ADR-003). Pulls
`status='active'` trades with their entries/exits (net open size), option
legs, and options meta; also weekly activity counts for Alex. Deep links
back into the RCS UI (`:8099`).

### `book.py` — positions book
- RCS option trades → one position per **open leg** (direction/type/strike/
  expiry/contracts); RCS equity trades → net-size share positions.
- Manual positions (anything unjournaled) live in
  `trading.db:jordan_positions` with add/close endpoints.
- `analyze_book()` prices everything live (yfinance, delayed): options
  through Sarah's `GreeksTool` (7 greeks, position-scaled), equities as
  delta-only. Produces per-position `delta_dollars`, `vega_dollars`,
  `notional`, plus portfolio **net greeks**, vanna/charm/vomma concentration
  flags, net delta/vega dollars and gross notional. Per-position pricing
  failures land in an `errors` list — one dead ticker never blinds the board.

### `limits.py` — limits are parameters
Checks against `JordanParams`: |net delta $|/NAV ≤ 20%, |net vega $|/NAV
≤ 15%, per-position notional/NAV ≤ 5% (defaults; all GUI-editable and
versioned). Drawdown alert/halt (8%/15%) is declared but explicitly
**not evaluated** until a NAV history exists (Phase 6). Returns structured
checks + a flat `breaches` list that drives the red banner.

### `stress.py` — the book under the shock library
Runs every position through Sarah's scenario engine for each named stress
scenario (the user-editable registry library): flat and skew-amplified P&L,
summed per scenario with per-position contributions; equities linear in the
spot shock. Reports the worst case. Endpoint approximation — same caveats
as Stage 3.

### `verdict_intake.py` — the Priya handoff, done defensively
Checklist over `research_verdict.json` + `regime_state.json`:
verdict exists → fresh (≤ `verdict_max_age_hours`, default 168h) → `GO` →
`viable_after_haircut` → **regime-compatible** (positive regime-conditional
Sharpe for the *current* regime; unknown regime = not actionable). Only if
all pass is the verdict "actionable". This closes audit gap **G4-7** (a GO
approved in RISK_ON silently rotting through a regime change).

`suggest_size(entry, stop)` implements the build-sequence formula —
units = (NAV × risk%) ÷ |entry − stop| — capped by the single-position
limit. NAV, default risk%, and every limit are registry fields.

## The v1.0 execution loop (Kai deferred)

```
verdict intake ✔ → sizing suggestion → YOU execute at the broker
      → journal the fill in the RCS → it appears in Jordan's book
      → limits & stress now include it
```

## Inputs · Outputs · API

| | |
|---|---|
| Reads | RCS SQLite (ro) · `trading.db:jordan_positions` · `research_verdict.json` · `regime_state.json` · yfinance (pricing) |
| Writes | `trading.db:jordan_positions` only |
| API | `/api/jordan/*` ([reference](../02-platform/api-reference.md#jordan)) |
| Verify | `python scripts/verify_jordan.py` (offline: sizing/limits/intake math, bridge read-only guarantee, book assembly) |

## Remaining for Phase 5 sign-off

`docs/audit/05_jordan_risk_layer.md` (audit-as-built), live smoke against
the real RCS DB, and the drawdown check once NAV history exists.
