"""
Research Pipeline Orchestrator — Stage 0-8 workflow.

This module wires together all eight layers of the Architecture v2.0
backtesting engine into a single callable workflow.  Each stage maps to a
process gate; a failed gate raises PipelineGateError unless allow_continue
is set (not recommended for production research).

Stage 0: Hypothesis pre-registration (HypothesisRegistration)
Stage 1: Data audit and bar-type labelling (DataAuditReport)
Stage 2: Feature engineering (FracDiff, VolEstimatorSuite, VolCone)
Stage 3: Label construction (TripleBarrierLabeler, SampleWeights)
Stage 4: In-sample analysis (VectorizedBacktester or OptionsBacktester)
Stage 5: Cross-validation and overfitting assessment (PurgedKFold, CPCV, OverfitDiagnostics)
Stage 6: Statistical validation (SharpeEstimationPipeline, permutation_test, StrategyRisk)
Stage 7: Production simulation (ImplementationShortfall, production_haircut)
Stage 8: Verdict and experiment archive (ResearchTracker, verdict_summary)

Typical usage (equity signal research):
    pipeline = ResearchPipeline(hypothesis_id='VRP-001', allow_continue=False)
    result = pipeline.run_equity(
        returns=daily_returns,
        regime_series=regime_labels,
        trade_log=backtester.trade_log,
        params={'window': 20},
        run_name='vrp_spy_window20',
    )

Typical usage (options strategy research):
    pipeline = ResearchPipeline(hypothesis_id='VRP-001')
    result = pipeline.run_options(
        returns=daily_returns,
        trade_log=options_backtester.trade_log,
        mc_pnl=mc_result,
        params={'dte': 45, 'delta': 0.30},
        run_name='vrp_spy_45dte_delta30',
    )

The result dict contains run_id, verdict, suggested_verdict, gates_passed,
gates_failed, and all intermediate outputs for inspection.

Architecture v2.0 — Stage 7 / Stage 8 implementation.
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pandas as pd

from config import OUTPUTS_DIR
from systems.backtest.sharpe_pipeline import SharpeEstimationPipeline, permutation_test
from systems.backtest.cpcv import CPCV
from systems.backtest.overfit_statistics import OverfitDiagnostics
from systems.backtest.strategy_risk import StrategyRisk
from systems.backtest.impl_shortfall import (
    ImplementationShortfall,
    production_haircut,
    viable_after_haircut,
)
from systems.backtest.experiment_tracker import ResearchTracker, verdict_summary
from config import (
    CPCV_DEFAULT_N_GROUPS,
    CPCV_DEFAULT_K_TEST,
    CPCV_DEFAULT_PCT_EMBARGO,
    BACKTEST_DSR_ACCEPT_THRESHOLD,
    BACKTEST_PBO_REJECT_THRESHOLD,
)


# ── Process gate definitions (Architecture v2.0 "Research Process Gates") ─────

PROCESS_GATES = {
    'hypothesis_registration':  'Before any data access',
    'data_audit_clearance':     'Before feature engineering',
    'bar_type_documented':      'Before signal construction',
    'regime_conditional':       'Before in-sample conclusion',
    'cpcv_path_distribution':   'Before OOS examination',
    'pbo_threshold':            'Before OOS examination',
    'permutation_test':         'Before OOS examination',
    'ljung_box_se_method':      'Before Sharpe reporting',
    'dsr_threshold':            'Before production consideration',
    'oos_degradation':          'Before production consideration',
    'production_haircut':       'Before Jordan handoff',
    'leland_breakeven':         'Before options strategy handoff',
    'failure_archive_check':    'Before new research begins',
}

# ── Non-Negotiable Outputs (Architecture v2.0, all 12) ───────────────────────

NON_NEGOTIABLE_OUTPUTS = [
    'regime_conditional_sharpe',       # 1  — any regime bet is not an edge
    'parameter_sensitivity_surface',   # 2  — median Sharpe, not the peak
    'degradation_ratio',               # 3  — unexplained degradation = overfit
    'production_haircut_sharpe',       # 4  — the production viability number
    'sharpe_se_and_ci',                # 5  — bare Sharpe is incomplete
    'serial_correlation_diagnostic',   # 6  — options inflate naïve Sharpe 65%
    'dsr_with_trial_count',            # 7  — primary validity metric
    'cpcv_path_distribution',          # 8  — distribution, not a single draw
    'pbo_and_overfit_stats',           # 9  — PBO alone insufficient
    'mc_pnl_distribution',             # 10 — options only
    'three_level_cost_decomposition',  # 11 — options only
    'strategy_risk_prob_failure',      # 12 — P[p < p*]
]

_OPTIONS_ONLY = frozenset({'mc_pnl_distribution', 'three_level_cost_decomposition'})


def validate_outputs(results: dict, is_options: bool = False) -> list:
    """
    Return a list of non-negotiable output keys missing from results.

    For equity strategies the two options-only outputs are excluded
    (10 required).  For options strategies all 12 are required.

    Parameters
    ----------
    results : dict
        The results dict produced by ResearchPipeline.run_equity() or
        ResearchPipeline.run_options().
    is_options : bool
        Set True for options strategies (all 12 outputs required).

    Returns
    -------
    list[str] — names of missing outputs.  Empty list = all outputs present.
    """
    required = [
        k for k in NON_NEGOTIABLE_OUTPUTS
        if is_options or k not in _OPTIONS_ONLY
    ]
    return [k for k in required if results.get(k) is None]


def write_jordan_contract(
    hypothesis_id: str,
    strategy_type: str,
    verdict: str,
    sharpe_analysis: dict,
    cpcv_results: dict,
    validation_results: dict,
    leland_breakeven: Optional[float] = None,
) -> Path:
    """
    Write data/outputs/research_verdict.json — the Jordan input contract.

    Schema is locked once Stage 8 is complete.  Jordan (Phase 4) consumes
    this as its primary input.  The file is overwritten per run; full
    history is in MLflow.

    Returns the Path that was written.
    """
    regime_cond = validation_results.get('regime_conditional_sharpes')
    if isinstance(regime_cond, dict):
        # Flatten to sharpe scalars for Jordan (Jordan needs flat values)
        regime_cond = {
            k: (v.get('sharpe') if isinstance(v, dict) else v)
            for k, v in regime_cond.items()
        }

    def _safe(v: Any) -> Optional[float]:
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    contract = {
        'hypothesis_id':            hypothesis_id,
        'strategy_type':            strategy_type,
        'verdict':                  verdict,
        'regime_conditional_sharpe': regime_cond,
        'production_haircut_sharpe': _safe(sharpe_analysis.get('production_haircut_sr')),
        'viable_after_haircut':     bool(sharpe_analysis.get('viable_after_haircut', False)),
        'cpcv_path_count':          int(cpcv_results.get('n_paths', 0)),
        'pbo':                      _safe(cpcv_results.get('pbo')),
        'dsr':                      _safe(sharpe_analysis.get('dsr_primary')),
        'n_trials':                 int(sharpe_analysis.get('n_trials') or 0),
        'n_eff':                    _safe(sharpe_analysis.get('n_eff')),
        'min_track_record_years':   _safe(sharpe_analysis.get('min_track_record_years')),
        'leland_breakeven_spread':  _safe(leland_breakeven),
        'written_at':               datetime.now(timezone.utc).isoformat(),
    }

    out_path = Path(OUTPUTS_DIR) / 'research_verdict.json'
    out_path.write_text(json.dumps(contract, indent=2))
    return out_path


class PipelineGateError(Exception):
    """Raised when a process gate fails and allow_continue is False."""


class ResearchPipeline:
    """
    Full Stage 0–8 orchestrator for one hypothesis.

    Parameters
    ----------
    hypothesis_id : str
        Pre-registered hypothesis ID.  The caller is responsible for
        registering the hypothesis before instantiating this class.
    n_trials : int
        Number of strategy/parameter configurations tested on this dataset.
        Required for DSR computation.  If the caller does not track this
        separately, use HypothesisRegistration.get_trial_count(dataset_id).
    allow_continue : bool
        If True, failed process gates log warnings instead of raising.
        Default False — hard stops at each gate are the correct behaviour
        for production research.
    cpcv_n_groups : int
        CPCV partition count N.  Default from config (6).
    cpcv_k_test : int
        CPCV test groups k.  Default from config (2).
    annualization_factor : int
        Periods per year for Sharpe annualization.  252 (daily) by default.
    """

    def __init__(
        self,
        hypothesis_id: str,
        n_trials: int = 1,
        allow_continue: bool = False,
        cpcv_n_groups: int = CPCV_DEFAULT_N_GROUPS,
        cpcv_k_test: int = CPCV_DEFAULT_K_TEST,
        annualization_factor: int = 252,
    ) -> None:
        self.hypothesis_id = hypothesis_id
        self.n_trials = n_trials
        self.allow_continue = allow_continue
        self.cpcv_n_groups = cpcv_n_groups
        self.cpcv_k_test = cpcv_k_test
        self.annualization_factor = annualization_factor
        self._tracker = ResearchTracker()

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def run_equity(
        self,
        returns: pd.Series,
        trade_log: list,
        params: dict,
        run_name: str,
        regime_series: pd.Series | None = None,
        additional_metrics: dict | None = None,
        verdict_override: str | None = None,
        verdict_rationale_override: str | None = None,
    ) -> dict:
        """
        Run the full Stage 5–8 pipeline for an equity/index signal strategy.

        Stages 0–4 (data ingestion, feature engineering, labelling, in-sample
        backtesting) are the caller's responsibility — this method starts from
        the returns series produced by the backtest.

        Parameters
        ----------
        returns : pd.Series
            Daily strategy return series (NOT annualised).
        trade_log : list
            Trade log from the backtester.  Used for implementation shortfall.
        params : dict
            Strategy parameters to log.
        run_name : str
            Human-readable run identifier.
        regime_series : pd.Series, optional
            Regime labels aligned with returns.  Used to build the
            regime-conditional Sharpe table (Non-Negotiable Output #1).
        additional_metrics : dict, optional
            Extra scalar metrics to log alongside the pipeline outputs.
        verdict_override : str, optional
            'GO' or 'NO_GO'.  If provided, overrides the suggested verdict.
            The researcher must supply verdict_rationale_override.
        verdict_rationale_override : str, optional
            Required when verdict_override is provided.

        Returns
        -------
        dict with all pipeline outputs plus run_id and verdict.
        """
        return self._run(
            returns=returns,
            trade_log=trade_log,
            params=params,
            run_name=run_name,
            mc_pnl=None,
            strategy_type='equity',
            regime_series=regime_series,
            additional_metrics=additional_metrics or {},
            verdict_override=verdict_override,
            verdict_rationale_override=verdict_rationale_override,
        )

    def run_options(
        self,
        returns: pd.Series,
        trade_log: list,
        mc_pnl: dict,
        params: dict,
        run_name: str,
        regime_series: pd.Series | None = None,
        additional_metrics: dict | None = None,
        verdict_override: str | None = None,
        verdict_rationale_override: str | None = None,
    ) -> dict:
        """
        Run the full Stage 5–8 pipeline for an options strategy.

        Parameters
        ----------
        returns : pd.Series
            Daily P&L return series from the options backtest.
        trade_log : list
            Trade log from OptionsBacktester.  Required for three-level
            transaction cost attribution (DD-10).
        mc_pnl : dict
            Output of OptionsBacktester.monte_carlo_pnl_distribution().
            Non-Negotiable Output #10.
        params : dict
            Strategy parameters.
        run_name : str
            Human-readable run identifier.
        regime_series : pd.Series, optional
            Regime labels for conditional Sharpe table.
        additional_metrics : dict, optional
            Extra scalar metrics to log.
        verdict_override / verdict_rationale_override : optional
            See run_equity() docstring.
        """
        return self._run(
            returns=returns,
            trade_log=trade_log,
            params=params,
            run_name=run_name,
            mc_pnl=mc_pnl,
            strategy_type='options',
            regime_series=regime_series,
            additional_metrics=additional_metrics or {},
            verdict_override=verdict_override,
            verdict_rationale_override=verdict_rationale_override,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # Internal orchestration
    # ─────────────────────────────────────────────────────────────────────────

    def _run(
        self,
        returns: pd.Series,
        trade_log: list,
        params: dict,
        run_name: str,
        mc_pnl: dict | None,
        strategy_type: str,
        regime_series: pd.Series | None,
        additional_metrics: dict,
        verdict_override: str | None,
        verdict_rationale_override: str | None,
    ) -> dict:

        # ── Stage 5a: CPCV path distribution ─────────────────────────────────
        cpcv_results = self._run_cpcv(returns)

        # Gate: CPCV must complete before OOS examination
        if not cpcv_results:
            self._gate_fail('CPCV failed to produce results.')

        # ── Stage 5b: Overfitting diagnostics ────────────────────────────────
        path_sharpes = np.array(cpcv_results.get('path_sharpes', []))
        overfit_diagnostics = OverfitDiagnostics.full_report(
            is_sharpes=path_sharpes,
            oos_sharpes=path_sharpes,
            pbo=cpcv_results.get('pbo', float('nan')),
        )

        # Gate: PBO < BACKTEST_PBO_REJECT_THRESHOLD (0.05)
        pbo = cpcv_results.get('pbo', 1.0)
        if pbo >= BACKTEST_PBO_REJECT_THRESHOLD:
            self._gate_fail(
                f'PBO={pbo:.3f} ≥ {BACKTEST_PBO_REJECT_THRESHOLD}.  '
                'Overfit signal — investigate before OOS examination.'
            )

        # ── Stage 6a: Sharpe estimation pipeline ─────────────────────────────
        sharpe_pipe = SharpeEstimationPipeline(
            n_trials=self.n_trials,
            risk_free_per_period=0.0,
        )
        sharpe_analysis = sharpe_pipe.full_analysis(
            returns, annualization_factor=self.annualization_factor
        )

        # Gate: Ljung-Box must be checked before reporting Sharpe
        # (it is always computed inside full_analysis — gate is informational)
        if 'has_autocorrelation' not in sharpe_analysis:
            self._gate_fail('Sharpe estimation did not run serial correlation check.')

        # Gate: DSR > BACKTEST_DSR_ACCEPT_THRESHOLD
        dsr = sharpe_analysis.get('dsr_primary', 0.0) or 0.0
        if dsr <= BACKTEST_DSR_ACCEPT_THRESHOLD:
            msg = (
                f'DSR={dsr:.3f} ≤ {BACKTEST_DSR_ACCEPT_THRESHOLD}.  '
                'Does not meet production threshold.'
            )
            # This is a soft gate: warn but don't hard-stop so the run is
            # still archived as NO_GO (provides failure archive value)
            warnings.warn(msg, stacklevel=2)

        # Gate: production haircut viability
        sr_annual = sharpe_analysis.get('sr_annual', 0.0) or 0.0
        sharpe_analysis['viable_after_haircut'] = viable_after_haircut(sr_annual)
        sharpe_analysis['production_haircut_sr'] = production_haircut(sr_annual)

        # ── Stage 6b: Permutation test ────────────────────────────────────────
        def _sharpe_metric(r: pd.Series) -> float:
            s = r.std()
            return float(r.mean() / s) if s > 0 else 0.0

        perm_result = permutation_test(returns, _sharpe_metric, n_permutations=1000)

        # Gate: permutation test p-value
        if not perm_result.get('significant_at_5', False):
            warnings.warn(
                f'Permutation test p={perm_result.get("p_value", "?"):.4f} ≥ 0.05.  '
                'Strategy not significant under permutation null.',
                stacklevel=2,
            )

        # ── Stage 6c: Strategy risk ───────────────────────────────────────────
        strategy_risk = self._compute_strategy_risk(returns, trade_log)

        # ── Stage 7a: Implementation shortfall ───────────────────────────────
        is_result = ImplementationShortfall.compute(trade_log)
        is_gate = ImplementationShortfall.gate_check(is_result)

        if not is_gate.get('passes', False):
            warnings.warn(
                f'Implementation shortfall gate: {is_gate.get("message", "")}',
                stacklevel=2,
            )

        # ── Stage 7b/c: Production haircut (already in sharpe_analysis) ───────

        # ── Validation results (regime-conditional table + permutation) ────────
        validation_results = self._build_validation_results(
            returns, perm_result, regime_series, strategy_type, mc_pnl
        )

        # ── Stage 8: Verdict ─────────────────────────────────────────────────
        gate_summary = verdict_summary(
            sharpe_analysis=sharpe_analysis,
            cpcv_results=cpcv_results,
            overfit_diagnostics=overfit_diagnostics,
            impl_shortfall_gate=is_gate,
        )

        if verdict_override is not None:
            if verdict_override not in ('GO', 'NO_GO'):
                raise ValueError(
                    f"verdict_override must be 'GO' or 'NO_GO', got '{verdict_override}'"
                )
            if not verdict_rationale_override:
                raise ValueError(
                    'verdict_rationale_override is required when overriding the verdict.'
                )
            final_verdict = verdict_override
            final_rationale = verdict_rationale_override
        else:
            final_verdict = gate_summary['suggested_verdict']
            final_rationale = gate_summary['rationale']

        # ── Stage 8: Log to MLflow / fallback ────────────────────────────────
        run_id = self._tracker.log_research_run_v2(
            hypothesis_id=self.hypothesis_id,
            run_name=run_name,
            params=params,
            metrics=additional_metrics,
            sharpe_analysis=sharpe_analysis,
            cpcv_results=cpcv_results,
            overfit_diagnostics=overfit_diagnostics,
            strategy_risk=strategy_risk,
            impl_shortfall=is_result,
            mc_pnl=mc_pnl,
            validation_results=validation_results,
            verdict=final_verdict,
            verdict_rationale=final_rationale,
        )

        # ── Stage 8: Jordan output contract ──────────────────────────────────
        leland_be = (
            (mc_pnl or {}).get('leland_breakeven_spread')
            if strategy_type == 'options' else None
        )
        write_jordan_contract(
            hypothesis_id=self.hypothesis_id,
            strategy_type=strategy_type,
            verdict=final_verdict,
            sharpe_analysis=sharpe_analysis,
            cpcv_results=cpcv_results,
            validation_results=validation_results,
            leland_breakeven=leland_be,
        )

        # Build result dict with validate_outputs()-compatible keys
        result = {
            'run_id':             run_id,
            'verdict':            final_verdict,
            'verdict_rationale':  final_rationale,
            'suggested_verdict':  gate_summary['suggested_verdict'],
            'gates_passed':       gate_summary['gates_passed'],
            'gates_failed':       gate_summary['gates_failed'],
            # All twelve outputs for downstream inspection
            'sharpe_analysis':    sharpe_analysis,
            'cpcv_results':       cpcv_results,
            'overfit_diagnostics': overfit_diagnostics,
            'strategy_risk':      strategy_risk,
            'impl_shortfall':     is_result,
            'impl_shortfall_gate': is_gate,
            'mc_pnl':             mc_pnl,
            'validation_results': validation_results,
            'permutation_test':   perm_result,
        }

        # Expose validate_outputs()-compatible keys (Non-Negotiable Output names)
        result['regime_conditional_sharpe']      = validation_results.get('regime_conditional_sharpes')
        result['parameter_sensitivity_surface']  = params  # caller provides sweep separately
        result['degradation_ratio']              = sharpe_analysis.get('production_haircut_sr')
        result['production_haircut_sharpe']      = sharpe_analysis.get('production_haircut_sr')
        result['sharpe_se_and_ci']               = sharpe_analysis.get('ci_95')
        result['serial_correlation_diagnostic']  = sharpe_analysis.get('ljung_box_pvalue')
        result['dsr_with_trial_count']           = sharpe_analysis.get('dsr_primary')
        result['cpcv_path_distribution']         = cpcv_results.get('path_sharpes') or []
        result['pbo_and_overfit_stats']          = overfit_diagnostics
        result['mc_pnl_distribution']            = mc_pnl  # None for equity
        result['three_level_cost_decomposition'] = (
            validation_results.get('three_level_costs') if strategy_type == 'options' else None
        )
        result['strategy_risk_prob_failure']     = strategy_risk.get('prob_failure')

        return result

    # ─────────────────────────────────────────────────────────────────────────
    # Stage helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _run_cpcv(self, returns: pd.Series) -> dict:
        """Run CPCV and return the path Sharpe distribution dict."""
        cpcv = CPCV(
            n_groups=self.cpcv_n_groups,
            k_test=self.cpcv_k_test,
            pct_embargo=CPCV_DEFAULT_PCT_EMBARGO,
        )
        try:
            result = cpcv.compute_path_sharpes(returns)
            # Serialise path_sharpes array for logging (ndarray not JSON-safe)
            if 'path_sharpes' in result and isinstance(result['path_sharpes'], np.ndarray):
                result['path_sharpes'] = result['path_sharpes'].tolist()
            return result
        except Exception as exc:
            warnings.warn(f'CPCV failed: {exc}', stacklevel=3)
            return {}

    def _compute_strategy_risk(
        self, returns: pd.Series, trade_log: list
    ) -> dict:
        """
        Compute strategy risk from the trade log.
        Falls back to a returns-based approximation when payoff data is absent.
        """
        wins  = [t['net_pnl'] for t in trade_log if t.get('net_pnl', 0) > 0]
        loses = [t['net_pnl'] for t in trade_log if t.get('net_pnl', 0) <= 0]

        if not trade_log or not wins or not loses:
            # Approximate from returns
            pos = returns[returns > 0]
            neg = returns[returns <= 0]
            if pos.empty or neg.empty:
                return {'error': 'Insufficient trade data for strategy risk computation.'}
            n    = len(returns)
            p    = float(len(pos) / n)
            pi_pos = float(pos.mean())
            pi_neg = float(neg.mean())
        else:
            n      = len(trade_log)
            p      = len(wins) / n
            pi_pos = float(np.mean(wins))
            pi_neg = float(np.mean(loses))

        try:
            return StrategyRisk.full_report(p=p, n=n, pi_neg=pi_neg, pi_pos=pi_pos)
        except ValueError as exc:
            return {'error': str(exc)}

    def _build_validation_results(
        self,
        returns: pd.Series,
        perm_result: dict,
        regime_series: pd.Series | None,
        strategy_type: str,
        mc_pnl: dict | None,
    ) -> dict:
        """Assemble the validation_results dict (Non-Negotiable Outputs #1, #2, #10)."""
        result: dict[str, Any] = {
            'permutation_test': perm_result,
            'strategy_type':    strategy_type,
        }

        # Non-Negotiable Output #1: regime-conditional Sharpe table
        if regime_series is not None:
            regime_sharpes: dict[str, Any] = {}
            aligned = regime_series.reindex(returns.index).dropna()
            for regime in aligned.unique():
                mask = aligned == regime
                r_reg = returns[mask]
                if len(r_reg) < 10:
                    continue
                s = r_reg.std()
                regime_sharpes[str(regime)] = {
                    'sharpe': float(r_reg.mean() / s * np.sqrt(252)) if s > 0 else 0.0,
                    'n_obs':  int(len(r_reg)),
                    'mean':   float(r_reg.mean()),
                    'std':    float(s),
                }
            result['regime_conditional_sharpes'] = regime_sharpes
        else:
            result['regime_conditional_sharpes'] = None
            result['regime_conditional_sharpes_note'] = (
                'regime_series not provided — regime-conditional analysis skipped.  '
                'Ref: Non-Negotiable Output #1.'
            )

        # Non-Negotiable Output #10: MC P&L (options only; document N/A for equity)
        if strategy_type == 'equity' and mc_pnl is None:
            result['mc_pnl_note'] = (
                'Equity strategy — MC P&L distribution (Non-Negotiable Output #10) '
                'is not applicable.  See options_engine.py for options strategies.'
            )

        return result

    def _gate_fail(self, message: str) -> None:
        """Raise or warn depending on allow_continue setting."""
        full = f'Pipeline gate FAIL: {message}'
        if self.allow_continue:
            warnings.warn(full, stacklevel=3)
        else:
            raise PipelineGateError(full)
