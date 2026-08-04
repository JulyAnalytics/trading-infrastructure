# Audit #5: Jordan / Risk Layer
**Generated:** 2026-07-17 (audit-as-built — written alongside the v1.0 build, per the audit prompt's instruction for this layer)
**Scope:** `systems/risk/` (5 modules) + `/api/jordan/*` routes + the Jordan workspace page
**Verified against:** `scripts/verify_jordan.py` 21/21 (synthetic RCS DB) **and** a live smoke against the real `research.db` on 2026-07-17 (results in the Validation section — two live-only bugs were found and fixed during that smoke)

**Grounding.** This layer implements the risk-desk function specified in
`Claude/B-trading-system/Personas/risk_manager_jordan_okafor.md` and the Phase 5
section of `zero_dollar_stack_and_build_sequence.md`, informed by the source
distillations in `Claude/B-trading-system/Research/Distillations/`:
Artzner et al. 1999 (coherent risk measures), Brunnermeier & Pedersen 2009
(market/funding liquidity spirals), Hull 11e ch. 19/22/23 (Greeks, VaR/ES,
vol estimation), Natenberg 2e ch. 7–8 (Greeks interpretation, dynamic
hedging path dependency), and Thorp 2006 (Kelly criterion). Where the build
deliberately implements less than the persona's full framework, that is
recorded as a gap below rather than silently dropped.

---

## DOCUMENT 1: CAPABILITY MAP

---

### Component: RCS Bridge (positions source)

**File path:** `systems/risk/rcs_bridge.py`
**Module:** Jordan / risk layer
**What it does:** Read-only adapter over the Research Capture System's SQLite
database. Turns the user's journaled trades (the RCS is where trades are
actually recorded) into Jordan's raw position material, and provides journal
activity counts for Alex's weekly review. It is the integration point that
makes Jordan's book reflect the *actual* book rather than a parallel manual
ledger.
**Inputs:**
- `research.db` (path from `config.RCS_DB_PATH`), opened with SQLite's
  `mode=ro` URI flag — writes are impossible at the driver level (ADR-003)
- Tables read: `trade`, `trade_entries`, `trade_exits`, `trade_option_legs`,
  `trade_options_meta`, `review`, `observation`, `thesis`
**Outputs:**
- `fetch_active_trades()` → list of trade dicts with net open size (entries −
  exits), average entry price, option legs, and options metadata
- `weekly_activity(days)` → journal counts (trades opened/closed/active,
  reviews completed, observations, theses updated) for the weekly review
- `entity_url()` → deep links into the RCS UI at :8099
**Dependencies:** the RCS application owns the schema; if RCS migrates its
schema this bridge must follow (see the `review.created_at` incident below).
If the DB file is absent the bridge degrades to `available: False` — Jordan
still runs on manual positions only.
**Implementation status:** Complete. Read-only guarantee verified against the
**real** database (a `CREATE TABLE` attempt on the live connection is rejected
by the driver).
**Gap vs architecture:**
- The bridge docstring originally asserted `review(id, …, created_at)`; the
  real schema has no `created_at` on `review` (it has `closed_at NOT NULL`,
  `locked_at`, `phase2_created_at`). `reviews_completed` silently returned
  `None` until the 2026-07-17 live smoke caught it — fixed to count on
  `closed_at`. Lesson recorded: the synthetic test DB validated the bridge's
  *logic* but not the *schema contract*; only a live smoke does that.
- One-way integration only. The architecture's optional "market context panel"
  inside RCS (regime + vol snapshot pulled from this repo's API) is documented
  as deferred (v1.0 plan, workstream G).

---

### Component: Positions Book

**File path:** `systems/risk/book.py`
**Module:** Jordan / risk layer
**What it does:** Assembles Jordan's book from two sources — active RCS trades
(via the bridge) and manual positions in `trading.db.jordan_positions` — then
prices every position live and aggregates Greeks and dollar exposures. This is
the persona's Level-3 aggregation ("Greeks aggregated across portfolio"): the
point where individually-analyzed positions become one risk picture.
**Inputs:**
- RCS bridge output (option legs → option positions; equity trades → share
  positions with direction from signed net size)
- `jordan_positions` table (manual entry fallback, CRUD via `/api/jordan/positions`)
- Live market data: yfinance spot + options chains through Sarah's
  `GreeksTool.analyze_position()` (15–20 min delayed; every output carries the
  data warning)
**Outputs:**
- `load_book()` → positions list + per-source counts + RCS availability status
- `analyze_book()` → per-position Greeks (7 Greeks, scaled), delta dollars,
  vega dollars, notional; portfolio `net_greeks`, `concentration_flags`
  (vanna/charm/vomma thresholds from `GreeksTool`), `net_delta_dollars`,
  `net_vega_dollars`, `gross_notional`, and an `errors` list
- Consumed by `/api/jordan/analyze`, `limits.evaluate_limits`, `stress.stress_book`
**Dependencies:** Sarah's `GreeksTool` and `pricing.py` (reused, not
duplicated — one pricing library across the system); yfinance availability.
**Implementation status:** Complete. Per-position pricing failures degrade to
the `errors` list rather than blinding the whole board (an expired option or a
dead ticker does not take down the risk view).
**Gap vs architecture (persona Framework 1 — the six aggregation levels):**
- Levels 1–3 (notional, per-position Greeks, portfolio net Greeks) and the
  cross-Greeks part of Level 6 (vanna/charm/vomma with concentration flags)
  are implemented.
- **Level 4 (Greeks by bucket) is not**: no vega-by-term-bucket, no gamma-by-
  strike-concentration, no delta-by-underlying breakdown. Net numbers can hide
  exactly the concentrations the persona warns about ("vega by term bucket,
  not just net vega").
- **Level 5 (stress Greeks — how the Greeks themselves move under ±10% spot /
  ±10 vol) is not implemented**; the stress module shocks P&L, not the Greeks.
- Equity positions contribute delta only, with no beta adjustment — SPY delta
  dollars and single-name delta dollars are summed as if equivalent.
- Greeks are point-in-time. Natenberg ch. 8's path-dependency warning applies:
  terminal Greeks miss intraday hedge decay (charm is flagged but not
  projected).

---

### Component: Limits Framework

**File path:** `systems/risk/limits.py`
**Module:** Jordan / risk layer
**What it does:** Evaluates the analyzed book against Jordan's risk limits.
Limits are **registry parameters** (`JordanParams`) — GUI-editable, versioned,
hash-stamped — which implements the persona's rule that limits are negotiated
when they are set, not in the moment ("changing them under pressure is how
limits stop being limits"; here changing one is an explicit, audited act).
**Inputs:** `analyze_book()` output; `JordanParams` (nav, max_net_delta_pct,
max_net_vega_pct, max_single_position_pct, drawdown_alert_pct,
drawdown_halt_pct, min_liquidity_days, default_risk_pct_per_trade,
verdict_max_age_hours).
**Outputs:** per-check dict (value, limit, utilization, breached) + a flat
`breaches` list (feeds banners now; the Phase 6 alerter later), `ok` boolean.
Concentration flags from the book are folded into `breaches`.
**Dependencies:** parameter registry; book analysis.
**Implementation status:** Complete for delta / vega / single-position checks.
Greeks-based rather than notional-based, per the persona's Mental Model 5
("leverage is dimensionless — risk is not"; notional limits are meaningless
for an options book).
**Gap vs architecture:**
- **Drawdown check is declared, not evaluated.** The check returns
  `breached: False` with an explicit not-evaluated note. It needs a NAV/P&L
  history series, which lands with the Phase 6 weekly review. The alert/halt
  thresholds (8%/15%) already exist in the registry so the check activates
  without a schema change. Until then the persona's drawdown-tier protocol
  (4 tiers + velocity triggers) has **no automated substrate** — this is the
  single most important open item in the risk layer.
- **`min_liquidity_days` is a parameter without a check.** Days-to-liquidate
  at stress bid/ask (persona Level-4 fund limit; Brunnermeier–Pedersen's
  entire mechanism — margin spirals bind through liquidity, and bid/ask
  widens 5–10x precisely when you need to exit) cannot be computed from
  yfinance mid-price data. Honest status: the limit exists, nothing evaluates
  it, and it needs U4.1-grade bid/ask data. Documented deferral, not an
  oversight.
- **Limits are not regime-contingent.** The persona ties limit tightening to
  Marcus's regime (CAUTION → −20%, RISK_OFF_STRESS → −50%, tighten on the
  *transition signal*, not the confirmation). v1.0 limits are static; the
  regime is available in `regime_state.json` but not consulted here.
- Only the portfolio level of the persona's four-level limit hierarchy exists
  (plus a single-position notional check). Strategy-level and fund-level
  limits await multiple strategies and NAV history respectively.

---

### Component: Book-Level Stress

**File path:** `systems/risk/stress.py`
**Module:** Jordan / risk layer
**What it does:** Runs the whole analyzed book through the named historical
stress library (the same registry-editable library Sarah's scenario lab uses:
Volmageddon 2018, COVID 2020, 2022 rates shock, etc.), producing per-scenario
portfolio P&L with per-position contributions and a worst-case pointer. This
is the scenario-based risk measure of the layer — the Artzner distillation's
central result is that scenario-based measures (generalized SPAN) **are**
coherent while VaR is not, and the persona's method is scenario-anchored
("show me this in the March 2020 scenario"). The system deliberately ships
stress scenarios and no VaR number.
**Inputs:** `analyze_book()` output; `ScenarioEngine.stress_scenario_library()`
(registry: spot shock %, ABSOLUTE vol-point shock, duration per scenario).
**Outputs:** per-scenario `{pnl_flat, pnl_skew_amplified, contributions[]}`,
`worst_case`, and a methodology note. Options are repriced via Black-Scholes
under the shock (flat shift + skew-amplified variant); equities are linear in
the spot shock.
**Dependencies:** Sarah's `ScenarioEngine` (reused — one stress library, two
consumers); book analysis must have market data per position.
**Implementation status:** Complete as an endpoint approximation.
**Gap vs architecture:**
- **Endpoint, not path.** Same limitation as Sarah's Stage 3 (audit #3): the
  P&L is computed at the scenario endpoint. The persona's war stories are
  specifically about the path (margin calls mid-path, theta bleed before the
  spike, bid/ask widening on exit). Path reconstruction is gated on CBOE
  historical options EOD (U3.3/U5.2 — the pre-live-capital hard gate).
- **No liquidity stress.** P&L under shock assumes you can hold; exit cost at
  stress bid/ask is not modeled (see limits gap above; the persona's March
  2020 story — exit costs 5–8x estimates — is exactly this).
- **No correlation matrices.** The persona's three-matrix protocol (normal /
  stress / all-correlations-to-1) is not implemented; with a book of a few
  positions on index ETFs this currently overlaps heavily with the spot-shock
  scenarios, but it becomes a real gap as soon as strategies multiply.

---

### Component: Verdict Intake & Sizing

**File path:** `systems/risk/verdict_intake.py`
**Module:** Jordan / risk layer
**What it does:** The Priya → Jordan handoff, done defensively. Reads
`research_verdict.json` and annotates it with pass/fail checks — existence,
freshness, GO verdict, viability after production haircut, and regime
compatibility (does the strategy have a positive regime-conditional Sharpe in
the regime we are in *now*, not the one it was validated under). Only if all
checks pass is the strategy "actionable". Separately provides the
build-sequence sizing formula: units = (NAV × risk%) / |entry − stop|, capped
by the single-position limit.
**Inputs:** `research_verdict.json`, `regime_state.json` (CLAUDE.md Rule 4 —
missing regime blocks action), `JordanParams`.
**Outputs:** `intake()` → checks list + `actionable` boolean;
`suggest_size()` → units, notional, risk dollars, `capped_by`.
**Dependencies:** Priya's Stage 8 output contract; Marcus's regime contract.
**Implementation status:** Complete. Closes audit #4's G4-7 (HIGH) on the
consumer side: a GO verdict cannot be silently consumed after the regime has
shifted. Never mutates the verdict.
**Gap vs architecture:**
- Sizing is **fixed-fractional (1% NAV default), not Kelly.** The Thorp
  distillation's own warnings justify this: Kelly requires edge estimates
  whose errors dominate at small sample sizes, and over-betting the true
  Kelly fraction is catastrophic while under-betting merely slows growth —
  so a conservative fixed fraction is the defensible v1.0 stance. The
  connection (haircut Sharpe → fractional-Kelly-style scaling of risk%) is a
  research task before it is an engineering task.
- The intake checks freshness and regime, but not the persona's pre-approval
  checklist (kill-scenario defined, cross-Greeks analyzed, exit plan). Those
  live in the pre-trade memo (Sarah Stage 4) and are procedural, not enforced.

---

### Component: Workspace & API surface

**File path:** `systems/api/routes/jordan.py` + `frontend/src/pages/JordanPage.tsx`
**Module:** Jordan / risk layer (presentation)
**What it does:** `/api/jordan/book`, `/analyze` (limits + optional stress),
`/positions` CRUD (manual entries), `/verdict-intake`, `/size`,
`/rcs-activity`. The workspace shows the book, net Greeks, limit panel with
breach banners, stress table, intake checklist, and the sizing calculator —
the "planned trade" flow: system prepares the decision, the operator executes
manually at the broker and journals it in RCS, where the bridge picks it up.
**Implementation status:** Complete; all endpoints returned live data in the
2026-07-17 smoke.
**Gap vs architecture:** No standing "risk open / risk close" cadence — the
persona's daily rhythm arrives with the Phase 6 scheduler (Sarah-blocks-on-
Marcus dependency chain can then include a post-run Jordan limit evaluation
with alerting on breach).

---

## DOCUMENT 2: OUTPUT LITERACY

---

**Output name:** Net Greeks (`net_greeks`: delta, gamma, theta_daily, vega, vanna, charm, vomma)
**What it represents:** The book's aggregate sensitivity to the things that
move option P&L: underlying price (delta, and gamma = how fast delta changes),
time (theta = daily carry), implied volatility (vega), plus the cross-Greeks —
vanna (how delta shifts when vol moves), charm (how delta decays with time),
vomma (how vega itself moves with vol).
**Unit/format:** delta in share-equivalents; theta_daily and vega in dollars;
vanna in delta per vol-point; charm in delta per day; vomma in $ per vol-point.
**Typical range:** book-size dependent; for a one-to-five-position retail book,
net delta within ±a few hundred share-equivalents, vega within ±few hundred $.
**How to read it:** net vega = −$180 means the book loses ~$180 per 1-point
rise in implied vol (before convexity). The persona's framing: state it as a
scenario — "VIX 18 → 35, which happened in 2018 and 2020, is a $3,060 move."
**Green flag:** magnitudes you can restate as a survivable dollar loss under a
named scenario; no concentration flags.
**Red flag:** any cross-Greek concentration flag (see below); a "hedged" book
whose delta is small but whose vanna is large — the 2014 war story: delta-
neutral now, long delta in a vol spike, "exactly backwards."
**Depends on:** live yfinance quotes (delayed); per-position IV quality.
**Limitation to know:** point-in-time and unbucketed. Net vega ≈ 0 can hide
short front-month / long back-month vega that behaves violently in a front-end
vol spike. Bucketed Greeks are a documented gap.

---

**Output name:** Concentration flags (`concentration_flags`)
**What it represents:** Automatic warnings when net vanna, charm, or vomma
exceed thresholds — the Greeks "most risk frameworks ignore" (persona) that
matter precisely in tail events.
**Unit/format:** list of strings, empty when clean.
**How to read it:** "VANNA CONCENTRATION: 0.45 delta/vol-pt" = a 10-point vol
spike shifts the book's delta by ~4.5 share-equivalents per contract-lot —
your delta hedge degrades as vol rises.
**Green flag:** empty list.
**Red flag:** any entry, *especially* alongside a position someone described
as "hedged" — that word is only meaningful with cross-Greeks analyzed.
**Limitation to know:** thresholds are `GreeksTool` constants calibrated for
single-position review, not portfolio scale; expect recalibration as the book
grows.

---

**Output name:** Limit checks (`checks`, `breaches`, `ok`)
**What it represents:** Where the book stands against the negotiated limits:
net delta / NAV, net vega / NAV, single-position notional / NAV, plus the
declared-but-not-evaluated drawdown check.
**Unit/format:** per-check {value, limit, utilization 0–1+, breached}; flat
breach strings; `ok` boolean.
**Typical range:** utilization < 0.5 in normal operation; between 0.5 and 1.0
is the persona's "within limits, flagging anyway" zone.
**How to read it:** net_delta utilization 0.85 = at 85% of the delta budget.
The persona's rule: every conversation ends with "what is the limit and are we
within it" — utilization is that number.
**Green flag:** ok=true with headroom; utilization stable day over day.
**Red flag:** repeated approaches to the same limit without a recalibration
discussion (persona red-flag list); any breach — breaches are banners now and
Phase 6 alerts later.
**Depends on:** `JordanParams.nav` being truthful. NAV is a manually-set
registry value; if it drifts from reality every %-of-NAV limit is silently
wrong.
**Limitation to know:** the drawdown entry always reads `breached: false` —
it is *not evaluated* until a NAV history exists (Phase 6). Do not read its
green as information; read its note.

---

**Output name:** Stress results (`scenarios{}`, `worst_case`)
**What it represents:** Portfolio P&L if a named historical episode's endpoint
shock (spot % move + ABSOLUTE vol-point move) hit the current book — the
scenario-based risk measure Artzner et al. prove coherent, in place of the VaR
they prove is not (VaR fails subadditivity: it can penalize the diversification
it should reward).
**Unit/format:** dollars per scenario, flat-shift and skew-amplified (downside
puts get extra vol per the skew-amplification rule); per-position contributions.
**How to read it:** covid_2020 pnl_skew_amplified = −$1,900 means replaying
March 2020's endpoint against today's book costs ~$1,900. Persona framing: is
that a hurt or a kill against current NAV? Hurt-risks get managed; kill-risks
get hard limits.
**Green flag:** worst case is a survivable, pre-categorized hurt.
**Red flag:** worst case that exceeds what the drawdown-halt parameter implies
you're willing to lose; a single position dominating contributions in every
scenario.
**Depends on:** the registry stress library's calibrations; per-position
market data quality.
**Limitation to know:** endpoint approximation with no liquidity stress — the
number assumes you can hold through the path and exit at model prices. The
persona's 2020 lesson: actual exit cost ran 5–8x the stress-test estimate.
Treat these as lower bounds in a real crisis.

---

**Output name:** Verdict intake (`actionable`, `checks[]`)
**What it represents:** Whether Priya's latest research verdict is safe to act
on *today*: exists → fresh (≤168h default) → GO → viable after production
haircut → positive regime-conditional Sharpe in the *current* regime.
**Unit/format:** boolean + per-check {name, ok, detail}; ok may be null for
"unknown" (e.g. no conditional Sharpe for this regime = treat as unvalidated).
**How to read it:** actionable=false with `regime_compatible: null` means the
strategy was never validated in today's regime — that is not a rejection of
the strategy, it is a refusal to extrapolate.
**Green flag:** all five checks explicitly true.
**Red flag:** any attempt to reason around a failed check ("the verdict is
only a week stale") — the checks encode exactly the persona's rule that
limits negotiated in calm are not renegotiated under pressure.
**Depends on:** Priya writing `regime_at_verdict` (G4-7 writer side, Phase 4
backlog) — until then the regime check leans on the conditional-Sharpe table.
**Limitation to know:** live-verified 2026-07-17 against the real April
verdict (NO_GO, 2,463h old, negative haircut Sharpe): all checks correctly
failed. The intake gates on validation quality, not on whether the strategy
fits the current book — portfolio fit is the operator's judgment with the
limits panel open.

---

**Output name:** Sizing suggestion (`units`, `notional`, `risk_dollars`, `capped_by`)
**What it represents:** Position size from stop-distance risk: risk 1% of NAV
(default) between entry and stop; cap at the single-position limit.
**Unit/format:** units floored to whole shares/contracts; dollars elsewhere.
**How to read it:** entry 100, stop 96, NAV 100k, risk 1% → risk $1,000 /
$4 stop distance = 250 units ($25k notional). If `capped_by` is set, the
single-position limit bound first — the size is the limit, not the formula.
**Green flag:** suggested notional comfortably inside the limit without the cap
engaging; risk% at or below default.
**Red flag:** consistently capped suggestions (stops too tight for the limit
structure — a sizing-philosophy mismatch worth a recalibration conversation).
**Depends on:** honest stops. The formula prices the stop being honored; gap
risk through a stop (August 2015 persona scenario) is not in it.
**Limitation to know:** this is fixed-fractional, deliberately not Kelly
(Thorp: estimate error + over-betting asymmetry make full Kelly dangerous at
small sample sizes). It also sizes stand-alone — no correlation to existing
book positions is considered.

---

**Output name:** RCS weekly activity (`trades_opened/closed/active`, `reviews_completed`, `observations_captured`, `theses_updated`)
**What it represents:** Journal discipline counts over a window — the process
metrics for Alex's weekly review (is the operator journaling, reviewing,
capturing?).
**Unit/format:** non-negative integers; `null` means the underlying query
failed (schema drift), *not* zero.
**Green flag:** all integers (zeros included — an empty week is data).
**Red flag:** any `null` — that is a schema-contract break between this repo
and RCS and should be fixed in the bridge, as happened with
`reviews_completed` on 2026-07-17.
**Limitation to know:** counts, not quality. Five rushed reviews count the
same as five honest ones; Elena's domain, not Jordan's.

---

## VALIDATION REQUIREMENTS & LIVE-SMOKE RECORD

1. **Synthetic suite** — `venv/bin/python scripts/verify_jordan.py`: 21/21 as
   of 2026-07-17 (sizing math, limit breach detection, intake gating incl.
   G4-7 regime cases, read-only rejection, book assembly from bridge shapes).
2. **Live RCS smoke (2026-07-17, real `research.db`)** — bridge available;
   `fetch_active_trades()` returned 0 (true state: the journal has no trades
   yet — all RCS tables empty, so shapes were validated by query success, not
   by data); write attempt on the live `mode=ro` connection rejected by the
   driver; `load_book()` and all six `/api/jordan/*` endpoints returned clean
   live responses. **Two live-only defects found and fixed:**
   - `weekly_activity.reviews_completed` queried a nonexistent
     `review.created_at` → now counts on `closed_at` (verified against RCS
     `schema.sql` line 319).
   - `verdict_intake._age_hours` crashed on the real verdict's tz-aware
     timestamp (naive/aware subtraction) and reported "unparseable" → now
     handles both; the real verdict correctly reports 2,463h old.
3. **Still requires data to validate:** the full trade→book loop (create an
   RCS trade, confirm it appears with correct legs/direction/greeks — blocked
   only on the user journaling a first trade); the drawdown check (needs the
   Phase 6 NAV series — until then its green is a placeholder, see Output
   Literacy); liquidity limits (need bid/ask-quality data, U4.1).

## OPEN GAPS, RANKED

1. **Drawdown tiers have no substrate** until NAV history exists (Phase 6
   weekly review). Highest-value close: persist a daily NAV/P&L row from the
   analyzed book, then evaluate alert/halt and the persona's velocity rules.
2. **Regime-contingent limits** — Marcus's regime is on disk but limits are
   static; the persona treats transition-triggered tightening as core.
3. **Bucketed + stress Greeks** (persona aggregation Levels 4–5) — net
   numbers hide term-bucket and strike concentrations.
4. **Liquidity checks** (`min_liquidity_days` unenforced) — gated on paid
   bid/ask data; keep deferred while research/paper-only.
5. **Correlation matrices / crowding signals** — becomes material when the
   book holds multiple concurrent strategies.
