# Workflow — Pre-Trade Analysis

*From "I have a view" to a journaled, structured decision — without the
system ever telling you a direction.*

## 0. Context gate (30 seconds)

Command Deck: regime fresh? fragility? If FRAGILE/BREAKING, the right
pre-trade analysis is usually on the existing book, not a new position.

## 1. Frame the thesis (you, then the RCS)

Write it in the journal first — RCS thesis with narrative, win condition,
kill conditions. The system's inputs mirror that discipline: expected move
(unsigned magnitude), horizon in days, catalyst type, max loss budget.

## 2. What is the market pricing? (Sarah page)

- **Vol level**: IV + IV rank (with its confidence chip). Buying options at
  IVR 0.85 means paying near the year's richest premium — your move must
  outrun it.
- **VRP**: `significantly_elevated` favors structures that sell some premium;
  `inverted` says realized has been beating implied — dangerous to be short.
- **Term structure**: does your thesis tenor sit on a cheap or expensive part
  of the curve? A hump at your expiry = event premium you'll pay.
- **Skew**: negative RR = puts rich; directional-down theses pay the
  insurance premium, put-spread structures harvest part of it back.

## 3. Price the position (Greeks tool)

Enter ticker/type/strike/expiry/contracts/side → the seven-greek
interpretation: share-equivalent delta, theta bleed per day at your DTE,
vega per vol point, and the vanna/charm warnings (how your delta drifts if
vol or time move against you). Watch the **IV source** line — `fallback_18pct`
means chain and history both failed: don't trust the magnitudes.

## 4. Stress it (Scenario lab)

- **P&L grid**: the two dimensions that kill option trades — spot × IV — at
  four points in the trade's life. Look at *your* scenario cell AND the
  adjacent ones (small-wrong-move + vol crush).
- **Stress table**: the six historical shocks, flat and skew-amplified.
  Would March-2020 on this position exceed your max loss budget?
- **Kill scenario**: spot flat, IV −8vpts by day 30 (parameters). If the
  kill loss > your `max_loss_budget`, the structure or size is wrong —
  this is the single most common pre-trade fail.

## 5. Compare structures / memo (Stage 4)

Until the Phase 3 memo GUI, run it from Python:

```python
from systems.sarah.pretrade_dashboard import TradeThesisInput, generate_memo
memo = generate_memo(TradeThesisInput(ticker="SPY", expected_move=0.06,
                                      thesis_days=45,
                                      catalyst_type="macro_catalyst",
                                      max_loss_budget=600.0), signals)
```
→ five panels + structure comparison (entry cost, P&L at ±move,
break-evens) + `pretrade_memo.json`.

## 6. Size it (Jordan) and decide (you)

Jordan page → sizing form (entry/stop) → suggestion within NAV/limits.
Then the human steps: journal the setup+decision in the RCS (TAKEN or
PASSED **with the reason** — passed-trade reasoning is half the learning
loop), execute at the broker if taken, journal the fill. It appears in
Jordan's book automatically.

## Anti-patterns this workflow exists to prevent

Entering without a kill-loss number · buying rich IV for a slow thesis ·
ignoring the term-structure hump at your expiry · sizing from conviction
instead of stop-distance · unjournaled passes.
