---
domain: trading-system
stage: wiki
project: v1-workstation
persona: sarah
status: active
---

# Workflow — Regime Context (analogs, VVIX, event history)

*The question behind every other workflow: what kind of environment is this,
and what did environments like it do next? Two layers answer it — Marcus
from macro data, Sarah's regime library from the vol surface — and they are
most useful read together.*

![Regime library](../images/sarah-regime-library.png)

## When to run this workflow

- Fragility left STABLE, or a divergence banner appeared.
- The VVIX monitor flagged, or the VVIX/VIX ratio crossed 6.
- Before sizing anything unusually large, or after any 2%+ index day.
- Whenever your narrative and the data feel out of sync — this workflow is
  the tiebreaker ritual.

## 1. Marcus's read (macro space)

Marcus page: fragility → divergences (which pair, how long, intensifying?)
→ **state vector** (which sub-composite is dragging: financial conditions,
real economy, nominal?) → **analogues** (nearest historical dates in
six-score space) → **implications** (what SPY/TLT/GLD/HYG/UUP did in this
regime historically, with reliability flags).

## 2. Sarah's read (vol-surface space)

Sarah → Regime library tab:

1. **VVIX pre-transition monitor.** The pattern that earns its keep:
   **VVIX z > 1.5 while VIX z < 0.5** — the market is uncertain about
   *volatility itself* while current vol is quiet. Historically this
   "nervous calm" precedes transitions. Confidence is `reliable` (the
   2006→present backfill backs the z-scores). Also: ratio > 6, VIX z > 2
   warnings, and the macro.db staleness caveat if the VIX feed is old.
2. **Analog search.** Today's surface as a fingerprint (vol level, IV rank,
   both term-structure slopes, skew, VIX z, VVIX z) → most similar
   historical days, with macro-compatibility filters. Honest by design:
   with a young library it says exactly how thin the searchable pool is.
   For each analog worth taking seriously, *you* look up what happened next
   — the system deliberately does not compute forward returns for you
   (that's a research question for Priya, not a lookup).
3. **Event browser.** The named episodes (Volmageddon, COVID, Q4-2018, 2022
   rates, CNY-2015, SVB): pre-event surface state, what worked, what
   failed, lessons. Ask: *does today rhyme with any of these setups?* —
   note the match is about the **pre-event surface**, not the headline.

## 3. Cross-check the two layers

| Marcus says | Sarah says | Read |
|---|---|---|
| STABLE, no divergence | no VVIX flag, analogs benign | normal operations |
| WATCH / credit-led divergence | VVIX flag | the classic pre-spike configuration — tighten before confirmation, review the book under stress |
| STABLE | VVIX flag alone | vol markets are nervous about something macro data doesn't show yet — smaller size, wider stops, re-check daily |
| FRAGILE/BREAKING | anything | risk-review day: [book stress](risk-and-sizing.md#d-watching-the-book), not new entries |

## 4. Act on it (context → decisions)

- Position sizing multiplier: this workflow's output is usually *smaller or
  normal*, rarely "bigger".
- Structure choice: nervous-calm environments favor defined-risk structures
  and disfavor naked short gamma.
- Journal it: a one-line RCS observation ("VVIX flag + credit divergence,
  reduced size intent") turns today's read into next quarter's evidence.

## After a real episode

Add it to the event library (Regime library → Edit library YAML) while
fresh — this library is your institutional memory, and it's the seed data
future analog searches and the
[Knowledge Library](../06-knowledge/ashurbanipal-integration.md) will draw
on.
