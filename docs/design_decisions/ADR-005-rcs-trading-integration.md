# ADR-005 — RCS ↔ trading integration: typed entity→capability seams

**Date:** 2026-07-29 · **Status:** accepted (user decision)
**Refines:** [ADR-003](ADR-003-rcs-bridge.md) (the read-only rule is unchanged;
this ADR defines what the integration *is*, on top of that rule).
**Reference spec:** [../wiki/06-knowledge/rcs-trading-contracts.md](../wiki/06-knowledge/rcs-trading-contracts.md)

## Context

ADR-003 settled the *mechanical* question: trading reads the RCS journal
read-only; never writes it; never rebuilds it. It did not settle the
*semantic* question: how do the entities in RCS (canvas, thesis, setup,
observation, trade, review, action, insight) relate to the trading system's
capabilities (Marcus regime, Sarah vol, Priya research, Jordan risk, Alex
ops), and what should flow across that seam?

In practice the seam is too loose to be useful. The bridge (`systems/risk/
rcs_bridge.py`) reads the `thesis` table only as a `COUNT(*)` for the weekly
activity count — it never reads thesis narrative, instrument, win condition,
kill conditions, or status. The link between a Priya hypothesis and its
originating RCS thesis exists only as free text in `rationale`. The link
between a Sarah memo (`PTM-…`) and the RCS note that should cite it exists
only as a copy-paste the user performs by hand. The documented loop — frame
thesis in RCS → open trading app → build memo → copy the PTM id → paste into
RCS → execute → journal the fill → it reappears in Jordan — is correct, but
the user is the switchboard.

The instinct this ADR responds to is "these two should be seamlessly
integrated, maybe even merged." This ADR accepts the instinct and rejects
the merger. The reconciliation is a *richer seam*, not a single app.

## Decision

**Each RCS entity has a typed relationship to one trading-system capability.
The relationships are codified as deterministic contracts (this ADR + the
reference spec). A later LLM assistant mediates them; it does not define
them.**

The entity → capability map (full detail in the reference spec §1):

| RCS entity | Semantic role | Trading counterpart | Integration type |
|---|---|---|---|
| **canvas** | persistent macro belief | **Marcus** | validation — does the market still agree with the belief? |
| **thesis** | directional + structural bet on an instrument | **Sarah + Priya** | analysis — structure + validate |
| **setup** | frozen evidence snapshot | **Sarah** | evidence — confirm or contradict |
| **observation** | cheap "I noticed something" | **Sarah** | triage — worth promoting? |
| **trade** | the commitment | **Jordan** | risk — *(already built via the bridge)* |
| **review** | post-close learning | **Priya + canvas** | feedback — *(spec'd here, built later)* |
| **action** | a task with a due date | **Alex + calendar** | scheduling — nudge at the right time |
| **insight** | polymorphic sticky note | **LLM narration** | memory — where synthesis lands |

### Why typed seams, not a merger

1. **Different reliability models.** The trading system is a quant engine
   with single-writer DuckDB discipline, parameter versioning, and
   reproducibility hashes stamped on every run. RCS is a freely-written
   SQLite journal (WAL, concurrent). Coupling them couples the reliability
   models — a journal write should not be able to block a quant job, and a
   quant job should not hold a lock the journal needs.
2. **Different stances — and blurring them is dangerous.** The trading
   system is *descriptive and gated* (Sarah never recommends direction;
   Priya kills bad backtests; Jordan enforces limits). RCS is *prescriptive
   and personal* (your thesis, your decision, your recorded mistake). If the
   engine could write theses, the boundary between "what the market says"
   and "what I decided" dissolves — which is exactly the line the
   "never recommend a direction" rule exists to protect.
3. **ADR-003's read-only rule protects the audit trail.** "Trading never
   writes RCS" keeps the journal an untamperable record of *the user's*
   decisions, not a system-modified artifact. The moment the engine can edit
   theses, "what did the human actually decide vs. what did the machine
   populate" becomes ambiguous — fatal to the review/mistake-learning loop
   that is the whole point of RCS.
4. **The two data shapes are correctly different.** DuckDB (analytical,
   columnar) for time-series and regime history; SQLite (transactional) for
   the entity graph. Both are the right tool.

### What this implies about the LLM layer

The LLM assistant (when added) is **not a third feature sitting beside two
apps** — it is the *integration layer* between them, and arguably the only
layer that can make the seam seamless without merging the apps. It can read
both sides (`:8100` and `:8099`), translate between the two domains (a
thesis narrative → Sarah memo inputs → a Priya hypothesis rationale is a
language/reasoning task, not a deterministic map), and hold the discipline
(confirm before any write, refuse to bypass gates). But it must operate over
the deterministic contracts in the reference spec, not improvise the
relationships. **The deterministic substrate comes first; the dialogical
layer sits on top.** That sequencing is the point of this ADR.

## Consequences

**Enables:**
- A future LLM assistant that closes the loop (thesis → memo → hypothesis →
  verdict → sizing) without the user copy-pasting ids across apps.
- Deterministic validation and triage integrations that need no LLM at all
  (canvas↔Marcus invalidation-condition checking; observation↔Sarah surface
  reads) — the cheapest, highest-daily-value seams.
- The review→feedback loop (spec'd in the reference doc §5, built later),
  which today dead-ends in RCS.

**Stays manual until the LLM layer lands:**
- Cross-app navigation (the user still clicks between `:5173` and `:8099`).
- Free-text citation of `PTM-…` ids and `rcs://thesis/<ULID>` references
  (the convention exists; the structural link fields do not yet).

**Required future work (out of scope for this docs-only ADR, recorded so it
is not forgotten):**
- Extend `rcs_bridge.py` to read thesis/canvas/observation/review *content*,
  not just counts. Today it reads the thesis table only as `COUNT(*)`.
- Add typed link fields on the trading side: `hypothesis_registry.source_thesis_ulid`
  and a mapping table `rcs_thesis_x_analysis(thesis_ulid, analysis_kind,
  analysis_id, linked_at)`. Turns the free-text `rcs://` convention into a
  real enforced field. All trading-side; RCS untouched (ADR-003 holds).
- Adopt `rcs://thesis/<ULID>` as a real citation, not just a hint the
  Ashurbanipal library scanner interprets.

**~~Known issue to fix when any structural-link work begins:~~ RESOLVED.**
`config.RCS_DB_PATH` used to point at the in-repo default
`research-capture-system/research/data/research.db` while RCS's `.env`
redirected the *live* server to `~/.local/state/rcs/research.db`, so the
bridge read a stale snapshot. `config._resolve_rcs_db_path()` now follows the
RCS `.env` (falling back to the in-repo default if it is absent) — RCS owns
its DB location and the bridge follows it.

## Progress against the required future work

**Done (2026-08-03) — the `trade → Sarah` analysis seam**
(`docs/wiki/01-components/sarah-vol-workspace.md#rcs-trade-intake`): a trade
committed in RCS deterministically triggers Sarah's vol pull and arrives with
every Class-A/B field pre-filled, leaving only the user's `expected_move`.
This realises the ADR's claim in miniature — it is deterministic (no LLM), it
extends `rcs_bridge.py` to read *content* (`entity_events`, legs, options
meta, `thesis.worst_case_dollar`) rather than counts, and it adds the first
real typed link field on the trading side
(`pretrade_memos.rcs_trade_ulid` + the `sarah_trade_inputs` table, both keyed
by RCS ULID, both trading-side, RCS untouched). It is also the exact hook the
LLM layer should call rather than improvising the relationship.

**Still outstanding:** `hypothesis_registry.source_thesis_ulid`, the general
`rcs_thesis_x_analysis` mapping table, and adopting `rcs://thesis/<ULID>` as
an enforced citation rather than a convention.

## What this ADR does *not* decide

- The model host, capability tier, or in-app-vs-external question for the
  LLM layer. Those are deferred and orthogonal to this substrate.
- The review→feedback implementation. Spec'd in the reference doc, built
  later (it is the highest-value but hardest integration; see §5 there).
- Resolution of the source-material gaps in reference doc §6 (Alex has no
  persona doc; Elena is under-connected; Marcus's surname is inconsistent;
  etc.). Surfaced for decision, not silently resolved.
