# Architecture

## Topology (v1.0)

```
                        ┌──────────────────────────────────┐
                        │  Browser — React workstation     │
                        │  vite dev :5173 (proxies /api)   │
                        └────────────────┬─────────────────┘
                                         │ REST + polling
                        ┌────────────────▼─────────────────┐
                        │  FastAPI service layer  :8100    │
                        │  systems/api                     │
                        │  • read-only DuckDB conns (503   │
                        │    on writer lock, never crash)  │
                        │  • params CRUD                   │
                        │  • JobManager (1 worker thread)  │
                        └───┬──────────────┬───────────────┘
              spawns 1-at-a-time          reads
                        ┌───▼───────────┐  │
                        │ job subprocess│  │
                        │ run_job <name>│  │   ┌───────────────────────────┐
                        │ = ONLY writer │  │   │ parameter registry        │
                        └───┬───────────┘  │   │ systems/params →          │
                            │ writes       │   │ trading.db:               │
        ┌───────────────────▼──────────────▼─┐ │  parameter_versions       │
        │ ENGINES (v0.5 refactored)           │◄┘ every run stamps hashes  │
        │ signals/ sarah/ backtest/ risk/     │
        │ data_feeds/ reports/                │
        └───┬────────────┬───────────┬────────┘
            │            │           │
   ┌────────▼───┐  ┌─────▼─────┐  ┌──▼──────────────┐   ┌──────────────────┐
   │ macro.db   │  │trading.db │  │ data/outputs/*.json│ │ RCS SQLite (ro)  │
   │ (Marcus)   │  │(Sarah+    │  │ locked contracts │  │ ../research-      │
   │            │  │ Priya+v1) │  │                  │  │ capture-system    │
   └────────────┘  └───────────┘  └──────────────────┘  └───────▲──────────┘
                                                                │ mode=ro
                                                    systems/risk/rcs_bridge
```

Legacy (being retired): Dash dashboard at :8050
(`systems/dashboard/macro_dashboard.py`) — display-only view of Marcus;
superseded by the workstation's Marcus page.

## The five integration mechanisms

1. **Output contracts** — JSON files in `data/outputs/` with locked schemas
   ([output-contracts.md](../03-contracts/output-contracts.md)). The regime
   file is the master gate: downstream components hard-fail if it is missing
   or stale.
2. **Shared DuckDB tables** — `macro.db` (Marcus's series + regime history),
   `trading.db` (Sarah's signals, Priya's hypothesis registry, and the v1.0
   platform tables). Full schemas: [databases.md](../02-platform/databases.md).
3. **The parameter registry** — one versioned store consulted by every
   engine; the *only* legitimate source of tunables
   ([parameter-registry.md](../02-platform/parameter-registry.md)).
4. **The API layer** — the single programmatic surface the GUI (and any
   future automation) talks to ([api-reference.md](../02-platform/api-reference.md)).
5. **The RCS bridge** — read-only SQLite adapter that turns journaled trades
   into Jordan's positions book ([rcs-journal.md](../01-components/rcs-journal.md)).

## Concurrency model (DuckDB single-writer)

DuckDB allows one writer **or** many readers per database file. The v1.0
rules that keep this safe:

- All pipeline **writes** happen inside job subprocesses, serialized by the
  single JobManager worker — at most one writer exists at any moment.
- API **reads** open short-lived `read_only=True` connections
  (`systems/api/deps.py`); if a writer holds the lock they retry briefly and
  then return HTTP **503** with a "pipeline is writing" message.
- The registry reads fall back to **code defaults with a loud warning** if
  the DB is locked — a busy database can never crash a pipeline (but the
  warning tells you edits weren't applied to that run).
- The old Dash app broke this model by classifying (and writing) on every
  page refresh; the workstation's GET endpoints never write.

## Process & import model

`from config import X` binds X at the importing module's import time. The
registry facade therefore guarantees *fresh-process* freshness, not
*live-process* freshness — which is why jobs run as **fresh subprocesses**
(each run imports the latest active parameters) and why the refactored
engines (`regime_classifier`, `scenario_engine`) call `get_params()` at
call-time instead of import-time. New code must do the same
(CLAUDE.md Rule 1).

## Ports & processes

| Port | What | Started by |
|---|---|---|
| 8100 | FastAPI service layer | `python -m systems.api.main` / uvicorn |
| 5173 | React dev server | `npm run dev` in `frontend/` |
| 8050 | Legacy Dash dashboard | `python systems/dashboard/macro_dashboard.py` (retiring) |
| 8099 | RCS journal app (separate repo) | `../research-capture-system/start.sh` |

## Design lineage

The architecture implements, in order: the zero-dollar build sequence
(Phases 0–7), the Marcus improvements doc (priorities 1–5 in v1.0), the
Sarah tiered upgrade path (free Tier-1 items in v1.0), and the four ADRs in
[docs/design_decisions/](../../design_decisions/ADR-001-gui-stack-fastapi-react.md).
