# Weekly Review — week ending 2026-07-18
*Generated 2026-07-18T13:28:49 · parameter hashes: marcus:165ba8, sarah:394625, priya:e1cd0e, jordan:b9c3b3, ops:8b3f4c, data:c8739f*

## Regime week (Marcus)
Current: **RISK_ON_ELEVATED_VOL** (composite 0.265, confidence MEDIUM, as of 2026-07-17)
Divergence flagged: BROAD_COMPONENT_DIVERGENCE

| date | regime | composite |
|---|---|---|
| 2026-07-17 | RISK_ON_ELEVATED_VOL | 0.265 |

## Vol summary (Sarah)
VVIX 104.9 (VVIX/VIX ratio 5.6 — typical 3.5–6.0) as of 2026-07-17.

| ticker | ATM IV 30d | IV rank | VRP signal | TS shape | 25Δ RR |
|---|---|---|---|---|---|
| GLD | 23.799999237060547 | None | near_parity | flat | -2.1700000762939453 |
| IWM | 19.799999237060547 | None | significantly_elevated | mixed | -5.46999979019165 |
| QQQ | 26.100000381469727 | None | near_parity | mixed | -6.03000020980835 |
| SPY | 15.0 | None | moderately_elevated | mixed | -4.230000019073486 |
| XLE | 29.600000381469727 | None | significantly_elevated | mixed | -4.739999771118164 |

## Research runs (Priya / MLflow)
2 run(s) this week — 0 GO, 2 NO_GO (failure archive).

| run | verdict | DSR | prod SR | logged |
|---|---|---|---|---|
| verify_priya_integration | NO_GO | 0.298 | -0.0 | 2026-07-18T05:10 |
| verify_priya_synthetic | NO_GO | 0.66 | 0.33 | 2026-07-18T05:10 |

## Risk flags (Jordan)
1 alert(s) in the window.
Book: 0 RCS + 0 manual position(s); RCS bridge available=True. Drawdown check still awaits a NAV history (see audit #5).

| when | source | severity | message |
|---|---|---|---|
| 2026-07-18 13:27 | jobs | warning | snapshot_pdf skipped — dependency missing job deadbeef0000 |

## Journal activity (RCS)
Trades opened 0, closed 0, active now 0. Reviews completed 0, observations 0, theses updated 0.
