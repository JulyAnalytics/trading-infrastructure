"""
Parameter models — the single source of truth for every tunable in the system.

Each component gets one dataclass. The DEFAULTS on these classes are the
canonical seed values (they mirror what config.py hardcoded through v0.5).
The live values are stored versioned in trading.db (see store.py); code reads
them via systems.params.get_params("<component>").

FIELD_SPECS carries per-field metadata used by the GUI to render forms and by
set_params() to validate edits:
    label        — human-readable name
    help         — one-line explanation
    bounds       — (min, max) for scalar numeric fields
    recompute    — name of the recompute action an edit invalidates
                   (e.g. "backfill_regime_history"), or None
    guarded      — True if relaxing this value weakens a research gate;
                   edits are allowed but flagged and stamped on outputs
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict, fields as dc_fields
from typing import Any


COMPONENTS = ("marcus", "sarah", "priya", "jordan", "ops", "data")


# ── Base ─────────────────────────────────────────────────────────────────────

@dataclass
class ParamsBase:
    """Shared (de)serialization + validation plumbing."""

    # Plain class attribute (deliberately NOT annotated — must not become a
    # dataclass field, and mutable dataclass defaults are illegal anyway).
    # Subclasses override with their own spec dict.
    FIELD_SPECS = {}

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), sort_keys=True, default=str)

    @classmethod
    def from_dict(cls, payload: dict) -> "ParamsBase":
        valid = {f.name for f in dc_fields(cls)}
        known = {k: v for k, v in payload.items() if k in valid}
        obj = cls(**known)
        obj._restore_types()
        return obj

    def _restore_types(self):
        """JSON round-trips lose tuples; subclasses restore them here."""

    def validate(self) -> "list[str]":
        """Return a list of violation strings; empty list = valid."""
        problems = []
        specs = type(self).FIELD_SPECS or {}
        for name, spec in specs.items():
            bounds = spec.get("bounds")
            if bounds is None:
                continue
            value = getattr(self, name, None)
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                lo, hi = bounds
                if not (lo <= value <= hi):
                    problems.append(
                        f"{name}={value} outside allowed range [{lo}, {hi}]"
                    )
        problems.extend(self._validate_extra())
        return problems

    def _validate_extra(self) -> "list[str]":
        return []


# ── Marcus — macro regime classification ────────────────────────────────────

@dataclass
class MarcusParams(ParamsBase):
    # Component weights — must sum to 1.0 (classifier asserts on init)
    component_weights: dict = field(default_factory=lambda: {
        "vol":         0.25,
        "credit":      0.25,
        "curve":       0.20,
        "inflation":   0.10,
        "labor":       0.15,
        "positioning": 0.05,
    })

    # Threshold families used by the component scorers (was REGIME_THRESHOLDS)
    regime_thresholds: dict = field(default_factory=lambda: {
        "vix":        {"low": 15.0, "medium": 20.0, "high": 25.0, "crisis": 35.0},
        "hy_spread":  {"tight": 300, "normal": 450, "wide": 600, "crisis": 900},
        "yield_curve_10_2": {"inverted": -10, "flat": 50, "normal": 100, "steep": 200},
        "unemployment_delta": {"improving": -0.3, "stable": 0.2, "deteriorating": 0.5},
        "breakeven_10y": {"anchored": 2.0, "elevated": 2.5, "unanchored": 3.0},
    })

    # Composite score → regime label mapping (was RegimeClassifier.SCORE_TO_REGIME)
    score_to_regime: list = field(default_factory=lambda: [
        [+0.60, "RISK_ON_LOW_VOL"],
        [+0.25, "RISK_ON_ELEVATED_VOL"],
        [-0.10, "NEUTRAL"],
        [-0.40, "CAUTION"],
        [-0.65, "RISK_OFF_STRESS"],
        [-2.00, "CRISIS"],
    ])

    # Divergence detection
    divergence_threshold_vc: float = 0.6
    divergence_threshold_vl: float = 0.7
    divergence_min_credit_stress: float = 0.1
    broad_divergence_spread: float = 1.2

    # Confidence mapping (fraction of non-positioning components agreeing)
    confidence_high_agreement: float = 0.8
    confidence_medium_agreement: float = 0.6

    # Data staleness (days) per component's primary series
    staleness_thresholds_days: dict = field(default_factory=lambda: {
        "vol": 3, "credit": 3, "curve": 3,
        "inflation": 3, "labor": 10, "positioning": 10,
    })
    unemployment_stale_days: int = 45

    FIELD_SPECS = {
        "component_weights": {
            "label": "Component weights",
            "help": "Weight of each macro component in the composite score. Must sum to 1.0.",
            "recompute": "backfill_regime_history",
        },
        "regime_thresholds": {
            "label": "Regime thresholds",
            "help": "Level cutoffs per input series used by the component scorers.",
            "recompute": "backfill_regime_history",
        },
        "score_to_regime": {
            "label": "Score→regime mapping",
            "help": "Composite-score floors for each regime label, highest first.",
            "recompute": "backfill_regime_history",
        },
        "divergence_threshold_vc": {
            "label": "Vol/Credit divergence threshold",
            "help": "Minimum |vol−credit| score spread to fire a divergence signal.",
            "bounds": (0.1, 2.0), "recompute": "backfill_regime_history",
        },
        "divergence_threshold_vl": {
            "label": "Vol/Labor divergence threshold",
            "bounds": (0.1, 2.0), "recompute": "backfill_regime_history",
        },
        "divergence_min_credit_stress": {
            "label": "Labor-lag credit gate",
            "help": "Credit score must be ≤ this for LABOR_LAG_WARNING to fire.",
            "bounds": (-1.0, 1.0),
        },
        "broad_divergence_spread": {
            "label": "Broad divergence spread",
            "help": "Max−min component score spread that flags BROAD_COMPONENT_DIVERGENCE.",
            "bounds": (0.5, 2.0),
        },
        "confidence_high_agreement": {"label": "HIGH confidence agreement", "bounds": (0.5, 1.0)},
        "confidence_medium_agreement": {"label": "MEDIUM confidence agreement", "bounds": (0.3, 1.0)},
        "staleness_thresholds_days": {
            "label": "Staleness thresholds (days)",
            "help": "Max age of each component's primary series before it is flagged stale.",
        },
        "unemployment_stale_days": {"label": "Unemployment staleness (days)", "bounds": (7, 120)},
    }

    def _validate_extra(self):
        problems = []
        w = self.component_weights
        total = sum(w.values())
        if abs(total - 1.0) > 1e-6:
            problems.append(f"component_weights sum to {total:.4f}, must sum to 1.0")
        expected = {"vol", "credit", "curve", "inflation", "labor", "positioning"}
        if set(w.keys()) != expected:
            problems.append(f"component_weights keys must be exactly {sorted(expected)}")
        thresholds = [row[0] for row in self.score_to_regime]
        if thresholds != sorted(thresholds, reverse=True):
            problems.append("score_to_regime thresholds must be strictly descending")
        if self.confidence_medium_agreement > self.confidence_high_agreement:
            problems.append("confidence_medium_agreement must be ≤ confidence_high_agreement")
        return problems


# ── Sarah — vol surface, scenarios, pre-trade ────────────────────────────────

def _default_stress_scenarios() -> dict:
    # Mirrors the v0.5 hardcoded library in scenario_engine.py.
    # vol_shock_vpts are ABSOLUTE vol points — never percentages.
    return {
        "2018_q4": {
            "label": "2018 Q4 Selloff", "spot_shock": -0.20, "vol_shock_vpts": 24.0,
            "duration": "3 months",
            "character": "Grinding decline, sustained. Not a one-day shock.",
        },
        "march_2020": {
            "label": "March 2020", "spot_shock": -0.34, "vol_shock_vpts": 62.0,
            "duration": "3 weeks",
            "character": "Acute shock, historic speed. Liquidity collapse.",
        },
        "aug_2015": {
            "label": "August 2015 China", "spot_shock": -0.11, "vol_shock_vpts": 22.0,
            "duration": "2 weeks",
            "character": "Spike and recovery. Vol mean-reverted quickly.",
        },
        "volmageddon": {
            "label": "Volmageddon Feb 2018", "spot_shock": -0.04, "vol_shock_vpts": 20.0,
            "duration": "1 session",
            "character": "Vol-specific. Spot barely moved; vol doubled.",
        },
        "2022_rates": {
            "label": "2022 Rate Shock", "spot_shock": -0.25, "vol_shock_vpts": 15.0,
            "duration": "10 months",
            "character": "Slow grind, no acute spike. Theta bleed punished longs throughout.",
        },
        "2011_euro": {
            "label": "2011 Euro Crisis", "spot_shock": -0.19, "vol_shock_vpts": 22.0,
            "duration": "5 months",
            "character": "Repeated stress events. Multiple spikes and partial recoveries.",
        },
    }


@dataclass
class SarahParams(ParamsBase):
    # Daily pipeline
    vol_tickers: list = field(default_factory=lambda: ["SPY", "QQQ", "IWM", "XLE", "GLD"])
    fred_risk_free_series: str = "DGS3MO"
    risk_free_fallback: float = 0.045
    vol_ivr_min_history_days: int = 60
    analog_min_history_days: int = 120
    vvix_confidence_min_days: int = 504
    # Max age of regime_state.json the daily vol run accepts before hard-failing.
    # 80h (not the 12h production limit) is intentional: it covers the Friday
    # close → Monday morning weekend cycle, where Friday's regime is the correct
    # most-recent signal for Monday's run.
    regime_staleness_hours: float = 80.0
    # Expirations fetched per ticker in the daily run. Weekly-chain tickers
    # (SPY/QQQ/IWM) list ~3 expirations/week, so 6 reached only ~10 DTE and
    # the 30/60/180d tenors were clamped extrapolations (ts_shape stuck on
    # 'flat'). 24 reaches ~120-180 DTE at ~1 chain request per expiration.
    chain_max_expirations: int = 24
    # Seconds to pause between tickers in a BATCH run (the daily universe is
    # unaffected — it is small and well-spaced already). Yahoo throttles at
    # ~30+ rapid chain fetches; a small gap keeps large ad-hoc batches
    # (earnings-week screening) under the limit. Batch mode only.
    batch_inter_ticker_delay_s: float = 1.0

    # RCS trade intake (Sarah ← RCS seam)
    # Position tickers with no yfinance options chain (leveraged / inverse
    # ETFs, thin names) mapped to the options-liquid underlier Sarah actually
    # analyses. Class-C judgment input, reusable across trades — see
    # docs/design_decisions/ADR-005 and the trade-intake spec §4.
    underlier_map: dict = field(default_factory=lambda: {
        "AMDL": "AMD", "GOOX": "GOOG", "GDXU": "GDX",
    })
    intake_poll_minutes: int = 5
    intake_fire_on_idea: bool = True

    # Pre-trade dashboard
    catalyst_types: list = field(default_factory=lambda: [
        "macro_slow", "macro_catalyst", "event_specific", "technical",
    ])
    max_flow_notes_length: int = 200

    # Scenario engine — grid
    grid_spot_range_pct: float = 0.30
    grid_spot_step_pct: float = 0.025
    grid_iv_range_vpts: float = 25.0
    grid_iv_step_vpts: float = 1.0
    grid_time_checkpoints: list = field(default_factory=lambda: [0.0, 0.25, 0.50, 0.75])
    grid_spot_range_highvol: float = 0.40
    grid_iv_range_highvol: float = 35.0
    highvol_vix_threshold: float = 25.0

    # Scenario engine — named stress library (user-editable in the GUI)
    stress_scenarios: dict = field(default_factory=_default_stress_scenarios)

    # Scenario engine — kill scenario defaults
    kill_iv_compression_vpts: float = 8.0
    kill_days_elapsed: int = 30

    # Break-even grid search
    breakeven_search_range: float = 0.35
    breakeven_step: float = 0.001

    FIELD_SPECS = {
        "vol_tickers": {"label": "Daily vol tickers",
                        "help": "Universe for the daily vol surface run."},
        "fred_risk_free_series": {"label": "Risk-free FRED series"},
        "risk_free_fallback": {"label": "Risk-free fallback rate",
                               "help": "Used when the FRED fetch fails.",
                               "bounds": (0.0, 0.15)},
        "vol_ivr_min_history_days": {"label": "IVR min history (days)", "bounds": (20, 756)},
        "analog_min_history_days": {"label": "Analog search min history (days)", "bounds": (30, 756)},
        "vvix_confidence_min_days": {"label": "VVIX confidence min history (days)", "bounds": (60, 1260)},
        "regime_staleness_hours": {
            "label": "Regime staleness limit (hours)",
            "help": "Daily vol run hard-fails if regime_state.json is older than "
                    "this. 80h covers the Friday→Monday weekend cycle; do not "
                    "drop below the intraday cadence you actually run at.",
            "bounds": (12, 168),
        },
        "chain_max_expirations": {
            "label": "Chain expirations per ticker",
            "help": "How many listed expirations the daily run fetches. Must "
                    "reach past 60 DTE on weekly-chain tickers or the 30/60/180d "
                    "term structure degrades to a flat extrapolation. Each "
                    "expiration is one yfinance request.",
            "bounds": (4, 40),
        },
        "batch_inter_ticker_delay_s": {
            "label": "Batch inter-ticker delay (s)",
            "help": "Pause between tickers in an ad-hoc BATCH run (the daily "
                    "universe is unaffected). Yahoo throttles ~30+ rapid chain "
                    "fetches; this keeps a large screening batch under the limit.",
            "bounds": (0.0, 10.0),
        },
        "underlier_map": {
            "label": "Underlier map (position ticker → options-liquid underlier)",
            "help": "Leveraged/inverse ETFs and thin names have no yfinance "
                    "options chain. RCS trade intake resolves the position "
                    "ticker through this map before enqueuing the vol pull. "
                    "A ticker with no chain AND no entry becomes the one "
                    "blocking question asked of you.",
        },
        "intake_poll_minutes": {
            "label": "RCS intake poll interval (minutes)",
            "help": "How often scheduler v2 checks RCS entity_events for newly "
                    "activated (and, if enabled, newly created) option trades.",
            "bounds": (1, 240),
        },
        "intake_fire_on_idea": {
            "label": "Fire intake on idea-stage trades",
            "help": "On: a trade created as an idea also triggers the vol pull, "
                    "so the memo's structure comparison is available while the "
                    "legs are still open (it is a chooser, not a monitor). Off: "
                    "only idea→active fires. On costs extra chain pulls on ideas "
                    "that never trade — they still accrue IV-rank history.",
        },
        "catalyst_types": {"label": "Catalyst types",
                           "help": "Allowed catalyst_type values in TradeThesisInput."},
        "max_flow_notes_length": {"label": "Flow notes max length", "bounds": (50, 2000)},
        "grid_spot_range_pct": {"label": "Grid spot range (±)", "bounds": (0.05, 1.0)},
        "grid_spot_step_pct": {"label": "Grid spot step", "bounds": (0.001, 0.10)},
        "grid_iv_range_vpts": {"label": "Grid IV range (±vpts)", "bounds": (5, 100)},
        "grid_iv_step_vpts": {"label": "Grid IV step (vpts)", "bounds": (0.25, 10)},
        "grid_time_checkpoints": {"label": "Grid time checkpoints",
                                  "help": "Fractions of DTE elapsed at which the grid is evaluated."},
        "grid_spot_range_highvol": {"label": "Grid spot range, high-vol (±)", "bounds": (0.05, 1.0)},
        "grid_iv_range_highvol": {"label": "Grid IV range, high-vol (±vpts)", "bounds": (5, 150)},
        "highvol_vix_threshold": {"label": "High-vol mode VIX threshold", "bounds": (15, 60)},
        "stress_scenarios": {
            "label": "Stress scenario library",
            "help": "Named historical scenarios. vol_shock_vpts are ABSOLUTE vol points.",
        },
        "kill_iv_compression_vpts": {"label": "Kill scenario IV compression (vpts)", "bounds": (1, 40)},
        "kill_days_elapsed": {"label": "Kill scenario days elapsed", "bounds": (1, 365)},
        "breakeven_search_range": {"label": "Break-even search range (±)", "bounds": (0.05, 1.0)},
        "breakeven_step": {"label": "Break-even search step", "bounds": (0.0001, 0.02)},
    }

    def _validate_extra(self):
        problems = []
        if not self.vol_tickers:
            problems.append("vol_tickers must not be empty")
        for key, sc in self.stress_scenarios.items():
            for req in ("label", "spot_shock", "vol_shock_vpts"):
                if req not in sc:
                    problems.append(f"stress_scenarios['{key}'] missing '{req}'")
        if self.grid_spot_step_pct >= self.grid_spot_range_pct:
            problems.append("grid_spot_step_pct must be smaller than grid_spot_range_pct")
        for k, v in (self.underlier_map or {}).items():
            if not isinstance(k, str) or not isinstance(v, str) or not k or not v:
                problems.append(
                    f"underlier_map['{k}']={v!r} — both sides must be non-empty "
                    "ticker strings")
            elif k.upper() == v.upper():
                problems.append(
                    f"underlier_map['{k}'] maps to itself — remove the entry")
        return problems


# ── Priya — backtest engine and research gates ───────────────────────────────

@dataclass
class PriyaParams(ParamsBase):
    # Data audit
    backtest_min_observations: int = 252
    backtest_min_options_obs: int = 126

    # Empirical spread floors (Hilpisch Table 3.1 — DJIA 1996-2010)
    spread_floor_otm_short: float = 0.12
    spread_floor_otm_long: float = 0.08
    spread_floor_atm_short: float = 0.06
    spread_floor_atm_long: float = 0.04
    spread_floor_itm_short: float = 0.05
    spread_floor_itm_long: float = 0.037

    # Hypothesis testing / research gates
    backtest_default_significance: float = 0.05
    backtest_pbo_reject_threshold: float = 0.05
    backtest_dsr_accept_threshold: float = 0.95
    backtest_production_haircut: float = 0.50
    backtest_min_viable_haircut_sr: float = 0.5
    backtest_regime_staleness_hours: int = 80

    # CPCV
    cpcv_default_n_groups: int = 6
    cpcv_default_k_test: int = 2
    cpcv_default_pct_embargo: float = 0.01

    # Monte Carlo
    mc_default_n_paths: int = 1000

    # Sharpe pipeline
    sharpe_autocorr_pvalue_threshold: float = 0.05
    sharpe_newey_west_lags: list = field(default_factory=lambda: [3, 6])

    # Vol estimators
    vol_cone_windows: list = field(default_factory=lambda: [20, 40, 60, 120, 240])
    vol_cone_percentiles: list = field(default_factory=lambda: [5, 25, 50, 75, 95])
    fracdiff_d_range: list = field(default_factory=lambda: [0.0, 1.0])
    fracdiff_d_step: float = 0.05
    fracdiff_weight_threshold: float = 1e-5

    # Triple-barrier labeling
    triple_barrier_pt_multiplier: float = 1.0
    triple_barrier_sl_multiplier: float = 1.0
    triple_barrier_ewma_span: int = 100

    # Vectorized engine overfitting flags
    backtest_overfitting_sharpe_cv_threshold: float = 0.5
    backtest_sweep_min_points: int = 10

    FIELD_SPECS = {
        "backtest_min_observations": {"label": "Min observations (equity)", "bounds": (60, 2520)},
        "backtest_min_options_obs": {"label": "Min observations (options)", "bounds": (30, 2520)},
        "backtest_default_significance": {"label": "Significance level", "bounds": (0.001, 0.20), "guarded": True},
        "backtest_pbo_reject_threshold": {
            "label": "PBO reject threshold",
            "help": "Research gate: PBO above this fails the run.",
            "bounds": (0.01, 0.50), "guarded": True,
        },
        "backtest_dsr_accept_threshold": {
            "label": "DSR accept threshold",
            "help": "Research gate: DSR below this fails the run.",
            "bounds": (0.50, 0.999), "guarded": True,
        },
        "backtest_production_haircut": {
            "label": "Production haircut",
            "help": "Fraction of OOS Sharpe assumed to survive to production.",
            "bounds": (0.1, 1.0), "guarded": True,
        },
        "backtest_min_viable_haircut_sr": {
            "label": "Min viable haircut Sharpe", "bounds": (0.0, 3.0), "guarded": True,
        },
        "backtest_regime_staleness_hours": {
            "label": "Regime staleness for research (hours)", "bounds": (12, 168),
        },
        "cpcv_default_n_groups": {"label": "CPCV groups (N)", "bounds": (4, 20)},
        "cpcv_default_k_test": {"label": "CPCV test groups (k)", "bounds": (1, 10)},
        "cpcv_default_pct_embargo": {"label": "CPCV embargo fraction", "bounds": (0.0, 0.20)},
        "mc_default_n_paths": {"label": "Monte Carlo paths", "bounds": (100, 100000)},
        "sharpe_autocorr_pvalue_threshold": {"label": "Ljung-Box p-value threshold", "bounds": (0.001, 0.20)},
        "triple_barrier_pt_multiplier": {"label": "Profit-target barrier (×vol)", "bounds": (0.1, 10)},
        "triple_barrier_sl_multiplier": {"label": "Stop-loss barrier (×vol)", "bounds": (0.1, 10)},
        "triple_barrier_ewma_span": {"label": "Barrier vol EWMA span", "bounds": (10, 1000)},
        "backtest_overfitting_sharpe_cv_threshold": {"label": "Sweep Sharpe CV warning", "bounds": (0.1, 3.0)},
        "backtest_sweep_min_points": {"label": "Min sweep points for CV flag", "bounds": (3, 1000)},
    }

    def _validate_extra(self):
        problems = []
        if self.cpcv_default_k_test >= self.cpcv_default_n_groups:
            problems.append("cpcv_default_k_test must be < cpcv_default_n_groups")
        return problems


# ── Jordan — risk limits (Phase 5 consumes these) ────────────────────────────

@dataclass
class JordanParams(ParamsBase):
    nav: float = 100_000.0                  # portfolio NAV used for %-of-NAV limits
    max_net_delta_pct: float = 0.20         # |net delta $| / NAV
    max_net_vega_pct: float = 0.15          # |net vega $ per vol pt| / NAV
    max_single_position_pct: float = 0.05   # position notional / NAV
    drawdown_alert_pct: float = 0.08
    drawdown_halt_pct: float = 0.15
    min_liquidity_days: int = 5
    default_risk_pct_per_trade: float = 0.01
    verdict_max_age_hours: int = 168        # research_verdict.json older than this is stale

    FIELD_SPECS = {
        "nav": {"label": "Portfolio NAV", "bounds": (1_000.0, 1e9)},
        "max_net_delta_pct": {"label": "Max net delta (% NAV)", "bounds": (0.01, 2.0)},
        "max_net_vega_pct": {"label": "Max net vega (% NAV)", "bounds": (0.01, 2.0)},
        "max_single_position_pct": {"label": "Max single position (% NAV)", "bounds": (0.005, 1.0)},
        "drawdown_alert_pct": {"label": "Drawdown alert", "bounds": (0.01, 0.50)},
        "drawdown_halt_pct": {"label": "Drawdown halt", "bounds": (0.02, 0.80)},
        "min_liquidity_days": {"label": "Min liquidity (days to exit)", "bounds": (1, 60)},
        "default_risk_pct_per_trade": {"label": "Default risk per trade (% NAV)", "bounds": (0.001, 0.05)},
        "verdict_max_age_hours": {"label": "Verdict max age (hours)", "bounds": (1, 24 * 90)},
    }

    def _validate_extra(self):
        problems = []
        if self.drawdown_alert_pct >= self.drawdown_halt_pct:
            problems.append("drawdown_alert_pct must be < drawdown_halt_pct")
        return problems


# ── Ops — schedule + orchestration ───────────────────────────────────────────

@dataclass
class OpsParams(ParamsBase):
    daily_pipeline_time: str = "18:05"      # weekdays — FRED + COT + classify
    vol_run_time: str = "08:00"             # weekdays — Sarah daily vol
    snapshot_time: str = "18:15"            # weekdays — PDF snapshot
    weekly_refresh_time: str = "20:00"      # Sunday — full FRED history
    calendar_fetch_time: str = "20:05"      # Sunday — macro calendar
    regime_staleness_hours_production: int = 12
    job_max_retries: int = 2
    job_retry_wait_seconds: int = 120
    # Phase 6 scheduler v2
    scheduler_enabled: bool = True
    weekly_review_time: str = "17:00"       # Friday — Alex weekly review

    FIELD_SPECS = {
        "daily_pipeline_time": {"label": "Daily macro pipeline (HH:MM, weekdays)"},
        "vol_run_time": {"label": "Daily vol run (HH:MM, weekdays)"},
        "snapshot_time": {"label": "Nightly snapshot (HH:MM, weekdays)"},
        "weekly_refresh_time": {"label": "Weekly full refresh (HH:MM, Sunday)"},
        "calendar_fetch_time": {"label": "Calendar fetch (HH:MM, Sunday)"},
        "regime_staleness_hours_production": {
            "label": "Production regime staleness (hours)",
            "help": "CLAUDE.md Rule 4 — downstream components hard-fail beyond this.",
            "bounds": (1, 96),
        },
        "job_max_retries": {"label": "Job max retries", "bounds": (0, 10)},
        "job_retry_wait_seconds": {"label": "Job retry wait (s)", "bounds": (5, 3600)},
        "scheduler_enabled": {
            "label": "Scheduler v2 enabled",
            "help": "Master switch for the in-process schedule loop. Off = "
                    "jobs run only when triggered manually.",
        },
        "weekly_review_time": {"label": "Weekly review (HH:MM, Friday)"},
    }

    def _validate_extra(self):
        problems = []
        for name in ("daily_pipeline_time", "vol_run_time", "snapshot_time",
                     "weekly_refresh_time", "calendar_fetch_time",
                     "weekly_review_time"):
            v = getattr(self, name)
            parts = v.split(":")
            ok = (len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit()
                  and 0 <= int(parts[0]) <= 23 and 0 <= int(parts[1]) <= 59)
            if not ok:
                problems.append(f"{name}='{v}' is not a valid HH:MM time")
        return problems


# ── Data — calendars and instrument universes ────────────────────────────────

@dataclass
class DataParams(ParamsBase):
    fomc_schedule: list = field(default_factory=lambda: [
        "2026-01-29", "2026-03-18", "2026-05-06",
        "2026-06-17", "2026-07-29", "2026-09-16",
        "2026-10-28", "2026-12-16",
    ])
    cftc_instruments: list = field(default_factory=lambda: [
        "SP500", "NASDAQ", "EURUSD", "GOLD", "WTI", "BONDS_10Y",
    ])
    dashboard_refresh_seconds: int = 3600
    # Series in config.MACRO_SERIES to skip during ingestion (by internal name)
    macro_series_disabled: list = field(default_factory=list)

    FIELD_SPECS = {
        "fomc_schedule": {"label": "FOMC meeting dates",
                          "help": "ISO dates. Requires manual update each year."},
        "cftc_instruments": {"label": "CFTC COT instruments"},
        "dashboard_refresh_seconds": {"label": "Dashboard refresh (s)", "bounds": (60, 86400)},
        "macro_series_disabled": {"label": "Disabled macro series",
                                  "help": "Internal names from MACRO_SERIES to skip on ingest."},
    }


# ── Registry map ─────────────────────────────────────────────────────────────

MODEL_BY_COMPONENT = {
    "marcus": MarcusParams,
    "sarah":  SarahParams,
    "priya":  PriyaParams,
    "jordan": JordanParams,
    "ops":    OpsParams,
    "data":   DataParams,
}
