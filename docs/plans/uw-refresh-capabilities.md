# UW Live Refresh — Capabilities Analysis (21-Day Window)

Status: **analysis** (companion to `docs/plans/uw-iv-backfill.md`)
Date: 2026-08-02
Scope: what a market-wide daily IV refresh (~7K names/day via UW API, Phase 3 of the
backfill plan) enables for analysis and trade selection. Grounded in the Sarah vol
analysis v1 specs (`B-trading-system/Sarah vol/vol analysis v1`), the Priya backtest
specs, and the option/risk distillations (`B-trading-system/Research/Distillations`).

## Framing

The 2-year backfill gives **history**; the live refresh gives **currency** — today's
cross-sectional state for ~7K names, plus 21 accruing daily observation points.
Most of what follows is either impossible today (universe = 5 ETFs + VIX) or
explicitly named as a gap in the existing specs.

---

## A. Daily cross-sectional screens — Sarah becomes a market radar

1. **IVR league table** — all ~7K names ranked by IVR/IVP with 1d/5d/21d changes.
   Makes Natenberg's sizing rule executable: "if the distance from current vol to
   breakeven is large *and the current level is rare historically*, size more
   aggressively" (Natenberg §5.1, Ch. 13 p. 240). "Rare historically" is an IVR
   screen: names at IVR > 95 or < 5 become mean-reversion candidates.
2. **IVR momentum / zone crossings** — names crossing into expensive (IVR > 80)
   or cheap (< 20) zones; 5d IVR deltas. This is the scan version of Stage 1
   Comparison Mode ("is this name's vol moving with the index or diverging?"):
   names diverging from sector/index IV = idiosyncratic risk pricing — the
   diagnostically interesting case.
3. **VRP screens (IV − RV)** — widest positive spreads → premium-selling candidates;
   negative → long-premium / cheap-hedge candidates. `backward_vrp_proxy` exists;
   the refresh makes it cross-sectional. Hull's GARCH(1,1) is the RV forecast side
   (Hull §7.3). Tenor-aware: a 1-point IV move in a front-month is ~9× the signal
   of a back-month (Hull §7.3, Ch. 23 pp. 533–534).
4. **Term-structure shape screens** — names in backwardation (front > back — the
   stress signature, Hull §6.1), steep contango (macro-premium names), plus
   day-over-day shape changes. Slope is only meaningful "when short-dated
   volatilities are historically low" (Hull §6.1) — slope percentile vs 2y history
   is now computable (Stage 1 context layer).
5. **Skew screens** (once Phase 2 surface data lands) — richest 25Δ RR names =
   put premium = tail-hedge hunting; skew percentile vs 52-week range ("tail
   steepness", Stage 1). Skew is the market's daily tail-probability series per
   name (Hull §6.3).

## B. Event intelligence — the single-name universe's missing piece

The old architecture deferred single names until "event vol handling is explicitly
designed." The refresh changes that:

6. **Expected-move series** — the 1-DTE ATM straddle *is* the market's event-move
   estimate (Natenberg §6.1: the 100/1-day straddle gaps 0.63 → 5.00 on a 5% move).
   For every earnings date in the window: pre-event IV elevation (Stage 4 Panel 2's
   "event premium flag > 2 vpts" is already specced), expected move, and post-event
   IV crush — quantified as the falling-vol path costing ~43% vs Black-Scholes at
   identical terminal vol (Natenberg §6.1 Assumption 3).
7. **Earnings-season screens** — names whose IVR spikes 5–10 days pre-earnings
   (event premium buildup) vs names where the post-event crush leaves IVR at
   historical lows (buy-compression-after-event setup, with IVR context).

## C. Regime signals for Marcus + Stage 5

8. **Market-wide IVR breadth** — % of names with IVR > 80 vs < 20, daily. A
   vol-breadth oscillator richer than the VIX level Marcus currently consumes.
   Breadth flips are regime transitions in disguise — the cross-sectional
   generalization of the Stage 5 Pre-Transition Monitor (VVIX/VIX ratio extended
   to "how many names are accelerating").
9. **Dispersion statistics** — cross-sectional IVR dispersion and index-IV vs
   sector-IV gaps. The Sarah persona names the dispersion strategy line explicitly;
   it currently has no data substrate. Also feeds Jordan: dispersion is the
   correlation input for portfolio-level Kelly (`F* = C⁻¹[M − R]`, Thorp §5).
10. **Funding-stress early warning** — B&P: margins scale with volatility (B&P
    Claim 4) → the market-wide IV feed is a leading indicator of margin
    escalation, a structural-fragility flag (B&P §12 regime flag), not just a P&L
    input.

## D. Trade selection and sizing that becomes computable

11. **Natenberg entry/sizing algorithm** — breakeven vol = current IV + edge/vega;
    margin-for-error < 3 pts → minimum size; > 7 pts and historically rare →
    aggressive (Natenberg §5.1). Every candidate now has the IVR/IVP to fire it.
12. **Kelly with real inputs** — per-name vol → covariance matrix → fractional
    Kelly with drawdown math (Thorp §5–7); per-name long-run vol levels (GARCH
    V_L) for mean-reversion forecasts. Jordan goes from "vega limit per 1% IV
    move" (Hull, Business Snapshot 19.1) to vol-conditional limits — the nonlinear
    scaling B&P insists on (B&P §5).
13. **RCS intake enrichment** — any thesis/idea in RCS instantly gets its full IV
    context: IVR, IVP, TS shape, skew, VRP, expected move. The Stage 4 pre-trade
    memo (JSON-exported for trade log ingestion) becomes data-complete for **any**
    name — the AAOI problem solved for every future trade.
14. **Trade journal feedback loop** — 21 days of trades + 21 days of market-wide
    vol_signals = the first honest "did I enter at high IVR / rich skew?"
    statistics on actual RCS trade history. Priya's VRP/IVR/skew signal modules
    (explicitly "carry forward" per the backtest spec) get their first real
    cross-sectional dataset.

## E. What compounds during the 21 days

15. **Matched-maturity VRP activates** — U1.3 upgrade "activates automatically from
    accumulated data." Each refresh day seeds the start-of-window IV; after ~30
    days the first forward VRP samples are complete; the machinery goes live now.
16. **Vol cones (U1.1)** fill with 21 more days of per-name RV/IV — "the vol cone
    context is more important for trade decisions than a GARCH point forecast."
17. **Daily cross-sectional snapshots** — 21 snapshots of market-wide IV state
    become "current regime" context for the Stage 5 analog search (each day adds
    ~7K candidate rows to the analog library).

## F. Honest limits

- 21 days is **operationalization time, not validation time** — build, calibrate
  thresholds, iterate while data accrues; no edge gets proven in 21 days.
- EOD only — no intraday (yfinance/Polygon remains the intraday layer).
- Screens need UI real estate (pretrade_dashboard + CommandDeck can host them).

## Build order (highest ROI during the window)

1. IVR league table + zone crossings — Phase 1 data only
2. Event-premium screen (earnings-driven) — Phase 1 data only
3. Market-wide IVR breadth for Marcus — Phase 1 data only
4. RCS intake enrichment — trade-context report pattern
5. Natenberg sizing check in the pretrade panel — needs breakeven computation

## Source references

- Sarah vol analysis v1 (Stages 1–5, upgrade path U1.1/U1.3):
  `/Users/jun/Nextcloud/Claude/B-trading-system/Sarah vol/vol analysis v1/`
- Priya backtest v1: `/Users/jun/Nextcloud/Claude/B-trading-system/priya backtest/v1/`
- Distillations: `/Users/jun/Nextcloud/Claude/B-trading-system/Research/Distillations/`
  (natenberg_extraction_jordan.md, hull_extraction_jordan_risk.md,
  thorp_kelly_extraction.md, bp2009_extraction_jordan.md)
