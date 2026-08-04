---
domain: trading-system
stage: contracts
project: rcs-integration
status: active
---

# RCS ↔ Trading Capability Contracts

*The deterministic substrate for integrating the Research Capture System
(RCS, `:8099`) with the trading workstation (`:8100`). Each RCS entity has a
typed relationship to one trading capability. This document codifies those
relationships as contracts — field-level on the RCS side, gate-level on the
trading side — so that a future LLM assistant operates over reliable,
typed seams rather than improvising them.*

**Companion decision record:** [ADR-005](../../design_decisions/ADR-005-rcs-trading-integration.md).
**Read-only rule (unchanged):** [ADR-003](../../design_decisions/ADR-003-rcs-bridge.md).
All change is on the trading side. RCS is never written from this repo.

**RCS schema source of truth:** `research-capture-system/research/db/schema.sql`
(+ `triggers.sql`, `views.sql`). Entity fields quoted below are verbatim
from that schema. Lifecycle/status values are the literal `CHECK` enum values.

---

## §1 The capability map

For each RCS entity: its semantic role, its trading counterpart, the
integration *type*, what it needs from trading, and what it offers trading.
The integration type determines whether the seam is a pure read (cheapest),
a translation (the LLM's job), or a gated write (the discipline surface).

### 1.1 canvas ↔ Marcus — **validation**

**Canvas** = a persistent macro belief ("the world looks like X"). Fields:
`id, name, narrative, status('active'|'archived'), last_reviewed, created_at`.
Children: `canvas_invalidation_conditions` (`condition, type('necessary'|'sufficient'),
probability('low'|'medium'|'high'), lead_time_days, last_assessed`),
`canvas_cross_currents`, `canvas_version_history` (append-only),
`canvas_source_documents` (library backlinks).

- **Integration type:** validation — does the market measurement still agree
  with the stated belief?
- **Canvas needs from Marcus:** the current component scores, fragility
  assessment, transition probability — to check each `invalidation_condition`
  against.
- **Canvas offers Marcus:** the human *why* behind a regime call. Marcus
  measures; the canvas explains what the user believes is driving it.
- **The contract surface:** each `canvas_invalidation_condition` is a
  monitoring spec (`probability` + `lead_time_days` is literally a
  monitoring cadence). The deterministic check is: "for each active canvas's
  invalidation conditions, is Marcus's output within the condition's
  tolerance, and is the condition's `last_assessed` within its `lead_time_days`?"
  The `stale_invalidation_conditions` view (>21 days) already flags overdue
  conditions on the RCS side.
- **No write needed.** This is the cheapest, highest-daily-value seam: a
  pure read on both sides, narrated by the LLM.

### 1.2 thesis ↔ Sarah + Priya — **analysis**

**Thesis** = a directional + structural bet on an instrument. Fields: `id,
instrument, status('building'|'ready'|'active'|'invalidated'|'archived'),
narrative, win_condition, worst_case_dollar, linked_trade_id, created_at,
last_updated`. Children: `thesis_kill_conditions_macro` (`condition,
linked_canvas_id, fired_at`), `thesis_kill_conditions_technical`
(`condition, linked_setup_id, fired_at`), `thesis_decision_points`
(`trigger, decision, instrument, size_pct, fired_at, deviation_note`),
`thesis_version_history`.

The `ready` gate (DB-enforced via `thesis_ready_gate` trigger): ≥1 macro
kill condition, ≥1 decision point, `worst_case_dollar > 0`, ≥1 linked
canvas. The `active` gate requires `linked_trade_id` pointing at an active
trade. Note `invalidated` is **not** terminal — a thesis can cycle
`invalidated → building → ready → active`.

- **Integration type:** analysis — structure the expression (Sarah) and
  validate the edge (Priya).
- **Thesis needs from Sarah/Priya:** Sarah memo inputs derived from
  `instrument` + `narrative` + `win_condition`; a Priya hypothesis whose
  `rationale` cites `rcs://thesis/<ULID>`.
- **Thesis offers Sarah/Priya:** the tradable expression + the falsification
  conditions (kill conditions are literally Sarah's "what's the kill
  scenario?" question, pre-registered).
- **The contract surface:** the `ready` gate is the natural trigger. A
  thesis at `ready` has done the RCS-side discipline (macro kill conditions,
  decision points, worst-case dollar, linked canvas); the trading side's job
  is to translate that into a memo + hypothesis, run them, and link the
  outputs back via `PTM-…` id and `hypothesis_id`. The kill conditions are
  the monitoring contract post-execution (§4 contract 4).

### 1.3 setup ↔ Sarah — **evidence**

**Setup** = a frozen evidence snapshot. Fields: `id, name, instrument,
type('technical'|'vol'|'flow'), timeframe, setup_note, date, created_at`.
**Append-only** (trigger blocks changes to all fields except `setup_note`;
blocks DELETE). Child: `setup_images`. Junctions: `setup_thesis_links`
(canonical setup↔thesis), `setup_linked_canvases`.

- **Integration type:** evidence — does the current surface confirm or
  contradict the frozen snapshot?
- **Setup needs from Sarah:** the current vol surface / Greeks / structure
  for its `instrument`, to compare against the snapshot.
- **Setup offers Sarah:** append-only proof backing a thesis. The
  `type` field ('technical'|'vol'|'flow') routes which Sarah tool checks it.
- **The contract surface:** given a setup, surface "since this snapshot was
  frozen on `date`, here's what changed on the surface." Deterministic read.

### 1.4 observation ↔ Sarah — **triage**

**Observation** = a cheap "I noticed something." Fields: `id, name,
instrument, status('watching'|'taken'|'passed'), note, passed_reason,
passed_reason_type('psychological'|'analytical'), date, created_at`.
`watching → taken|passed` are the only transitions; both terminal. `taken`
requires ≥1 linked thesis (`observation_taken_gate`); `passed` requires
`passed_reason` + `passed_reason_type` (`observation_passed_gate`).

- **Integration type:** triage — is this worth promoting to a thesis?
- **Observation needs from Sarah:** a quick surface read on `instrument` so
  the watching is informed.
- **Observation offers Sarah/the user:** the funnel top. Over time,
  `passed_reason_type` distribution is self-knowledge data ("I pass 60% of
  observations for psychological reasons" is a real finding).
- **The contract surface:** when an observation is created on `instrument`,
  the trading side surfaces the current surface state + any active canvas
  relevant to that instrument. The `taken` gate (must link a thesis) is the
  promotion path; the LLM's job is to ask "still watching, or promote?"

### 1.5 trade ↔ Jordan — **risk** *(already built)*

**Trade** = the commitment. Fields: `id, name, instrument, idea_note,
thesis_id (FK), instrument_type('equity'|'option'|'future'|'fx'|'other'),
entry_rules_stated, exit_rules_stated, thesis_snapshot, status('idea'|
'active'|'closed'|'discarded'), review_id, created_at, closed_at`.
`idea → active` freezes `entry_rules_stated`, `exit_rules_stated`,
`thesis_snapshot` (trigger-enforced). Children: `trade_entries`,
`trade_exits` (append-only), `trade_options_meta` (1:1, greeks + IV at
entry/exit + max_loss), `trade_option_legs` (append-only except
`exit_premium`/`date_closed`).

- **Integration type:** risk — the trade becomes Jordan's book position.
- **This seam is already live** via `rcs_bridge.fetch_active_trades()` →
  Jordan's positions book. Frozen fields are the immutable contract; the
  append-only children are safe to stream incrementally.
- **Known gap:** `trade` events are explicitly excluded from the RCS
  `export_watermarks` (Design Decision 12 in the RCS schema). The bridge
  reads `trade` directly today; that read path remains the integration
  point, not an exporter.

### 1.6 review ↔ Priya + canvas — **feedback** *(spec'd here, built later — see §5)*

**Review** = post-close learning, two-phase with a 24h Zone-3 timelock.
Phase 1 (at close): `trade_id, closed_at, entry_fill, exit_fill,
thesis_at_entry, exit_rules_as_written, what_i_actually_did,
emotional_state (single word), rules_followed('yes'|'no'|'partial'),
locked_at`. Phase 2a: `zone_3_clear` (requires ≥24h after `locked_at`,
trigger-enforced). Phase 2b: `phase2_created_at, mistake_type('type_1'|
'type_2'|'type_3'), analysis, single_update, what_not_changing`.

- **Integration type:** feedback — what did this trade teach, and where does
  that learning flow?
- **Review offers Priya/canvas:** the mistake taxonomy is *exactly* the
  signal that should inform hypothesis pursuit and canvas re-assessment.
  Repeated `type_2` (wrong process) on a setup type → a backtestable Priya
  hypothesis about entry timing. `type_3` (wrong process, won) → a warning
  not to reinforce the behavior.
- **This is the hardest integration.** Spec'd in §5, built later.

### 1.7 action ↔ Alex + calendar — **scheduling**

**Action** = a task with a due date. Fields: `id, instrument, action,
due_date, linked_thesis_id (FK), linked_setup_id (FK), status('open'|
'done'|'cancelled'), cancellation_note, created_at`. `cancelled` requires
`cancellation_note` (trigger).

- **Integration type:** scheduling — nudge at the right market time.
- **Action needs from Alex/calendar:** the macro calendar (FOMC, CPI, NFP,
  earnings, OPEX) to time the nudge.
- **Action offers Alex:** reminders tied to market events, linked to a
  thesis or setup.
- **The contract surface:** the `overdue_actions` view exists on the RCS
  side; the trading side's `/api/marcus/calendar` is the timing source. The
  deterministic join is "action.due_date ↔ next relevant calendar event for
  action.instrument."

### 1.8 insight ↔ LLM narration — **memory**

**Insight** = a polymorphic sticky note on anything. Fields: `id, name,
note, linked_entity_type('canvas'|'thesis'|'observation'|'setup'|'trade'|
'review'), linked_entity_id (no FK — intentional), context_tag, created_at`.
No status, no lifecycle, append-only in practice.

- **Integration type:** memory — where the LLM's synthesis lands.
- **Insight needs from trading:** nothing live. It's a sink.
- **Insight offers the LLM:** long-term annotations tied to any entity. The
  polymorphic link is the natural place for the LLM to record "here's what
  I noticed about this thesis/trade/canvas" without writing to either app's
  structured fields.
- **Note:** `linked_entity_id` has no FK by design (migration `005_insight`).
  The LLM must validate the link exists before relying on it.

---

## §2 The collaboration graph, made deterministic

The persona profiles (`~/Nextcloud/Claude/B-trading-system/Personas/`)
describe a seven-node collaboration graph in narrative form. This section
restates those edges as routing rules: **which RCS entity + which trading
output triggers which downstream check.** The personas stop being story and
become policy here.

### 2.1 Authority hierarchy (which checks can be skipped, which cannot)

Ranked by hardness, with the persona doc it comes from:

1. **Jordan — hard override + production gate.** Circuit-breaker Level 2
   forces reduce-only posture (Kai doc). Production simulation gates which
   strategies survive (Kai doc). Drawdown-tier breaches are
   non-discretionary ("conviction cited as a reason to hold through a tier
   breach" is a red flag, Jordan doc). Marcus regime shifts trigger
   tightening *before confirmation* (Jordan doc). **Strongest veto in the
   system.** → *No integration may route around Jordan's intake checks.*
2. **Priya — research sign-off gate.** "A signal is not research-complete
   until Priya signs off" (Sam doc). Required before live trading. → *A
   thesis at `ready` queues analysis; it does not authorize action. The
   Priya verdict (GO/NO_GO) is the gate.*
3. **Sam — operational-documentation gate (paired with Priya).** "No
   strategy goes live without a complete signal library entry" (Sam doc).
   Sam's authority stops at detection — coherence gaps are escalated, not
   unilaterally resolved. → *Operational completeness is a co-gate with
   research completeness.*
4. **Kai — soft veto via escalation.** Reality-check on Priya's execution
   assumptions (Kai doc); mandatory escalation on >20% TCA divergence. A
   forcing function, not a hard block. → *Kai is deferred to v1.1
   (ADR-004); the contract surface exists but the executor is manual.*
5. **Marcus — regime authority, indirect.** No direct veto, but
   classification forces downstream reconfiguration (Marcus → Jordan
   tightening, Marcus → Kai conservative posture). → *Every downstream
   consumer reads Marcus; the regime gate (CLAUDE.md Rule 4) is the spine.*
6. **Alex — prioritization only.** Research-queue EV ranking, capacity
   allocation. No documented block/veto. Effectively the PM's
   chief-of-staff, not an approver. → *Alex schedules and ranks; Alex does
   not approve.*
7. **Elena — advisory only.** No block on trades. Can recommend size
   reduction during compromised state. → *Elena's outputs are signals, not
   gates.*

### 2.2 The directed edges (RCS entity + trading output → downstream check)

Each edge names the trigger and what flows. Quote-anchored to the persona docs.

**Regime propagation (Marcus out):**
- `Marcus.regime_change_probability` + `Marcus.fragility` → **canvas** :
  re-check each active canvas's `invalidation_conditions` against the new
  component scores. (Jordan doc: "regime shift signal from Marcus triggers
  limit tightening before confirmation, not after" — the same signal should
  trigger canvas re-assessment.)
- `Marcus.regime` → **Jordan** : "regime classification changes Jordan's
  limit framework in real time" (Jordan doc). The verdict intake's
  `regime_compatible` check (already implemented) is this edge.
- `Marcus.regime` → **Priya** : every regime-conditional Sharpe is computed
  against Marcus's classification; a conflict between a signal's regime
  conditions and Marcus's current assessment "is an escalation" (Priya doc).

**Analysis handoff (thesis → Sarah/Priya):**
- `thesis.status = 'ready'` → **Sarah** : build a pre-trade memo from
  `instrument` + `narrative` + `win_condition` + `worst_case_dollar`. The
  memo's kill scenario is the thesis's macro kill conditions restated.
- `thesis.status = 'ready'` → **Priya** : register a hypothesis with
  `rationale` citing `rcs://thesis/<ULID>`. "Sarah generates hypotheses
  from market structure intuition; Priya validates whether the data supports
  them. Productive tension is the point." (Priya doc.)
- `Sarah.memo (PTM-…)` + `Priya.verdict` → **thesis** : link back via
  `source_thesis_ulid` (to be added) + the mapping table. The thesis
  becomes the join key between the two analyses.

**Risk enforcement (Jordan out — the hard edges):**
- `Priya.verdict = GO` → **Jordan.verdict_intake** : the 5-check gate
  (verdict_exists, verdict_fresh, verdict_go, viable_after_haircut,
  regime_compatible). "Never help size around a failed intake check"
  (LLM Assistant Guide §2.3). This is non-negotiable.
- `Jordan.drawdown_tier ≥ 2` → **Alex** (immediate, not weekly) + **Elena**
  (if emotional responses observed affecting decision quality). (Jordan doc.)
- `Jordan.circuit_breaker_level = 2` → **Kai** : reduce-only posture. Hard
  override of execution. (Kai doc; deferred to v1.1.)

**Feedback (Kai/Sam → Priya — the production-gap loop):**
- `Kai.TCA` (rolling 20-trade) > assumption by >20% → **Priya** : escalate,
  recalibrate transaction-cost assumptions. (Kai doc.) *Deferred to v1.1
  with Kai; the contract surface exists.*
- `Sam.P&L_attribution` → **Jordan** : "Sam's P&L attribution is Jordan's
  primary input for drawdown analysis and tier decisions." (Jordan doc.)
  *Sam is post-v1.0; the attribution input is currently manual.*

**Coordination (Alex/Sam):**
- `Alex.EV_ranking` → **Priya** : research-queue priority. "Prioritize
  research queue — that is Alex and Priya." (Sam doc.) Alex ranks; Priya
  executes.
- `Sam.coherence_gap` → **Alex + PM** (escalated, not unilaterally
  resolved). (Sam doc.) *Sam is post-v1.0.*

### 2.3 What this means for the integration

The LLM mediator respects this graph: it can read across nodes, but writes
respect the authority hierarchy. Concretely — a thesis at `ready` can ask
Sarah to build a memo and Priya to register a hypothesis (both writes go to
the trading side, never to RCS). But no amount of thesis conviction routes
around a failed Jordan intake check, and no Priya verdict authorizes action
without the operational sign-off. The hierarchy is the policy; the LLM is
the executor.

---

## §3 Distillation-grounded gates, as contracts

The trading engines are built on distilled finance literature. This section
codifies the gates and measurements as the *contract surface* the RCS↔trading
links must respect — so that "thesis queues a job" never becomes "job output
gets used naively for sizing." Each item is tagged with its source.

Sources are in `~/Nextcloud/Claude/B-trading-system/Research/Distillations/`
(Jordan) and `~/Nextcloud/Claude/B-trading-system/priya backtest/v1/resource distills/` (Priya).

### 3.1 Priya pipeline gates (research validation)

A thesis that triggers a Priya hypothesis must pass through this pipeline.
Each gate is a hard stop; none can be silently relaxed (relaxing a guarded
gate is logged forever on the verdict — CLAUDE.md).

**Pre-backtest (formation):**
- **Hypothesis pre-registration** before any backtest — *AFML Ch 11, LdP 2018*.
  The thesis's `narrative` + `win_condition` is the natural pre-registration
  input; the `rationale` field must state the *mechanism*, not just the pattern.
- **Trials register** (trial id, params, IS SR, OOS SR, date) — *AFML Ch 14,
  PBO §1*. Mandatory, not reconstructed.
- **Bar-construction method** as metadata (dollar/volume bars preferred over
  time bars) — *LdP 2018*.

**Cross-validation:**
- **PurgedKFold + embargo** (h ≈ 0.01·T) replaces sklearn KFold — *AFML Ch 7*.
- **CPCV** primary (φ[N,k] paths, distribution of Sharpe ratios);
  walk-forward secondary and labeled "single-path high-variance" — *AFML Ch 12*.
- **CSCV parameters**: S=16 default (S=24 for >6yr daily), T=2× model-selection
  observations — *PBO (Bailey et al 2014)*.

**Performance gates (all required, in order):**
- **Sharpe SE + 95% CI** on every Sharpe output (non-optional) — *Lo 2002*.
- **Ljung-Box test** → branch IID vs robust estimator; **η(q)** scale factor
  when autocorrelation present — *Lo 2002*.
- **PSR ≥ 0.95** — *AFML Ch 14*.
- **DSR ≥ 0.95** (requires N + V[{SR̂_n}]) — *AFML Ch 14, LdP 2018*.
- **PBO ≤ 0.05** with all four overfit statistics — *PBO*.
- **Strategy-risk P[p < p_θ*] ≤ 0.05** — *AFML Ch 15*.
- **Monte Carlo P&L distribution** (not single path) — *Sinclair*.
- **Decomposed P&L** (delta/gamma/vega/theta) — *Sinclair*.
- **Leland breakeven spread** pre-trade on every short-vol simulation — *Sinclair*.
- **Implementation shortfall** as required field — *AFML Ch 14*.

### 3.2 Jordan risk measurements (sizing & limits)

A Priya verdict that reaches Jordan is consumed under these contracts. The
key point: **Jordan never consumes Priya's raw Sharpe** — the haircut bridge
(§4 contract 1) sits between them.

**Primary risk metrics (computed & enforced):**
- **CVaR / WCE** as primary limit metric; VaR demoted to reporting — *Artzner 1999*.
- **Scenario supremum** `ρ(X) = sup{E_P[−X/r] | P∈P}` — the coherent measure;
  the scenario library *is* the measure — *Artzner Prop 4.1*.
- **Margin utilization ratio** `Σ(x·m)/W` real-time (Level-4 fund metric) —
  *Brunnermeier-Pedersen 2009 Eq 4*.
- **Portfolio simultaneous-liquidation cost** (not per-position
  days-to-liquidate) — *B&P Prop 6*.
- **Greeks hierarchy** every 30 min: delta, gamma, vega, theta, rho + **cross-Greeks:
  vanna, volga, charm** — *Hull, Natenberg*.
- **Vega by term bucket** ($ per 1% IV) — *Hull BusSnap 19.1*.
- **DTE-contingent gamma limits** (independent dimension from VIX; tighten
  when DTE<14 + ATM + low vol) — *Natenberg*.
- **Quadratic/MC VaR** (linear forbidden on options); **ES not VaR** for fund
  survival limits — *Hull*.
- **Kelly ceiling** `c × f*` per strategy; **multi-asset F* = C⁻¹[M−R]** using
  stress covariance — *Thorp*.
- **Stress bid/ask (not mid)** folded *inside* scenario P&L, differentiated
  by margin tier — *Artzner Remark 2.8, Natenberg, B&P Prop 6*.
- **Endogenous margin-escalation path** in every stress scenario — *B&P Prop 3*.

**Kill vs Hurt categorization (Jordan's own framework, grounded by):**
- *Kill* (hard limits, survival): CVaR/scenario supremum (Artzner), margin
  utilization ratio (B&P), ES at fund level (Hull), Kelly ceiling (Thorp).
- *Hurt* (soft limits, monitoring): per-Greek limits (Hull), breakeven-vol-
  distance (Natenberg), Sharpe SE (Sinclair/Lo).

---

## §4 The seven Priya ↔ Jordan handoff contracts

These are the load-bearing inter-layer contracts the distillations justify.
They are the reason "thesis → job → sizing" is not a naive pipeline. Each is
a typed input/output spec.

### Contract 1 — Edge haircut *(the central bridge)*
*Grounded in Thorp §7.3 p27.*

```
Priya outputs: { SR̂_research, V[{SR̂_n}], N_trials, skew γ̂₃, kurt γ̂₄, autocorr ρ_k }
Jordan applies: f*_production = c · (m_haircut − r) / s²
where  m_haircut = SR̂_research − haircut_factor
       c ∈ [0.5, 1.0]   (Thorp recommended band)
Justification: "me > mt is likely" — research edge systematically overstated.
```
**This is the single most important inter-layer contract.** Without it the
system structurally overbets. The verdict intake's `viable_after_haircut`
check is the live enforcement; the contract codifies *why*.

### Contract 2 — Covariance matrix handoff
*Thorp Eq 8.2 + B&P Prop 6.*

```
Priya computes: C_normal (strategy-return covariance from CPCV paths)
Jordan consumes: C_stress (correlation-stressed; at Cor→1, individual f* halves)
F* = C_stress⁻¹[M_haircut − R]
Justification: Thorp Table 5; B&P Prop 6 commonality of fragility
              (correlations → 1 in crises).
```
Priya's normal-regime C cannot be used directly for sizing — Jordan must
stress it.

### Contract 3 — CPCV paths → scenario library
*AFML Ch 12 + Artzner Prop 4.1.*

```
Priya's φ[N,k] CPCV paths feed Jordan's scenario library P
Justification: Artzner requires scenario coverage of Ω;
              CPCV paths are empirically-grounded Ω partitions.
```

### Contract 4 — Triple-barrier exit conditions → Greeks-monitoring triggers
*AFML Ch 3 + Natenberg Ch 21.*

```
Priya defines: { profit_take_level, stop_loss_level, vertical_barrier_t1 }
               (vol-scaled, path-dependent)
Jordan monitors: live Greeks & P&L against these barriers; tier escalation
                 triggers if production path approaches stop_loss barrier
                 before vertical barrier.
```
This is the live monitoring contract post-execution. The thesis's macro kill
conditions (§1.2) map onto the stop-loss barrier semantically.

### Contract 5 — Transaction-cost model → stress bid/ask
*Sinclair + AFML implementation shortfall → Jordan stress bid/ask.*

```
Priya computes: Leland-adjusted breakeven spread, slippage via TCA
Jordan consumes: stress bid/ask multiplier per margin tier (5–10× normal),
                 differentiated by flight-to-quality haircut
Justification: Sinclair Leland; B&P Prop 6(iii)–(iv); Artzner Remark 2.8
              (liquidity cost inside scenario P&L, not overlay).
```

### Contract 6 — Strategy-risk vs portfolio-risk separation
*AFML Ch 15 p217 explicit.*

```
Priya outputs: strategy risk  P[p < p_θ*]   (binomial precision model)
Jordan outputs: portfolio risk (CVaR, Greeks, margin util)
Both must be present at deployment decision; high portfolio risk does NOT
imply high strategy risk and vice versa.
```

### Contract 7 — Trial-count propagation
*AFML Third Law + PBO §1 + Lo 2002.*

```
Priya logs: N_trials at research time (mandatory, not reconstructed)
Jordan uses: N_trials as input to DSR-based haircut factor
              (higher N → larger haircut, because more selection bias)
```

### Three load-bearing tensions to resolve before locking these as code
*(flagged for the implementation phase, not silently resolved here)*

1. **TCE vs WCE on discrete scenarios** (Artzner §3): standard scipy/empyrical
   CVaR returns TCE; for Jordan's named scenarios (2018/2020/2022) the
   distribution has point masses → TCE < WCE. Decision: implement WCE for
   limit computation, or use TCE with explicit "lower bound" labeling.
2. **Parametric vs historical VaR** (Natenberg + Artzner vs any Gaussian
   optimizer): mean-variance tools are *qualified, not primary*, for options
   portfolios. Thorp §6 p21: "covariance or correlation information is not
   enough" for non-Gaussian options returns.
3. **Margin path vs terminal P&L** (B&P + Natenberg vs any terminal-only
   stress framework): endogenous margin-escalation path + projected peak
   margin call must be separate outputs, not a tuning parameter.

---

## §5 The feedback loop (review → Priya/canvas) — spec'd, not built

Per ADR-005: this is the highest-value but hardest integration. Spec'd here;
built later. The review is where the system learns, and right now nothing
reads it back.

### 5.1 The contracts (to be built)

**Contract F1 — review → Priya hypothesis signal:**
```
Trigger: review with zone_3_clear = 1 AND mistake_type = 'type_2'
         (wrong process, regardless of P&L outcome)
Surface: to the LLM — "this closed trade's review classifies a process error;
         the thesis's entry timing is a candidate Priya hypothesis
         (mechanism: entry-timing edge on <setup.type> setups)."
Action:  LLM-drafted hypothesis rationale, citing rcs://review/<ULID>,
         offered to the user for Priya pre-registration. Not auto-registered.
```

**Contract F2 — review → canvas re-assessment:**
```
Trigger: ≥2 reviews on trades linked to theses linked to canvas C,
         with mistake_type = 'type_2' OR rules_followed = 'no'
Surface: to the LLM — "canvas C's invalidation conditions may need
         re-assessment; the user's process is breaking under it repeatedly."
Action:  LLM-surfaced prompt to re-assess canvas C's conditions.
         Updates happen in RCS by the user, never from the trading side.
```

**Contract F3 — type_3 warning (the "lucky win" guard):**
```
Trigger: review with mistake_type = 'type_3' (wrong process, won)
Surface: to the LLM — "this win resulted from a process error; do not
         reinforce the behavior. Flag the linked thesis's strategy as
         'benefited from luck, not edge' for future sizing."
Action:  Annotation on the thesis via the mapping table; no auto-sizing change.
```

### 5.2 Why this is the hardest integration (reasons it's deferred)

1. **Correlation machinery.** Detecting "repeated type_2 on a setup type"
   requires joining reviews across trades across theses across setups — a
   multi-hop graph query. The data exists; the query layer does not.
2. **LLM reasoning-quality dependency.** Drafting a hypothesis rationale from
   a review's `analysis` field is genuinely a reasoning task, and a weak
   model will produce plausible-sounding but wrong hypotheses. This integration
   is where the model-quality question bites hardest.
3. **Elena's persona is under-connected in the source material** (see §6).
   The review loop is Elena's domain (mistake taxonomy, three-zone
   separation, post-trade protocol), but her persona doc names zero other
   personas. Before building, Elena's edges to Priya/canvas need to be
   specified explicitly.

### 5.3 What stays in RCS

The review entity itself, the Zone-3 timelock, and the mistake taxonomy are
all RCS-owned and correct as-is. The trading side only *reads* completed
reviews (`zone_3_clear = 1`) and *surfaces* derived signals — it never
writes reviews, never short-circuits the timelock, and never reclassifies a
mistake type.

---

## §6 Open questions / gaps in the source material

Found while distilling the personas. **Surfaced for your decision, not
silently resolved.** Each blocks some part of the contracts above from
becoming code.

1. **Alex Rivera has no persona document.** He is defined only in
   `boutique_pm_toolkits.md` §1 (~13 lines) and `zero_dollar_stack_and_build_sequence.md`
   Phase 6. His contracts (capacity allocation → Jordan; research-queue
   priority → Priya) are under-specified one-liners. **Needed:** an Alex
   persona doc before §1.7 (action↔Alex) and the Alex edges in §2.2 become
   code. He is the least-defined of the seven personas.
2. **Elena Sokolova's node is under-connected.** Her persona doc names zero
   other personas; her only edges come from Sam's and Jordan's docs. If she
   is supposed to consume decision-quality signals from Marcus/Sarah/Priya/Kai
   (not just Sam's decision log), those edges are undocumented. **Needed:**
   Elena's edges to Priya/canvas (§5) before the feedback loop is built.
3. **Marcus's surname is inconsistent.** Kai's doc and `boutique_pm_toolkits`
   say "Marcus **Webb**"; `elite_macro_trader_persona.md` says "Marcus **Wei**."
   Two different surnames for the same node. **Needed:** pick one canonical
   identifier before any cross-reference system lands.
4. **"The PM" is referenced as an 8th node but never identified.** Sam's doc
   line 959: "escalated to Alex **and the PM**." The PM is never identified as
   one of the seven personas. **Needed:** decide whether PM = Marcus-as-CIO,
   = Alex, or is an eighth node (you, the user).
5. **Two macro persona files exist.** `elite_macro_trader_persona.md` (Marcus)
   and `macro_research_expert_persona.md`. Confirm whether the latter is a
   second macro node or a duplicate before finalizing the graph.
6. **Duplicate Elena file.** `trading_psychology_persona_dr_elena_sokolova_1.md`
   is a byte-identical-size duplicate. Worth deduplicating so the system
   doesn't model two Elena nodes.

---

*This document is the deterministic substrate. The LLM layer (when added)
operates over these contracts; it does not define them. Where the contracts
are silent, the LLM must ask the user rather than improvise — because an
improvised relationship across this seam is exactly the kind of thing that
looks helpful until it routes around a gate.*
