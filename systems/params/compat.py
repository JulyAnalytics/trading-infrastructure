"""
Legacy config-name compatibility layer.

Through v0.5 every tunable lived as a module constant in root config.py.
config.py now resolves those names through this map (PEP 562 __getattr__),
so `from config import REGIME_THRESHOLDS` keeps working everywhere while the
parameter registry is the single source of truth.

Note the import-time binding caveat: `from config import X` copies the value
when the *importing* module first loads. Long-running processes therefore see
parameter edits only on restart / next fresh job process; code refactored to
call get_params() directly (regime_classifier, scenario_engine, and all new
code) sees edits live.
"""
from __future__ import annotations

import copy

# legacy_name -> (component, field, cast)
# cast restores the container type the v0.5 constant had (JSON gives lists).
LEGACY_CONFIG_MAP: "dict[str, tuple[str, str, type | None]]" = {
    # ── Marcus ──────────────────────────────────────────────────────────
    "REGIME_THRESHOLDS":            ("marcus", "regime_thresholds", None),
    "COMPONENT_WEIGHTS":            ("marcus", "component_weights", None),
    "STALENESS_THRESHOLDS_DAYS":    ("marcus", "staleness_thresholds_days", None),
    "UNEMPLOYMENT_STALE_DAYS":      ("marcus", "unemployment_stale_days", None),
    "DIVERGENCE_THRESHOLD_VC":      ("marcus", "divergence_threshold_vc", None),
    "DIVERGENCE_THRESHOLD_VL":      ("marcus", "divergence_threshold_vl", None),
    "DIVERGENCE_MIN_CREDIT_STRESS": ("marcus", "divergence_min_credit_stress", None),
    # ── Sarah ───────────────────────────────────────────────────────────
    "VOL_TICKERS":               ("sarah", "vol_tickers", list),
    "FRED_RISK_FREE_SERIES":     ("sarah", "fred_risk_free_series", None),
    "VOL_IVR_MIN_HISTORY_DAYS":  ("sarah", "vol_ivr_min_history_days", None),
    "ANALOG_MIN_HISTORY_DAYS":   ("sarah", "analog_min_history_days", None),
    "VVIX_CONFIDENCE_MIN_DAYS":  ("sarah", "vvix_confidence_min_days", None),
    "CATALYST_TYPES":            ("sarah", "catalyst_types", tuple),
    "MAX_FLOW_NOTES_LENGTH":     ("sarah", "max_flow_notes_length", None),
    # ── Priya ───────────────────────────────────────────────────────────
    "BACKTEST_MIN_OBSERVATIONS":  ("priya", "backtest_min_observations", None),
    "BACKTEST_MIN_OPTIONS_OBS":   ("priya", "backtest_min_options_obs", None),
    "SPREAD_FLOOR_OTM_SHORT":     ("priya", "spread_floor_otm_short", None),
    "SPREAD_FLOOR_OTM_LONG":      ("priya", "spread_floor_otm_long", None),
    "SPREAD_FLOOR_ATM_SHORT":     ("priya", "spread_floor_atm_short", None),
    "SPREAD_FLOOR_ATM_LONG":      ("priya", "spread_floor_atm_long", None),
    "SPREAD_FLOOR_ITM_SHORT":     ("priya", "spread_floor_itm_short", None),
    "SPREAD_FLOOR_ITM_LONG":      ("priya", "spread_floor_itm_long", None),
    "BACKTEST_DEFAULT_SIGNIFICANCE":   ("priya", "backtest_default_significance", None),
    "BACKTEST_PBO_REJECT_THRESHOLD":   ("priya", "backtest_pbo_reject_threshold", None),
    "BACKTEST_DSR_ACCEPT_THRESHOLD":   ("priya", "backtest_dsr_accept_threshold", None),
    "BACKTEST_PRODUCTION_HAIRCUT":     ("priya", "backtest_production_haircut", None),
    "BACKTEST_MIN_VIABLE_HAIRCUT_SR":  ("priya", "backtest_min_viable_haircut_sr", None),
    "BACKTEST_REGIME_STALENESS_HOURS": ("priya", "backtest_regime_staleness_hours", None),
    "CPCV_DEFAULT_N_GROUPS":    ("priya", "cpcv_default_n_groups", None),
    "CPCV_DEFAULT_K_TEST":      ("priya", "cpcv_default_k_test", None),
    "CPCV_DEFAULT_PCT_EMBARGO": ("priya", "cpcv_default_pct_embargo", None),
    "MC_DEFAULT_N_PATHS":       ("priya", "mc_default_n_paths", None),
    "SHARPE_AUTOCORR_PVALUE_THRESHOLD": ("priya", "sharpe_autocorr_pvalue_threshold", None),
    "SHARPE_NEWEY_WEST_LAGS":   ("priya", "sharpe_newey_west_lags", list),
    "VOL_CONE_WINDOWS":         ("priya", "vol_cone_windows", list),
    "VOL_CONE_PERCENTILES":     ("priya", "vol_cone_percentiles", list),
    "FRACDIFF_D_RANGE":         ("priya", "fracdiff_d_range", tuple),
    "FRACDIFF_D_STEP":          ("priya", "fracdiff_d_step", None),
    "FRACDIFF_WEIGHT_THRESHOLD": ("priya", "fracdiff_weight_threshold", None),
    "TRIPLE_BARRIER_PT_MULTIPLIER": ("priya", "triple_barrier_pt_multiplier", None),
    "TRIPLE_BARRIER_SL_MULTIPLIER": ("priya", "triple_barrier_sl_multiplier", None),
    "TRIPLE_BARRIER_EWMA_SPAN":     ("priya", "triple_barrier_ewma_span", None),
    "BACKTEST_OVERFITTING_SHARPE_CV_THRESHOLD":
        ("priya", "backtest_overfitting_sharpe_cv_threshold", None),
    "BACKTEST_SWEEP_MIN_POINTS": ("priya", "backtest_sweep_min_points", None),
    # ── Data / Ops ──────────────────────────────────────────────────────
    "FOMC_SCHEDULE_2026":        ("data", "fomc_schedule", list),
    "CFTC_INSTRUMENTS":          ("data", "cftc_instruments", list),
    "DASHBOARD_REFRESH_SECONDS": ("data", "dashboard_refresh_seconds", None),
}

REGISTRY_BACKED_NAMES = frozenset(LEGACY_CONFIG_MAP)


def config_value(name: str):
    """Resolve a legacy config constant from the active registry version."""
    from .store import get_params

    component, field, cast = LEGACY_CONFIG_MAP[name]
    value = getattr(get_params(component), field)
    if cast is not None:
        return cast(value)
    if isinstance(value, (dict, list)):
        # defensive copy — consumers must not mutate shared cached state
        return copy.deepcopy(value)
    return value
