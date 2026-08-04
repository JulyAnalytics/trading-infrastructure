---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# RCS — the Journal (Research Capture System) & the Bridge

**Status:** RCS app ✅ live (separate repo) · bridge ✅ **verified live against the real DB** (2026-07-17) · trade→Sarah intake seam ✅ live (2026-08-03)
**App:** `~/Nextcloud/Trading/research-capture-system` — FastAPI + Jinja/HTMX/Alpine on **:8099**, SQLite at `research/data/research.db` (30 tables)
**Bridge:** `systems/risk/rcs_bridge.py` (this repo, read-only)

> **DB location gotcha.** The *running* RCS server reads `db_path` from
> `research/.env`, which points outside the repo at
> `~/.local/state/rcs/research.db` (moved there so WAL churn stops generating
> Nextcloud conflict copies). `config.RCS_DB_PATH` follows that `.env` rather
> than the in-repo default, so the bridge reads the DB the live app is
> actually writing. If you ever debug "my new RCS entity isn't reaching the
> workstation", check which file you inspected.

## What the RCS is

The Intelligence → Decision → Learning layers of the desk, already built as
its own application:

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

> **Learning anchor.** The journal is not paperwork — it is the only place
> the *reasoning* behind a trade survives contact with the outcome. The
> whole workstation is built so that analysis (memos, verdicts, regime
> context) can be *cited* from journal entries, and so risk is computed over
> what you actually journaled, not what you remember.

## The division of labor

| Concern | Lives in |
|---|---|
| Capturing narratives, theses, setups, trades, reviews | **RCS** (:8099) |
| Market context (regime, vol state), pre-trade math, research validation | **workstation** (this repo) |
| Positions risk (greeks, limits, stress) over journaled trades | **workstation**, reading RCS |
| Trade execution | **you**, at the broker (Kai is v1.1) |

## The bridge contract (ADR-003, CLAUDE.md Rule 6)

- This repo opens research.db with SQLite `mode=ro` — **writes are
  impossible at the driver level**, verified both by the synthetic suite and
  by a live write-attempt against the real DB (rejected by the driver,
  2026-07-17).
- Consumed tables: `trade`, `trade_entries`, `trade_exits`,
  `trade_option_legs`, `trade_options_meta` (→ Jordan's book);
  `review`, `observation`, `thesis` counts (→ the weekly review);
  `entity_events` + `thesis.worst_case_dollar` (→ the Sarah trade-intake
  trigger, below).
- Mapping: an active option trade contributes one Jordan position per
  **open leg**; an active equity trade contributes its net size
  (entries − exits).
- Deep links: Jordan's book rows link to `http://localhost:8099/trade/<id>`.
- **Schema-contract note** (found in the live smoke): `review` has no
  `created_at` column — completed reviews are counted on `closed_at`
  (stamped at position close). If a bridge count ever returns `null`
  instead of a number, that is schema drift between the two repos: fix the
  bridge, don't ignore it.
- No RCS code changes in v1.0. A future, optional RCS-side "market context"
  panel (pulling `/api/context/regime` from :8100) is sketched in the ADR.

## Trade → Sarah: the first automated seam (ADR-005)

Until now *you* were the switchboard: frame the trade in RCS, open Sarah,
retype the ticker and position, run. The intake seam removes that step
without RCS knowing it exists.

```
RCS: trade idea→active (or created as an idea)
  └─ entity_events row written by an RCS trigger
        │  read-only, mode=ro — no RCS change, no callback, no button
        ▼
Trading: sarah_intake_poll (scheduler v2, every sarah.intake_poll_minutes)
  → skip anything that isn't an option trade
  → ticker ← sarah.underlier_map.get(instrument, instrument)
  → upsert sarah_trade_inputs: legs, strategy, catalyst, budget — all
    pre-filled; expected_move deliberately left NULL
  → submit ONE coalesced sarah_daily_vol batch for the union of tickers
  → advance sarah_intake_watermark (trading-side: RCS's own
    export_watermarks does not cover `trade`, and ADR-003 forbids writing it)
```

The design rule it preserves: the system pre-fills every cost and
probability, but **never** `expected_move` — magnitude belief stays yours.
Full detail, including the two-phase model and the underlier map, in
[Sarah — RCS trade intake](sarah-vol-workspace.md#rcs-trade-intake).

**Schema-contract note — leg capture emits no usable event.** Inserting a
`trade_option_legs` row fires no trigger at all; *editing* one fires
`audit_trade_option_legs_edit`, which writes `entity_id = 'leg:' || NEW.id`
rather than the trade ULID. So `entity_events` cannot tell the workstation
that a trade just gained its legs — which matters, because legs are exactly
what Jordan's book and Sarah's greeks/scenario surfaces need. Rather than
change RCS (ADR-003), the intake poll re-reads the trades it already tracks
each cycle, and both intake surfaces carry an explicit **Re-pull**. If RCS
ever grows a trade-scoped `updated` event for leg changes, the poll can drop
that re-read.

Why a poll rather than a push: zero coupling. An RCS "Send to Sarah" button
calling `POST /api/sarah/intake` would be compatible and can be added later
without changing anything here.

## Cross-linking convention (the provenance thread)

Pre-trade memos persist with stable IDs — `PTM-YYYYMMDD-TICKER-NNN` — so an
RCS setup or trade note can cite *exactly* the memo that justified it. This
mirrors the RCS's own `canvas_source_documents` pattern (record the source
at the moment of use), and is the same convention the
[Knowledge Library integration](../06-knowledge/ashurbanipal-integration.md)
builds on: explicit reference beats semantic inference for provenance.

## The loop this closes

Analyze (workstation: memo `PTM-…`) → journal the decision citing it (RCS) →
execute (broker) → journal the fill (RCS) → the position appears in
Jordan → limits/stress/daily check include it → the review (RCS) records
the outcome → Friday's weekly review aggregates both sides.

**Current state honestly (2026-08-03):** the journal now has real trades, and
the trade→Sarah half of the loop is verified end-to-end against one of them
(the AAOI earnings trade: activation read → AAOI vol pull → memo
`PTM-20260803-AAOI-001` persisted with the trade ULID). The trade→**book**
half still waits on option legs being captured in RCS — until a
`trade_option_legs` row exists, an option trade reaches the bridge with no
legs, so Jordan has nothing to price and Sarah's greeks/scenario surfaces
stay empty even though the ticker-level vol data is there. **RCS leg capture
is the upstream gate on both.**
