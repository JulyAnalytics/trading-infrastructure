# ADR-003 — Journal = existing RCS, integrated read-only (not rebuilt)

**Date:** 2026-07-06 · **Status:** accepted (user decision)

## Context
The docs describe a Sam/Trade-Journal layer (trends → theses → setups →
trades, learnings/mistakes). That system already exists and is live: the
Research Capture System at `../research-capture-system` (FastAPI + HTMX,
:8099, SQLite `research/data/research.db`, 30 tables, state machines,
protocols 1–4, backups). Its analytics routes are unbuilt.

## Decision
Integrate, never rebuild, never write:
- trading-infrastructure reads the RCS SQLite READ-ONLY (Phase 5): active
  trades + option legs/meta become Jordan's positions book; weekly activity
  stats feed Alex's review.
- Deep links between the two local UIs; pretrade memos get stable IDs/URLs
  an RCS setup or trade note can reference.
- RCS-side changes (e.g. a market-context panel pulling regime/vol from this
  API) are proposed separately, later — no RCS code changes in v1.0.
- RCS backup/guard hooks remain authoritative for that database.

## Consequences
- Jordan gets a real book without new capture UI.
- The infra workstation may host analytics over RCS trade data (the RCS
  "analytics: not started" hole) without duplicating storage.
