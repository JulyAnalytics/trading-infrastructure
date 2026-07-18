# Glossary

Plain-language definitions for every term the system uses. Deeper "how to
read this number" guidance lives in the audit docs
(`docs/audit/01–04`, the *Output Literacy* sections).

## Regimes (Marcus)

| Term | Meaning |
|---|---|
| **Regime** | A six-state label for the macro environment, from `RISK_ON_LOW_VOL` (best for holding risk) through `NEUTRAL`, `CAUTION`, to `RISK_OFF_STRESS` and `CRISIS` (2008/2020-type stress). Descriptive of *now*, not predictive. |
| **Composite score** | Weighted average of the six component scores, −1…+1. Mapped to the regime label via `score_to_regime` thresholds. |
| **Component score** | Per-dimension −1…+1 reading: vol (VIX), credit (HY spreads), curve (10Y−2Y), inflation (breakevens/real rates/PCE), labor (unemployment/claims), positioning (CFTC COT, contrarian). |
| **Confidence** | HIGH/MEDIUM/LOW — how many of the five fundamental components agree in sign. A count of agreement, not signal strength. |
| **Divergence** | Two components telling contradictory stories. `LEADING_STRESS_WARNING` (credit stressed, vol calm — historically precedes vol spikes) is the actionable one; also `ELEVATED_VOL_UNCONFIRMED`, `LABOR_LAG_WARNING`, `BROAD_COMPONENT_DIVERGENCE`. |
| **Fragility** | v1.0 headline (STABLE/WATCH/FRAGILE/BREAKING): is the current regime stable or cracking? Combines divergences, 30d transition probability, and 7-day score momentum. |
| **Transition probability** | Heuristic ~30-day probability of the regime label changing (capped at 85%). Attention-allocation tool, not a calibrated forecast. |
| **State vector** | The six scores kept as a vector (never collapsed), plus sub-composites: financial conditions (vol+credit), real economy (labor+curve), nominal (inflation). |
| **Analogues / nearest neighbours** | Past dates whose six-score vector was closest (Euclidean) to today's, excluding the trailing year. "When did the macro look like this before?" |
| **Z-score (z_1y / z_5y)** | How many standard deviations a series sits from its rolling 1y/5y mean. ±3 is extreme; beyond ±4 usually means a data error. |

## Vol & options (Sarah)

| Term | Meaning |
|---|---|
| **IV (implied volatility)** | The annualized move the options market is pricing. `atm_iv_30d` = at-the-money, ~30 days out — the headline vol number per ticker. |
| **RV (realized vol)** | What the underlying actually moved (21-day annualized std dev). |
| **VRP (vol risk premium)** | IV minus RV — what option sellers are being paid over recent actual movement. Positive ~+1–6 vpts is normal; `inverted` means the market moved more than options priced (dangerous for sellers). Backward-looking proxy: 30d IV vs 21d past RV, a known tenor mismatch. |
| **IV Rank (IVR)** | Where today's IV sits in its 1-year min–max range (0–1). Spike-sensitive. |
| **IV Percentile (IVP)** | Fraction of past days with lower IV than today. More robust than IVR after spike years. Both need ~252 days of history — check `ivr_ivp_confidence`. |
| **Skew / 25Δ risk reversal** | 25-delta put IV minus call IV. Negative for equities (puts bid = insurance demand). `skew_1025_ratio` measures how steep the far tail is. |
| **Term structure (contango/backwardation)** | IV by expiry. Contango (far > near) is normal; backwardation (near > far) = near-term panic or event premium. Shapes: steep/mild contango, flat, humped, inverted, full backwardation. |
| **Greeks** | Sensitivities of an option's price: **delta** (per $1 spot), **gamma** (delta's change), **theta** (per day), **vega** (per vol point), plus second-order **vanna** (delta per vol), **charm** (delta per day), **vomma** (vega per vol). |
| **Kill scenario** | Max *realistic* loss for a long: spot goes nowhere and IV compresses (default 8 vpts by day 30 — a registry parameter). |
| **Stress scenario** | Named historical shock (2018 Q4, March 2020, Volmageddon…) applied as endpoint spot/vol shocks. Vol shocks are ABSOLUTE vol points, never percentages. Skew-amplified variant bumps OTM put IV harder, matching empirics. |
| **BL density** | Breeden-Litzenberger risk-neutral probability distribution extracted from the option chain. |
| **VVIX** | Vol-of-vol. VVIX elevated while VIX is calm = the pre-transition warning pattern. |

## Research statistics (Priya)

| Term | Meaning |
|---|---|
| **Hypothesis registry** | Write the idea down (and count every trial) *before* touching data — the anti-data-snooping gate. |
| **Triple-barrier label** | Trade outcome label: profit-target / stop / time-limit, whichever hits first, barriers scaled by volatility. |
| **Purged K-Fold / embargo** | Cross-validation that removes training samples whose label windows overlap the test period (no peeking), plus a buffer after each fold. |
| **CPCV** | Combinatorial Purged CV — many train/test paths instead of one, giving a *distribution* of Sharpes rather than a single lucky number. |
| **PBO** | Probability of Backtest Overfitting — chance that picking the in-sample winner gives below-median out-of-sample results. Gate: < 0.05. Diagnostic, never an optimization target. |
| **PSR / DSR** | Probabilistic & Deflated Sharpe Ratio — probability the Sharpe is real after non-normality (PSR) and multiple-testing (DSR, penalized by trial count). Gate: DSR > 0.95. |
| **Production haircut** | Assume only 50% of OOS Sharpe survives to live trading; the haircut Sharpe must still clear 0.5. Both are `guarded` registry parameters. |
| **Degradation ratio** | IS Sharpe ÷ OOS Sharpe. 1–2.5 normal, >3 suspicious. |
| **Implementation shortfall** | Gross P&L vs total execution cost; ratio must clear 2× or the edge dies in fees. |
| **GO / NO_GO verdict** | The final output of the 13-gate pipeline, written to `research_verdict.json` for Jordan. |

## Risk (Jordan)

| Term | Meaning |
|---|---|
| **Book** | All open positions: RCS journal trades (auto-imported) + manual entries. |
| **Net delta dollars** | Portfolio share-equivalent delta × spot — headline directional exposure, limit-checked as % of NAV. |
| **Verdict intake** | The checklist a GO verdict must pass *now* (fresh, viable, regime-compatible) before sizing — the freshness/regime rot guard (audit gap G4-7). |
| **Sizing formula** | units = (NAV × risk%) ÷ |entry − stop|, capped by the single-position limit. |

## Platform

| Term | Meaning |
|---|---|
| **Parameter registry** | Versioned store of every tunable; see [parameter-registry.md](../02-platform/parameter-registry.md). |
| **Param hash** | 12-hex fingerprint of a component's active parameter payload; stamped on every run. |
| **Guarded field** | A research-gate parameter (DSR/PBO/haircut…) — editable but loudly logged, and outputs carry the version that produced them. |
| **Job** | One pipeline run, executed in a fresh subprocess, tracked in `trading.db:jobs`. |
| **Output contract** | A locked JSON schema in `data/outputs/` that downstream components rely on (CLAUDE.md Rule 5). |
