# Weekly Review — week ending 2026-07-24
*Generated 2026-07-24T17:01:03 · parameter hashes: marcus:165ba8, sarah:394625, priya:e1cd0e, jordan:b9c3b3, ops:8b3f4c, data:c8739f*

## Regime week (Marcus)
Current: **RISK_ON_ELEVATED_VOL** (composite 0.265, confidence MEDIUM, as of 2026-07-23)
Divergence flagged: BROAD_COMPONENT_DIVERGENCE

| date | regime | composite |
|---|---|---|
| 2026-07-17 | RISK_ON_ELEVATED_VOL | 0.265 |
| 2026-07-18 | RISK_ON_ELEVATED_VOL | 0.265 |
| 2026-07-20 | RISK_ON_ELEVATED_VOL | 0.265 |
| 2026-07-21 | RISK_ON_ELEVATED_VOL | 0.265 |
| 2026-07-22 | RISK_ON_ELEVATED_VOL | 0.265 |
| 2026-07-23 | RISK_ON_ELEVATED_VOL | 0.265 |

## Vol summary (Sarah)
VVIX 97.6 (VVIX/VIX ratio 5.5 — typical 3.5–6.0) as of 2026-07-24.

| ticker | ATM IV 30d | IV rank | VRP signal | TS shape | 25Δ RR |
|---|---|---|---|---|---|
| GLD | 21.9 | -0.13 | near_parity | mixed | -0.73 |
| IWM | 19.4 | 0.33 | significantly_elevated | mixed | -2.88 |
| QQQ | 24.5 | 0.32 | near_parity | mixed | -5.59 |
| SPY | 14.1 | 0.33 | moderately_elevated | mixed | -2.75 |
| XLE | 28.7 | 0.5 | significantly_elevated | full_backwardation | -0.39 |

## Research runs (Priya / MLflow)
3 run(s) this week — 0 GO, 3 NO_GO (failure archive).

| run | verdict | DSR | prod SR | logged |
|---|---|---|---|---|
| verify_priya_synthetic | NO_GO | 0.66 | 0.33 | 2026-07-18T19:30 |
| verify_priya_integration | NO_GO | 0.298 | -0.0 | 2026-07-18T05:10 |
| verify_priya_synthetic | NO_GO | 0.66 | 0.33 | 2026-07-18T05:10 |

## Risk flags (Jordan)
3 alert(s) in the window.
Book: 0 RCS + 0 manual position(s); RCS bridge available=True. Drawdown check still awaits a NAV history (see audit #5).

| when | source | severity | message |
|---|---|---|---|
| 2026-07-18 16:52 | jobs | error | job snapshot_pdf FAILED (exit code 1) after 3 attempt(s) — see Jobs page |
| 2026-07-18 16:52 | jobs | error | job snapshot_pdf FAILED (exit code 1) after 3 attempt(s) — see Jobs page |
| 2026-07-18 13:27 | jobs | warning | snapshot_pdf skipped — dependency missing job deadbeef0000 |

## Journal activity (RCS)
Trades opened 0, closed 0, active now 0. Reviews completed 0, observations 0, theses updated 0.
