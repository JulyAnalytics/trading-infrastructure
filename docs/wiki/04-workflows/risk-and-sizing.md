# Workflow — Risk, Sizing & the Journal Loop

*How a validated edge (or a discretionary thesis) becomes a sized position,
and how the book stays watched. Kai is v1.1 — execution is manual by design.*

## A. Sizing a validated strategy (Priya → Jordan)

1. **Jordan page → Verdict intake.** Five checks, all must pass:
   verdict exists → fresh (≤ `verdict_max_age_hours`) → `GO` →
   viable after haircut → **regime-compatible** (positive regime-conditional
   Sharpe for *today's* regime; "no data for this regime" = fail-safe not
   actionable). A GO that was valid in RISK_ON does not survive a flip to
   RISK_OFF — this re-check at decision time is the point.
2. **Sizer.** Entry + stop (+ optional risk% override) →
   units = (NAV × risk%) ÷ |entry − stop|, capped by the single-position
   limit. NAV and every limit are registry parameters — keep NAV current.
3. **Sanity vs the book.** Analyze book first: would this position push net
   delta/vega utilization near 100%? Concentration flags already firing?

## B. Sizing a discretionary options thesis

Same sizer, but the "stop" for premium structures is the kill-scenario
loss: run [pre-trade analysis](pre-trade-analysis.md), take
`max_realistic_loss` per contract, and size so contracts × kill-loss ≤
NAV × risk%.

## C. Execute and journal (the human steps)

1. Journal the decision in the **RCS** (:8099): setup → decision
   (TAKEN/PASSED with reason) → trade (idea).
2. Execute at the broker.
3. Activate the RCS trade with the fill: entries, option legs
   (direction/type/strike/expiry/contracts/premium), greeks/IV meta.
4. **It now appears in Jordan's book automatically** (read-only bridge) —
   no double entry. Anything not journaled goes in as a manual position
   (second-best; prefer the journal).

## D. Watching the book

- Daily (part of the [morning routine](morning-routine.md)): *Analyze book*
  → breach banner → utilization table → pricing-error list.
- On regime WATCH/FRAGILE days: *Analyze + stress* — the six-shock table
  with per-position contributions and the worst-case chip. The stress
  library is registry data; add the scenario you're actually worried about.
- Limit breach fires the red banner (and, from Phase 6, a notification).
  The response is a decision, not an automation: trim, hedge, or —
  consciously, with a note — raise the limit in the registry (versioned,
  visible, reviewable).

## E. Close the loop

Exit → journal the exit in the RCS → position leaves Jordan's book →
complete the RCS review (phase 1 → zone 3 → phase 2, mistake taxonomy).
The Phase 6 weekly review will aggregate both sides: regime week, research
runs, risk flags, journal activity.

## What Jordan will not do

Place orders (v1.1) · evaluate drawdown limits (needs NAV history — Phase 6)
· trust a verdict without re-checking it · write to the journal (ever).
