# RCS — the Journal (Research Capture System) & the Bridge

**Status:** RCS app ✅ live (separate repo) · bridge 🟡 unverified
**App:** `~/Nextcloud/Trading/research-capture-system` — FastAPI + Jinja/HTMX/Alpine on **:8099**, SQLite at `research/data/research.db` (30 tables)
**Bridge:** `systems/risk/rcs_bridge.py` (this repo, read-only)

## What the RCS is

The Intelligence → Decision → Learning layers of the desk, already built and
in daily use as its own application:

```
canvas (macro narratives, cross-currents, invalidation conditions)
   └─ thesis (state machine: building→ready→active→invalidated/archived;
              win condition, macro+technical kill conditions, decision points)
        └─ setup (structured technical/vol/flow analysis, images)
             └─ trade (idea→active→closed/discarded; append-only entries/exits;
                       option legs + greeks/IV meta; frozen entry/exit rules)
                  └─ review (phase 1 → zone 3 → phase 2, mistake taxonomy)
plus: observations (watch/take/pass with pass-reasons), insights, actions,
      exposure board, protocols 1–4 (process-discipline banners)
```

It has its own CLAUDE.md, hourly launchd backups, a destructive-command
guard hook, and append-only triggers. Its **analytics routes are unbuilt** —
which is exactly the hole this workstation fills from the outside.

## The division of labor

| Concern | Lives in |
|---|---|
| Capturing narratives, theses, setups, trades, reviews | **RCS** (:8099) |
| Market context (regime, vol state), pre-trade math, research validation | **workstation** (this repo) |
| Positions risk (greeks, limits, stress) over journaled trades | **workstation**, reading RCS |
| Trade execution | **you**, at the broker (Kai is v1.1) |

## The bridge contract (ADR-003, CLAUDE.md Rule 6)

- This repo opens research.db with SQLite `mode=ro` — writes are impossible
  at the driver level, verified by a test in `scripts/verify_jordan.py`.
- Consumed tables: `trade`, `trade_entries`, `trade_exits`,
  `trade_option_legs`, `trade_options_meta` (→ Jordan's book);
  `review`, `observation`, `thesis` counts (→ weekly activity for Alex).
- Mapping: an active option trade contributes one Jordan position per
  **open leg**; an active equity trade contributes its net size
  (entries − exits).
- Deep links: Jordan's book rows link to `http://localhost:8099/trade/<id>`.
- No RCS code changes in v1.0. A future, optional RCS-side "market context"
  panel (pulling `/api/context/regime` from :8100) is sketched in the ADR.

## The loop this closes

Analyze (workstation) → journal the decision (RCS) → execute (broker) →
journal the fill (RCS) → the position appears in Jordan → limits/stress
include it → the review (RCS) records the outcome → the weekly review
(Phase 6) aggregates both sides.
