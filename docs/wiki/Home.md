---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# Leopold Wiki

The reference manual **and operator's guide** for the six-component
systematic trading workstation. Everything here describes the system **as
it exists on disk right now** — v1.0 complete, all phases 0–6 verified
(2026-07-18; suites: platform 34/34, Jordan 21/21, Priya green). Living
status: [05-status/build-status.md](05-status/build-status.md).

The wiki is written for an operator who is **still developing trading
knowledge**: components explain their concepts inline, every significant
number has a "how to read it" entry, and workflows are step-by-step.
Screenshots of the live app are embedded throughout (`images/`;
regenerate with `node scripts/capture_wiki_screenshots.mjs`).

> **Working with an AI assistant?** Point it at
> [00-system/llm-assistant-guide.md](00-system/llm-assistant-guide.md) —
> it tells the model how to guide you through every workflow, which rules
> to hold, and where to ground every number.

---

## Learning paths

**Day one (60–90 min):**
[overview](00-system/overview.md) →
[glossary](00-system/glossary.md) (first two sections) →
[running & operating](04-workflows/running-and-operating.md) →
do the [morning routine](04-workflows/morning-routine.md) once with the app open.

**First trade analysis:** [pre-trade analysis](04-workflows/pre-trade-analysis.md)
end-to-end, with the [Sarah component page](01-components/sarah-vol-workspace.md)
open beside it for any number you don't recognize.

**First research idea:** [research validation](04-workflows/research-validation.md)
— expect (and welcome) a NO_GO.

**Understanding a scary day:** [regime context](04-workflows/regime-context.md).

## Task index

| If you want to… | Read |
|---|---|
| Understand what this system is and why | [00-system/overview.md](00-system/overview.md) |
| See how the pieces connect | [00-system/architecture.md](00-system/architecture.md) · [00-system/data-flow.md](00-system/data-flow.md) |
| Look up a term (VRP, DSR, regime, skew…) | [00-system/glossary.md](00-system/glossary.md) |
| Run the thing | [04-workflows/running-and-operating.md](04-workflows/running-and-operating.md) |
| Do the 7am read | [04-workflows/morning-routine.md](04-workflows/morning-routine.md) |
| Analyze a trade before entering it | [04-workflows/pre-trade-analysis.md](04-workflows/pre-trade-analysis.md) |
| Ask "what environment is this?" | [04-workflows/regime-context.md](04-workflows/regime-context.md) |
| Validate a strategy idea honestly | [04-workflows/research-validation.md](04-workflows/research-validation.md) |
| Size a validated strategy & watch risk | [04-workflows/risk-and-sizing.md](04-workflows/risk-and-sizing.md) |
| Run the Friday review | [04-workflows/weekly-operations.md](04-workflows/weekly-operations.md) |
| Change a threshold/weight/limit safely | [04-workflows/editing-parameters.md](04-workflows/editing-parameters.md) |
| Re-skin the app / add a visual theme | [04-workflows/creating-a-theme.md](04-workflows/creating-a-theme.md) |

## Components (the six personas)

Each page covers: what it does in plain language · the workspace (with
screenshot) · features per tool · key variables and how to read them ·
the computations · process flow · workflows served · limitations.

| Persona | Role | Doc |
|---|---|---|
| **Marcus** | Macro regime classification — the context everything runs in | [01-components/marcus-macro-regime.md](01-components/marcus-macro-regime.md) |
| **Sarah** | Vol surface + the five pre-trade tools | [01-components/sarah-vol-workspace.md](01-components/sarah-vol-workspace.md) |
| **Priya** | Research validation — backtests that are hard to fool | [01-components/priya-research-engine.md](01-components/priya-research-engine.md) |
| **Jordan** | Risk — book, limits, stress, verdict intake, sizing | [01-components/jordan-risk-layer.md](01-components/jordan-risk-layer.md) |
| **Alex** | Orchestration — scheduler v2, alerts, weekly review | [01-components/alex-orchestration.md](01-components/alex-orchestration.md) |
| **Kai** | Execution — **deferred to v1.1** (manual execution in v1.0) | [05-status/build-status.md](05-status/build-status.md) |

Supporting: [data feeds](01-components/data-feeds.md) ·
[RCS journal + bridge](01-components/rcs-journal.md)

## Platform

- [Parameter registry](02-platform/parameter-registry.md) — versioned, GUI-editable source of truth for every tunable
- [API reference](02-platform/api-reference.md) — every FastAPI endpoint on :8100
- [Frontend](02-platform/frontend.md) — the React workstation pages
- [Jobs & scheduling](02-platform/jobs-and-scheduling.md) — job system, scheduler v2, retries, alerts
- [Databases](02-platform/databases.md) — full table schemas (macro.db, trading.db)

## Contracts & schemas

- [Output contracts](03-contracts/output-contracts.md) — the locked JSON files in `data/outputs/`
- [Parameter schemas](03-contracts/parameter-schemas.md) — every registry field, default, bound, and meaning

## Knowledge Library

- [Ashurbanipal integration](06-knowledge/ashurbanipal-integration.md) —
  how trading artifacts (memos, weekly reviews, the event library, this
  wiki) flow into the personal knowledge library, and how grounding packs
  flow back. Includes the draft `trading` source-adapter mapping.

## Deeper reference

The audit docs (`docs/audit/01–05`) are the per-layer capability maps +
**output literacy** guides — the most detailed "how to read this number"
material in the repo. The wiki links into them throughout.

## Conventions used in this wiki

- **Status tags**: ✅ verified · 🟢 built, smoke-tested · 🟡 partial · ⬜ planned.
- File references are repo-relative. "Registry" always means
  `systems/params`. "Leopold" is the product name; "the workstation" means
  FastAPI :8100 + React :5173.
- Every page carries cross-surface frontmatter
  (`domain/stage/project/persona/status`) per the Knowledge Library
  feature brief, so the library's filesystem adapter can catalog these
  pages with persona and project as query axes.
