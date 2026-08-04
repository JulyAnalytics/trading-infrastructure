---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# System Overview

> **New here?** Read this page, then the
> [glossary](glossary.md), then follow the
> [morning routine](../04-workflows/morning-routine.md) once with the app
> open. If you're working with an AI assistant, point it at the
> [LLM assistant guide](llm-assistant-guide.md).

## What this is

A personal systematic trading system organized as **six analyst personas**,
each a software component with a defined job, explicit inputs/outputs, and a
locked contract with the components downstream of it. The metaphor comes from
a boutique fund's desk: a macro strategist (Marcus), a vol/derivatives head
(Sarah), a quant researcher (Priya), a risk manager (Jordan), an execution
specialist (Kai, deferred), and a chief-of-staff (Alex). The operator — you —
are the PM: the system prepares decisions; the human makes them.

## The core idea

Trading decisions are made in a **context stack**:

1. **Regime first.** Marcus classifies the macro environment daily
   (`RISK_ON_LOW_VOL` … `CRISIS`) from FRED/CFTC data. Every downstream
   component must read the regime before doing anything, and must refuse to
   run on stale regime data (CLAUDE.md Rule 4).
2. **Vol state second.** Sarah measures what the options market is pricing —
   IV levels vs history, term structure shape, skew, and the vol-risk-premium
   — per ticker, daily.
3. **Validated edges only.** Priya's research pipeline exists to make it hard
   to fool yourself: pre-registered hypotheses, purged/combinatorial
   cross-validation, deflated Sharpe ratios, overfitting diagnostics, and 13
   process gates before a strategy earns a `GO`.
4. **Risk before size.** Jordan converts a GO verdict plus the current regime
   into position sizes, and monitors the live book (imported from the trade
   journal) against limits.
5. **Everything journaled.** Trades, theses, setups, and reviews live in the
   sibling **Research Capture System** app; this repo reads it (never writes)
   to close the loop between analysis and outcomes.

## v0.5 → v1.0 in one sentence each

- **v0.5** answered *"what is the market doing, and is this strategy real?"*
  — a headless pipeline of Python modules writing JSON files and DB rows.
- **v1.0** turns that pipeline into **a desk you operate**: one React
  workstation over a FastAPI service layer, with every tunable in a
  versioned, GUI-editable **parameter registry**, every run stamped with the
  parameter hashes it used, and the risk/journal loop closed.

Three deliberate v1.0 principles:

1. **Control surfaces, not constants** — changing an assumption is a
   first-class, audited act ([parameter registry](../02-platform/parameter-registry.md)).
2. **Human-in-the-loop at explicit points** — thesis, sizing, and execution
   are yours; the system computes, warns, and records.
3. **Honest data lineage** — yfinance data is 15–20 min delayed and every
   affected output carries a `data_warning`; live-capital deployment is
   explicitly gated behind historical options data validation
   ([ADR-004](../../design_decisions/ADR-004-scope-deferrals.md)).

## What it is not (yet)

- Not an execution system: Kai (IBKR connectivity, TCA) is v1.1; in v1.0 you
  execute manually at the broker and journal the fill in the RCS.
- Not a live-data system: research/paper quality data only.
- Not fully autonomous: the scheduler runs data pipelines, but every trading
  decision has a human control point by design.

## Directory map (top level)

```
trading-infrastructure/
├── config.py            infrastructure literals + registry facade
├── scheduler.py         RETIRED (see systems/orchestration/scheduler_v2.py)
├── systems/
│   ├── params/          parameter registry (v1.0 core)
│   ├── api/             FastAPI service layer :8100
│   ├── orchestration/   job runner + scheduler v2 + alerts
│   ├── signals/         Marcus: classifier + 1.0 analytics
│   ├── sarah/           vol pipeline, greeks, scenarios, memo builder, regime library
│   ├── backtest/        Priya: 15-module research engine
│   ├── risk/            Jordan: book, limits, stress, intake, RCS bridge
│   ├── data_feeds/      FRED / CFTC / yfinance / CBOE ingestion
│   ├── dashboard/       RETIRED Dash app (figure builders still imported by reports)
│   ├── reports/         PDF snapshot + weekly review generators
│   └── utils/           db.py (connections), pricing.py (Black-Scholes)
├── frontend/            React workstation (Vite + TS) :5173
├── research/signals/    vol surface + signal math used by Sarah
├── scripts/             verify suites, golden master, backfills, migrations
├── reports/weekly/      generated weekly reviews (md + pdf)
├── data/                processed DBs, outputs (contracts), events, snapshots
└── docs/                architecture, audits, ADRs, this wiki
```

Related but separate: `../research-capture-system/` — the journal app
([rcs-journal.md](../01-components/rcs-journal.md)).
