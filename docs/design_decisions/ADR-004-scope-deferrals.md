# ADR-004 — v1.0 scope deferrals (Kai; Marcus gaps 2 & 6; paid data)

**Date:** 2026-07-06 · **Status:** accepted (user decision)

## Deferred to v1.1+
1. **Kai / IBKR execution** — v1.0 ends at Jordan (limits, sizing, planned-
   trade tickets); the user executes manually at the broker and the fill
   lands in RCS, which Jordan re-imports. Removes the IBKR Gateway
   operational dependency from v1.0.
2. **Marcus Gap 2 (regime-conditional weights)** and **Gap 6 (forward
   scenario layer)** — both require a longer validated backfill than exists;
   the improvements doc itself sequences them last. Priorities 1–5 are in
   v1.0 (`systems/signals/regime_analytics.py`).
3. **Paid data tiers** — Polygon (U4.1/U4.2), CBOE historical options EOD
   (U3.3/U5.2), OptionMetrics: purchase decisions, not builds. **U3.3/U5.2
   remain the pre-live-capital hard gate** per the Sarah upgrade paths;
   v1.0 stays a research/paper workstation on delayed data with
   `data_warning` propagation intact.

## Consequences
- Jordan's "planned trade" ticket is the v1.0 execution hand-off artifact.
- The vol data ceiling (yfinance 15–20min) is unchanged and documented on
  every affected output.
