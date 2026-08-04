---
domain: trading-system
stage: wiki
project: v1-workstation
persona: sarah
status: active
---

# Workflow — Pre-Trade Analysis

*From "I have a view" to a journaled, structured decision — without the
system ever telling you a direction. Time cost: ~10 minutes done honestly.*

## 0. Context gate (30 seconds)

Command Deck: regime fresh? fragility? If FRAGILE/BREAKING, the right
pre-trade analysis is usually on the existing book, not a new position.
Then [Regime context](regime-context.md) if the environment itself is the
question.

## 1. Frame the thesis (you, then the RCS)

Write it in the journal first — RCS thesis with narrative, win condition,
kill conditions. The memo form's five fields mirror that discipline:
**expected move** (unsigned magnitude — how far, not which way), **horizon**
in days, **catalyst type**, **max loss budget** per contract, and optionally
a directional bias (used only to price which wing you'd pay for).

## 2. What is the market pricing? (Sarah → Vol monitor)

- **Vol level**: IV + IV rank (with its confidence chip). Buying options at
  IVR 0.85 means paying near the year's richest premium — your move must
  outrun it.
- **VRP**: `significantly_elevated` favors structures that sell some premium;
  `inverted` says realized has been beating implied — dangerous to be short.
- **Term structure**: does your thesis tenor sit on a cheap or expensive part
  of the curve? A hump at your expiry = event premium you'll pay.
- **Skew**: negative RR = puts rich; directional-down theses pay the
  insurance premium; put-spread structures harvest part of it back.
- **Vol cone**: is current IV high *relative to what this underlying
  actually realizes* across windows — the buy/sell-vol context in one chart.

## 3. Build the memo (Sarah → Pre-trade memo)

![Memo builder](../images/sarah-memo-builder.png)

1. Fill the thesis form. Click **Auto-resolve catalyst** — it looks up the
   next earnings and importance-1 macro events (FOMC/CPI/PCE/NFP) and
   pre-fills catalyst type + horizon; candidate chips let you pick a
   different event. Confirm it matches *your actual* catalyst.
2. **Build pre-trade memo** (~15–30s: it prices from the live chain).
3. Read the five panels in order:
   - **Vol level** — daily theta, monthly carry, **roll-adjusted carry**
     (the extra cost of sliding down a contango curve), break-even move,
     cost-burden verdict. If break-even ≥ your expected move, the trade is
     structurally underwater before direction even matters.
   - **Term structure** — recommended DTE *with its reasoning*; event
     premium flag at your expiry.
   - **Skew** — what your directional bias costs vs ATM.
   - **Flow** (optional) — record an unusual-activity observation; the panel
     characterizes it and pointedly does not tell you what it means.
   - **Implied distribution** — the market's own P(±5/10/15%) at your
     expiry. Compare against your thesis probability honestly: if you think
     +6% is likely and the market prices P(+5%) at 4%, you are claiming a
     big edge — say so out loud.
4. **Structure comparison** — seven candidate expressions priced live, P&L
   at ±your-move, and in-budget/over-budget chips against your max loss.

The memo persists automatically with a stable ID (`PTM-YYYYMMDD-TICKER-NNN`)
— **copy that ID into the RCS setup/trade note**. That link is what makes
the trade auditable later ("what did I know and pay when I entered?").

## 4. Position-level stress (Greeks & scenarios)

For the structure you're actually leaning toward: Greeks tool →
seven-greek interpretation (watch the **IV source** line — `fallback_18pct`
means don't trust magnitudes) → Scenario lab:
- **P&L grid**: your scenario cell AND its neighbors (small-wrong-move +
  vol crush is the common death).
- **Stress table**: would March-2020 on this position exceed your budget?
- **Kill scenario**: spot flat, IV −8vpts by day 30. **If kill-loss >
  `max_loss_budget`, the structure or the size is wrong** — the single most
  common pre-trade fail this workflow exists to catch.

## 5. Size it (Jordan) and decide (you)

[Risk & sizing](risk-and-sizing.md): sizer (entry/stop, or kill-loss as the
stop-equivalent for premium structures), sanity vs the book's current
utilization, then the human steps — journal the decision (TAKEN or PASSED
**with the reason**; passed-trade reasoning is half the learning loop),
execute at the broker, journal the fill. It appears in Jordan's book
automatically.

## Anti-patterns this workflow exists to prevent

Entering without a kill-loss number · buying rich IV for a slow thesis ·
ignoring the term-structure hump at your expiry · claiming a probability
edge you never stated · sizing from conviction instead of stop-distance ·
memos not cited in the journal · unjournaled passes.
