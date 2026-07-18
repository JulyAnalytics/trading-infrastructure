# Parameter Schemas — every registry field

Source of truth: `systems/params/models.py` (defaults mirror v0.5 exactly;
seeded as version 1 on first use). **G** = guarded research gate;
**R** = triggers a recompute suggestion. Bounds are enforced on save.
Legacy config-name mapping: `systems/params/compat.py`.

## marcus

| Field | Default | Bounds | Notes |
|---|---|---|---|
| component_weights | vol .25 · credit .25 · curve .20 · inflation .10 · labor .15 · positioning .05 | must sum to 1.0, exact key set | **R**: backfill_regime_history |
| regime_thresholds.vix | low 15 · medium 20 · high 25 · crisis 35 | | **R** |
| regime_thresholds.hy_spread | tight 300 · normal 450 · wide 600 · crisis 900 (bps) | | **R** |
| regime_thresholds.yield_curve_10_2 | inverted −10 · flat 50 · normal 100 · steep 200 (bps) | | **R** |
| regime_thresholds.unemployment_delta | improving −0.3 · stable 0.2 · deteriorating 0.5 (pp/3m) | | **R** |
| regime_thresholds.breakeven_10y | anchored 2.0 · elevated 2.5 · unanchored 3.0 (%) | | **R** |
| score_to_regime | +0.60 → RISK_ON_LOW_VOL · +0.25 → RISK_ON_ELEVATED_VOL · −0.10 → NEUTRAL · −0.40 → CAUTION · −0.65 → RISK_OFF_STRESS · −2.00 → CRISIS | strictly descending | **R** |
| divergence_threshold_vc / _vl | 0.6 / 0.7 | 0.1–2.0 | vol-credit / vol-labor spreads; **R** |
| divergence_min_credit_stress | 0.1 | −1–1 | credit gate for LABOR_LAG_WARNING |
| broad_divergence_spread | 1.2 | 0.5–2.0 | max−min component spread flag |
| confidence_high_agreement / _medium_ | 0.8 / 0.6 | ≤ ordering enforced | share of components agreeing |
| staleness_thresholds_days | vol/credit/curve/inflation 3 · labor/positioning 10 | | per-component data-age flags |
| unemployment_stale_days | 45 | 7–120 | |

## sarah

| Field | Default | Bounds | Notes |
|---|---|---|---|
| vol_tickers | SPY QQQ IWM XLE GLD | non-empty | daily-run universe |
| fred_risk_free_series / risk_free_fallback | DGS3MO / 0.045 | fallback 0–0.15 | |
| vol_ivr_min_history_days | 60 | 20–756 | IVR/IVP confidence floor |
| analog_min_history_days | 120 | 30–756 | analog-search warning floor |
| vvix_confidence_min_days | 504 | 60–1260 | VVIX joins the feature vector after ~2y |
| regime_staleness_hours | 80 | 12–168 | max age of regime_state.json the daily vol run accepts; 80h covers the Friday→Monday weekend cycle |
| catalyst_types | macro_slow · macro_catalyst · event_specific · technical | | TradeThesisInput enum |
| max_flow_notes_length | 200 | 50–2000 | |
| grid_spot_range_pct / _step_pct | 0.30 / 0.025 | step < range | scenario grid geometry |
| grid_iv_range_vpts / _step_vpts | 25 / 1 | 5–100 / 0.25–10 | |
| grid_time_checkpoints | 0 · .25 · .50 · .75 | | fractions of DTE elapsed |
| grid_spot_range_highvol / grid_iv_range_highvol | 0.40 / 35 | | widened grid |
| highvol_vix_threshold | 25 | 15–60 | switches to the wide grid |
| stress_scenarios | the six-event library (2018 Q4 −20%/+24vpts · Mar-2020 −34%/+62 · Aug-2015 −11%/+22 · Volmageddon −4%/+20 · 2022 rates −25%/+15 · 2011 euro −19%/+22) | each needs label/spot_shock/vol_shock_vpts | **user-editable library**; vol shocks are ABSOLUTE vpts |
| kill_iv_compression_vpts / kill_days_elapsed | 8 / 30 | 1–40 / 1–365 | kill-scenario assumptions |
| breakeven_search_range / _step | 0.35 / 0.001 | | structure break-even grid search |

## priya

| Field | Default | Bounds | Notes |
|---|---|---|---|
| backtest_min_observations / _min_options_obs | 252 / 126 | | data-audit floors |
| spread_floor_{otm,atm,itm}_{short,long} | .12/.08 · .06/.04 · .05/.037 | | Hilpisch empirical option-spread floors |
| backtest_default_significance | 0.05 | 0.001–0.20 | **G** |
| backtest_pbo_reject_threshold | 0.05 | 0.01–0.50 | **G** — gate: PBO above fails |
| backtest_dsr_accept_threshold | 0.95 | 0.50–0.999 | **G** — gate: DSR below fails |
| backtest_production_haircut | 0.50 | 0.1–1.0 | **G** — OOS→production Sharpe assumption |
| backtest_min_viable_haircut_sr | 0.5 | 0–3 | **G** |
| backtest_regime_staleness_hours | 80 | 12–168 | research runs' regime gate (weekend-tolerant) |
| cpcv_default_n_groups / _k_test / _pct_embargo | 6 / 2 / 0.01 | k < N enforced | 6C2 → 5 paths |
| mc_default_n_paths | 1000 | 100–100k | options Monte Carlo |
| sharpe_autocorr_pvalue_threshold | 0.05 | | Ljung-Box gate for η(q) annualization |
| sharpe_newey_west_lags | [3, 6] | | dual truncation lags |
| vol_cone_windows / _percentiles | [20 40 60 120 240] / [5 25 50 75 95] | | |
| fracdiff_d_range / _d_step / _weight_threshold | [0,1] / 0.05 / 1e-5 | | |
| triple_barrier_pt/_sl_multiplier · _ewma_span | 1.0 / 1.0 / 100 | 0.1–10 / 10–1000 | barrier widths ×vol |
| backtest_overfitting_sharpe_cv_threshold | 0.5 | 0.1–3.0 | sweep-instability warning |
| backtest_sweep_min_points | 10 | 3–1000 | |

## jordan

| Field | Default | Bounds | Notes |
|---|---|---|---|
| nav | 100,000 | 1k–1e9 | the denominator for all %-of-NAV limits — **set this to your real number** |
| max_net_delta_pct | 0.20 | 0.01–2.0 | |net delta $| / NAV |
| max_net_vega_pct | 0.15 | 0.01–2.0 | |net vega $/vpt| / NAV |
| max_single_position_pct | 0.05 | 0.005–1.0 | notional / NAV; also caps the sizer |
| drawdown_alert_pct / drawdown_halt_pct | 0.08 / 0.15 | alert < halt | declared; evaluated from Phase 6 NAV history |
| min_liquidity_days | 5 | 1–60 | declared; needs volume data |
| default_risk_pct_per_trade | 0.01 | 0.001–0.05 | sizer default |
| verdict_max_age_hours | 168 | 1–2160 | intake freshness gate |

## ops

| Field | Default | Notes |
|---|---|---|
| daily_pipeline_time / vol_run_time / snapshot_time | 18:05 / 08:00 / 18:15 | weekdays (HH:MM validated) |
| weekly_refresh_time / calendar_fetch_time | 20:00 / 20:05 | Sundays |
| regime_staleness_hours_production | 12 | CLAUDE.md Rule 4 |
| job_max_retries / job_retry_wait_seconds | 2 / 120 | scheduler v2 policy |

## data

| Field | Default | Notes |
|---|---|---|
| fomc_schedule | eight 2026 dates | manual yearly update |
| cftc_instruments | SP500 NASDAQ EURUSD GOLD WTI BONDS_10Y | COT universe |
| dashboard_refresh_seconds | 3600 | |
| macro_series_disabled | [] | ingest skip-list (feed enforcement: Phase 6) |
