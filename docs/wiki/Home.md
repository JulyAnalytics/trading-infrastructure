# Trading Infrastructure Wiki

The reference manual for the six-component systematic trading workstation.
Everything here describes the system **as it exists on disk right now**
(v1.0 build, 2026-07-06) — including which parts are still unverified or
unbuilt. For the aspirational roadmap see
[../architecture/v1_architecture.md](../architecture/v1_architecture.md);
for build state see [05-status/build-status.md](05-status/build-status.md).

> ✅ **Phase 0 gauntlet + Jordan suite: green (2026-07-06).** Golden master
> identical, all legacy config names resolve, registry/Jordan test suites
> pass, API boots and serves real data, frontend builds clean. See
> [05-status/verification.md](05-status/verification.md) for exactly what
> that does and doesn't cover — some pieces (Sarah data completions, Priya
> workbench, an interactive browser pass) are still ⬜/🟡.

---

## Start here

| If you want to… | Read |
|---|---|
| Understand what this system is and why | [00-system/overview.md](00-system/overview.md) |
| See how the pieces connect | [00-system/architecture.md](00-system/architecture.md) · [00-system/data-flow.md](00-system/data-flow.md) |
| Look up a term (VRP, DSR, regime, skew…) | [00-system/glossary.md](00-system/glossary.md) |
| Run the thing | [04-workflows/running-and-operating.md](04-workflows/running-and-operating.md) |
| Do the 7am read | [04-workflows/morning-routine.md](04-workflows/morning-routine.md) |
| Change a threshold/weight/limit safely | [04-workflows/editing-parameters.md](04-workflows/editing-parameters.md) |
| Analyze a trade before entering it | [04-workflows/pre-trade-analysis.md](04-workflows/pre-trade-analysis.md) |
| Validate a strategy idea honestly | [04-workflows/research-validation.md](04-workflows/research-validation.md) |
| Size a validated strategy & monitor risk | [04-workflows/risk-and-sizing.md](04-workflows/risk-and-sizing.md) |

## Components (the six personas)

| Persona | Role | Doc |
|---|---|---|
| **Marcus** | Macro regime classification — the context everything runs in | [01-components/marcus-macro-regime.md](01-components/marcus-macro-regime.md) |
| **Sarah** | Vol surface, greeks, scenarios, pre-trade intelligence | [01-components/sarah-vol-workspace.md](01-components/sarah-vol-workspace.md) |
| **Priya** | Research validation — backtests that are hard to fool | [01-components/priya-research-engine.md](01-components/priya-research-engine.md) |
| **Jordan** | Risk — book, limits, stress, verdict intake, sizing | [01-components/jordan-risk-layer.md](01-components/jordan-risk-layer.md) |
| **Alex** | Orchestration — jobs, schedule, (planned) weekly review | [01-components/alex-orchestration.md](01-components/alex-orchestration.md) |
| **Kai** | Execution — **deferred to v1.1** (manual execution in v1.0) | [05-status/build-status.md](05-status/build-status.md) |

Supporting: [data feeds](01-components/data-feeds.md) ·
[RCS journal + bridge](01-components/rcs-journal.md)

## Platform

- [Parameter registry](02-platform/parameter-registry.md) — versioned, GUI-editable source of truth for every tunable
- [API reference](02-platform/api-reference.md) — every FastAPI endpoint on :8100
- [Frontend](02-platform/frontend.md) — the React workstation pages
- [Jobs & scheduling](02-platform/jobs-and-scheduling.md) — how pipelines run
- [Databases](02-platform/databases.md) — full table schemas (macro.db, trading.db)

## Contracts & schemas

- [Output contracts](03-contracts/output-contracts.md) — the locked JSON files in `data/outputs/`
- [Parameter schemas](03-contracts/parameter-schemas.md) — every registry field, default, bound, and meaning

## Conventions used in this wiki

- **Status tags**: `✅ live` (ran in production pre-v1.0), `🟡 unverified`
  (v1.0 code written this build, gauntlet pending), `⬜ planned` (documented,
  not built).
- File references are repo-relative. "Registry" always means
  `systems/params`. "The workstation" means FastAPI :8100 + React :5173.
