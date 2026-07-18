"""
Layer 8: Experiment Tracking — MLflow integration, signal library, failure archive.

Every research run — including NO_GO runs — is logged here.  Failures are as
important as successes: documenting what was tried and why it failed prevents
re-running the same experiments and enables pattern recognition across the
failure archive.

The primary performance validity metric is DSR, not raw Sharpe.  Every logged
run stores the full SharpeEstimationPipeline output so DSR is always available
alongside the point estimate.

Design decisions encoded here:
- DD-11: PBO is diagnostic ONLY. This class accepts PBO embedded in the
  completed cpcv_results dict. It is never exposed as an optimisation input,
  callback, or selection criterion. The API does not accept PBO as a standalone
  parameter — it arrives inside cpcv_results that was already computed.
- Primary performance validity metric is DSR (not raw Sharpe). MLflow's
  primary logged metric is 'dsr_primary'. Raw Sharpe is logged but not the
  primary metric.
- NO_GO verdicts are tagged 'is_failure_archive_entry: true' for retrieval
  by the failure archive workflow.
- Engine version is tagged on every run for forward compatibility.
- When MLflow is unavailable, runs are written as JSON to
  OUTPUTS_DIR/../mlruns_fallback/.  The API is identical in both modes.

Ref: Architecture v2.0 Layer 8; LdP AFML Ch.14, DD-11.
"""

from __future__ import annotations

import json
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import mlflow
    MLFLOW_AVAILABLE = True
except ImportError:
    MLFLOW_AVAILABLE = False
    warnings.warn(
        "mlflow not available.  ResearchTracker will write JSON artefacts to "
        "OUTPUTS_DIR/../mlruns_fallback/ instead of an MLflow tracking server.",
        stacklevel=2,
    )

from config import (
    MLFLOW_TRACKING_URI,
    MLFLOW_EXPERIMENT_NAME,
    OUTPUTS_DIR,
    BACKTEST_DSR_ACCEPT_THRESHOLD,
    BACKTEST_MIN_VIABLE_HAIRCUT_SR,
)

_ENGINE_VERSION = '2.0'

# Keys that must be non-empty for a run to be COMPLETE
_REQUIRED_ARTEFACTS = (
    'sharpe_analysis',
    'cpcv_results',
    'overfit_diagnostics',
    'strategy_risk',
    'impl_shortfall',
)


class ResearchTracker:
    """
    MLflow-backed experiment tracker for all Priya research runs.

    Usage:
        tracker = ResearchTracker()
        run_id = tracker.log_research_run_v2(
            hypothesis_id='vrp_001',
            run_name='vrp_spx_window20',
            params={'window': 20, 'threshold': 0.03},
            metrics={'total_return': 0.12},
            sharpe_analysis=sharpe_pipeline.full_analysis(returns),
            cpcv_results=cpcv.compute_path_sharpes(...),
            overfit_diagnostics=OverfitDiagnostics.full_report(...),
            strategy_risk=StrategyRisk.full_report(...),
            impl_shortfall=ImplementationShortfall.compute(trade_log),
            validation_results={'permutation_pvalue': 0.02, ...},
            verdict='NO_GO',
            verdict_rationale='DSR 0.61 below 0.95 threshold.',
            mc_pnl=None,   # equity strategy — document N/A in validation_results
        )

    All v2.0 artefact fields are required.  A run missing any of them is logged
    but tagged INCOMPLETE.  The verdict should be NO_GO for incomplete runs.
    """

    def __init__(self) -> None:
        if MLFLOW_AVAILABLE:
            mlflow.set_tracking_uri(MLFLOW_TRACKING_URI)
            try:
                mlflow.set_experiment(MLFLOW_EXPERIMENT_NAME)
            except Exception as exc:
                warnings.warn(
                    f'Could not set MLflow experiment "{MLFLOW_EXPERIMENT_NAME}": {exc}',
                    stacklevel=2,
                )
        else:
            self._fallback_dir = (
                Path(OUTPUTS_DIR).parent / 'mlruns_fallback' / MLFLOW_EXPERIMENT_NAME
            )
            self._fallback_dir.mkdir(parents=True, exist_ok=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Primary API
    # ─────────────────────────────────────────────────────────────────────────

    def log_research_run_v2(
        self,
        hypothesis_id: str,
        run_name: str,
        params: dict,
        metrics: dict,
        sharpe_analysis: dict,
        cpcv_results: dict,
        overfit_diagnostics: dict,
        strategy_risk: dict,
        impl_shortfall: dict,
        validation_results: dict,
        verdict: str,
        verdict_rationale: str,
        mc_pnl: dict | None = None,
    ) -> str:
        """
        Log a complete v2.0 research run.

        Parameters
        ----------
        hypothesis_id : str
            Pre-registered hypothesis ID from HypothesisRegistration.
        run_name : str
            Human-readable name for this parameter configuration.
        params : dict
            Strategy parameters (window, threshold, etc.).  Scalar values.
        metrics : dict
            Scalar performance metrics (total_return, win_rate, etc.).
            DSR, PBO, and production Sharpe are added automatically from the
            structured outputs.
        sharpe_analysis : dict
            Full output of SharpeEstimationPipeline.full_analysis().
            Must contain 'dsr_primary', 'sr_annual', 'production_haircut_sr'.
        cpcv_results : dict
            Full output of CPCV.compute_path_sharpes().
            Must contain 'pbo', 'mean_sharpe'.
            PBO is read here as a completed diagnostic — DD-11.
        overfit_diagnostics : dict
            Output of OverfitDiagnostics.full_report().
        strategy_risk : dict
            Output of StrategyRisk.full_report().
        impl_shortfall : dict
            Output of ImplementationShortfall.compute().
        validation_results : dict
            Permutation test results and regime-conditional Sharpe table.
        verdict : str
            'GO' or 'NO_GO'.  GO entries advance to Jordan.
        verdict_rationale : str
            Plain-language explanation of the verdict.
        mc_pnl : dict, optional
            Output of OptionsBacktester.monte_carlo_pnl_distribution().
            Pass None for equity strategies — document the N/A in
            validation_results.  Absence without documentation is flagged.

        Returns
        -------
        str — run_id for cross-referencing with the failure archive.
        """
        if verdict not in ('GO', 'NO_GO'):
            raise ValueError(f"verdict must be 'GO' or 'NO_GO', got '{verdict}'")

        missing = self._check_completeness(
            sharpe_analysis, cpcv_results, overfit_diagnostics,
            strategy_risk, impl_shortfall, mc_pnl,
        )

        if MLFLOW_AVAILABLE:
            return self._log_mlflow(
                hypothesis_id=hypothesis_id, run_name=run_name,
                params=params, metrics=metrics,
                sharpe_analysis=sharpe_analysis, cpcv_results=cpcv_results,
                overfit_diagnostics=overfit_diagnostics,
                strategy_risk=strategy_risk, impl_shortfall=impl_shortfall,
                mc_pnl=mc_pnl, validation_results=validation_results,
                verdict=verdict, verdict_rationale=verdict_rationale,
                missing_outputs=missing,
            )
        else:
            return self._log_fallback(
                hypothesis_id=hypothesis_id, run_name=run_name,
                params=params, metrics=metrics,
                sharpe_analysis=sharpe_analysis, cpcv_results=cpcv_results,
                overfit_diagnostics=overfit_diagnostics,
                strategy_risk=strategy_risk, impl_shortfall=impl_shortfall,
                mc_pnl=mc_pnl, validation_results=validation_results,
                verdict=verdict, verdict_rationale=verdict_rationale,
                missing_outputs=missing,
            )

    def get_run(self, run_id: str) -> dict | None:
        """Retrieve a logged run by ID.  Returns None if not found."""
        if MLFLOW_AVAILABLE:
            try:
                client = mlflow.tracking.MlflowClient()
                run = client.get_run(run_id)
                return {
                    'run_id':        run.info.run_id,
                    'run_name':      run.info.run_name,
                    'status':        run.info.status,
                    'tags':          dict(run.data.tags),
                    'params':        dict(run.data.params),
                    'metrics':       dict(run.data.metrics),
                }
            except Exception:
                return None
        else:
            path = self._fallback_dir / run_id / 'run_summary.json'
            if path.exists():
                with path.open() as f:
                    return json.load(f)
            return None

    def list_runs(self, verdict_filter: str | None = None,
                  max_results: int = 50) -> list[dict]:
        """
        List logged runs, optionally filtered by verdict ('GO' or 'NO_GO').
        Returns a list of summary dicts ordered by recency.
        """
        if MLFLOW_AVAILABLE:
            return self._list_mlflow(verdict_filter, max_results)
        else:
            return self._list_fallback(verdict_filter, max_results)

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    @staticmethod
    def _check_completeness(
        sharpe_analysis: dict,
        cpcv_results: dict,
        overfit_diagnostics: dict,
        strategy_risk: dict,
        impl_shortfall: dict,
        mc_pnl: dict | None,
    ) -> list[str]:
        """Return names of missing non-negotiable outputs."""
        check = {
            'sharpe_analysis':     sharpe_analysis,
            'cpcv_results':        cpcv_results,
            'overfit_diagnostics': overfit_diagnostics,
            'strategy_risk':       strategy_risk,
            'impl_shortfall':      impl_shortfall,
        }
        missing = [k for k, v in check.items() if not v]
        if mc_pnl is None:
            missing.append(
                'mc_pnl (options) — if equity strategy, document N/A '
                'in validation_results'
            )
        if missing:
            warnings.warn(
                f'ResearchTracker: run is missing outputs: {missing}. '
                f'Tagged INCOMPLETE.',
                stacklevel=4,
            )
        return missing

    @staticmethod
    def _build_primary_metrics(
        metrics: dict,
        sharpe_analysis: dict,
        cpcv_results: dict,
    ) -> dict:
        """
        Merge caller metrics with key derived scalars.
        DSR is the primary performance validity metric.
        """
        derived: dict[str, float] = {}

        if sharpe_analysis:
            for key in ('dsr_primary', 'dsr_literal', 'psr', 'sr_annual',
                        'production_haircut_sr', 'ljung_box_pvalue'):
                if key in sharpe_analysis and isinstance(sharpe_analysis[key], (int, float)):
                    derived[key] = float(sharpe_analysis[key])

        if cpcv_results:
            for key in ('pbo', 'mean_sharpe', 'pct_positive', 'is_oos_correlation'):
                if key in cpcv_results and isinstance(cpcv_results[key], (int, float)):
                    derived[key] = float(cpcv_results[key])

        merged = {**metrics, **derived}
        return {
            k: float(v)
            for k, v in merged.items()
            if isinstance(v, (int, float)) and not isinstance(v, bool)
        }

    def _log_mlflow(
        self,
        hypothesis_id: str, run_name: str, params: dict, metrics: dict,
        sharpe_analysis: dict, cpcv_results: dict, overfit_diagnostics: dict,
        strategy_risk: dict, impl_shortfall: dict, mc_pnl: dict | None,
        validation_results: dict, verdict: str, verdict_rationale: str,
        missing_outputs: list,
    ) -> str:
        all_metrics = self._build_primary_metrics(metrics, sharpe_analysis, cpcv_results)

        with mlflow.start_run(run_name=run_name) as run:
            # Tags
            mlflow.set_tag('hypothesis_id', hypothesis_id)
            mlflow.set_tag('verdict', verdict)
            mlflow.set_tag('is_failure_archive_entry', str(verdict == 'NO_GO'))
            mlflow.set_tag('engine_version', _ENGINE_VERSION)
            mlflow.set_tag('logged_at', datetime.now(timezone.utc).isoformat())
            mlflow.set_tag(
                'completeness',
                'COMPLETE' if not missing_outputs else 'INCOMPLETE',
            )
            if missing_outputs:
                # Truncate to MLflow tag value limit (5000 chars)
                mlflow.set_tag('missing_outputs', ', '.join(missing_outputs)[:5000])

            # Params — MLflow requires scalar values; serialise nested structures
            flat_params = {
                k: (
                    json.dumps(v)
                    if not isinstance(v, (str, int, float, bool))
                    else v
                )
                for k, v in (params or {}).items()
            }
            mlflow.log_params(flat_params)

            # Metrics (DSR is primary — DD-11 means PBO is diagnostic only)
            mlflow.log_metrics(all_metrics)

            # Artefacts (all twelve non-negotiable outputs)
            mlflow.log_dict(sharpe_analysis or {},      'sharpe_analysis.json')
            mlflow.log_dict(cpcv_results or {},         'cpcv_results.json')
            mlflow.log_dict(overfit_diagnostics or {},  'overfit_diagnostics.json')
            mlflow.log_dict(strategy_risk or {},        'strategy_risk.json')
            mlflow.log_dict(impl_shortfall or {},       'impl_shortfall.json')
            mlflow.log_dict(validation_results or {},   'validation_results.json')
            if mc_pnl is not None:
                mlflow.log_dict(mc_pnl, 'mc_pnl.json')
            mlflow.log_text(verdict_rationale, 'verdict_rationale.txt')

            return run.info.run_id

    def _log_fallback(
        self,
        hypothesis_id: str, run_name: str, params: dict, metrics: dict,
        sharpe_analysis: dict, cpcv_results: dict, overfit_diagnostics: dict,
        strategy_risk: dict, impl_shortfall: dict, mc_pnl: dict | None,
        validation_results: dict, verdict: str, verdict_rationale: str,
        missing_outputs: list,
    ) -> str:
        """Write JSON artefacts to disk when MLflow is unavailable."""
        import uuid
        run_id = str(uuid.uuid4())
        run_dir = self._fallback_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        all_metrics = self._build_primary_metrics(metrics, sharpe_analysis, cpcv_results)

        summary = {
            'run_id':          run_id,
            'run_name':        run_name,
            'hypothesis_id':   hypothesis_id,
            'verdict':         verdict,
            'engine_version':  _ENGINE_VERSION,
            'logged_at':       datetime.now(timezone.utc).isoformat(),
            'completeness':    'COMPLETE' if not missing_outputs else 'INCOMPLETE',
            'missing_outputs': missing_outputs,
            'params':          params or {},
            'metrics':         all_metrics,
        }

        artefacts: dict[str, Any] = {
            'run_summary':         summary,
            'sharpe_analysis':     sharpe_analysis or {},
            'cpcv_results':        cpcv_results or {},
            'overfit_diagnostics': overfit_diagnostics or {},
            'strategy_risk':       strategy_risk or {},
            'impl_shortfall':      impl_shortfall or {},
            'validation_results':  validation_results or {},
        }
        if mc_pnl is not None:
            artefacts['mc_pnl'] = mc_pnl

        for name, data in artefacts.items():
            with (run_dir / f'{name}.json').open('w') as f:
                json.dump(data, f, indent=2, default=_json_default)

        (run_dir / 'verdict_rationale.txt').write_text(verdict_rationale)
        return run_id

    def _list_mlflow(self, verdict_filter: str | None, max_results: int) -> list[dict]:
        try:
            runs = mlflow.search_runs(
                experiment_names=[MLFLOW_EXPERIMENT_NAME],
                filter_string=(
                    f"tags.verdict = '{verdict_filter}'" if verdict_filter else ''
                ),
                max_results=max_results,
                output_format='list',
            )
        except Exception:
            return []

        return [
            {
                'run_id':        r.info.run_id,
                'run_name':      r.info.run_name,
                'verdict':       r.data.tags.get('verdict', 'UNKNOWN'),
                'hypothesis_id': r.data.tags.get('hypothesis_id', ''),
                'dsr_primary':   r.data.metrics.get('dsr_primary'),
                'production_sr': r.data.metrics.get('production_haircut_sr'),
                'logged_at':     r.data.tags.get('logged_at', ''),
                'completeness':  r.data.tags.get('completeness', 'UNKNOWN'),
            }
            for r in runs
        ]

    def _list_fallback(self, verdict_filter: str | None, max_results: int) -> list[dict]:
        result = []
        try:
            dirs = sorted(
                self._fallback_dir.iterdir(),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
        except FileNotFoundError:
            return []

        for run_dir in dirs:
            summary_path = run_dir / 'run_summary.json'
            if not summary_path.exists():
                continue
            with summary_path.open() as f:
                s = json.load(f)
            if verdict_filter and s.get('verdict') != verdict_filter:
                continue
            result.append({
                'run_id':        s.get('run_id', ''),
                'run_name':      s.get('run_name', ''),
                'verdict':       s.get('verdict', 'UNKNOWN'),
                'hypothesis_id': s.get('hypothesis_id', ''),
                'dsr_primary':   s.get('metrics', {}).get('dsr_primary'),
                'production_sr': s.get('metrics', {}).get('production_haircut_sr'),
                'logged_at':     s.get('logged_at', ''),
                'completeness':  s.get('completeness', 'UNKNOWN'),
            })
            if len(result) >= max_results:
                break
        return result


# ── Helpers ───────────────────────────────────────────────────────────────────

def _json_default(obj: Any) -> Any:
    """JSON serialisation fallback for numpy scalars, datetimes, etc."""
    try:
        import numpy as np
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
    except ImportError:
        pass
    if hasattr(obj, 'isoformat'):
        return obj.isoformat()
    return str(obj)


def verdict_summary(
    sharpe_analysis: dict,
    cpcv_results: dict,
    overfit_diagnostics: dict,
    impl_shortfall_gate: dict,
) -> dict:
    """
    Produce a structured verdict summary from the four key gate outputs.

    This is a convenience function for the research_pipeline orchestrator.
    It codifies the process gates from Architecture v2.0 into a single
    dict.  The researcher makes the final call; this function surfaces
    which gates passed and failed.

    Parameters
    ----------
    sharpe_analysis : dict
        Output of SharpeEstimationPipeline.full_analysis().
    cpcv_results : dict
        Output of CPCV.compute_path_sharpes().
    overfit_diagnostics : dict
        Output of OverfitDiagnostics.full_report().
    impl_shortfall_gate : dict
        Output of ImplementationShortfall.gate_check().

    Returns
    -------
    dict with:
        suggested_verdict : 'GO' or 'NO_GO'
        gates_passed      : list[str]
        gates_failed      : list[str]
        rationale         : str
    """
    gates_passed: list[str] = []
    gates_failed: list[str] = []
    notes: list[str] = []

    # Gate 1: DSR > threshold
    dsr = (sharpe_analysis or {}).get('dsr_primary')
    if dsr is not None:
        if dsr > BACKTEST_DSR_ACCEPT_THRESHOLD:
            gates_passed.append(f'DSR={dsr:.3f} > {BACKTEST_DSR_ACCEPT_THRESHOLD}')
        else:
            gates_failed.append(f'DSR={dsr:.3f} ≤ {BACKTEST_DSR_ACCEPT_THRESHOLD}')
            notes.append(f'DSR {dsr:.3f} does not meet threshold.')
    else:
        gates_failed.append('DSR not computed')
        notes.append('sharpe_analysis incomplete.')

    # Gate 2: production haircut viability
    viable = (sharpe_analysis or {}).get('viable_after_haircut')
    prod_sr = (sharpe_analysis or {}).get('production_haircut_sr')
    if viable is True:
        gates_passed.append(
            f'production haircut SR={prod_sr:.3f} > {BACKTEST_MIN_VIABLE_HAIRCUT_SR}'
        )
    elif viable is False:
        gates_failed.append(
            f'production haircut SR={prod_sr:.3f} ≤ {BACKTEST_MIN_VIABLE_HAIRCUT_SR}'
        )
        notes.append('Production haircut SR below viable threshold.')
    else:
        gates_failed.append('viability not computed')

    # Gate 3: PBO < 0.05
    pbo = (cpcv_results or {}).get('pbo')
    if pbo is not None:
        if pbo < 0.05:
            gates_passed.append(f'PBO={pbo:.3f} < 0.05')
        else:
            gates_failed.append(f'PBO={pbo:.3f} ≥ 0.05')
            notes.append(f'PBO {pbo:.3f} ≥ 0.05 — overfit signal.')
    else:
        gates_failed.append('PBO not computed')

    # Gate 4: overfit diagnostics verdict
    ov = (overfit_diagnostics or {}).get('verdict', '')
    if ov in ('NO_OVERFIT_SIGNAL', 'LOW_OVERFIT_SIGNAL'):
        gates_passed.append(f'overfit_verdict={ov}')
    elif ov:
        gates_failed.append(f'overfit_verdict={ov}')
        notes.append(f'Overfit diagnostics: {ov}.')
    else:
        gates_failed.append('overfit diagnostics not computed')

    # Gate 5: implementation shortfall
    if impl_shortfall_gate:
        msg = impl_shortfall_gate.get('message', '')
        if impl_shortfall_gate.get('passes'):
            gates_passed.append(msg or 'IS gate passed')
        else:
            gates_failed.append(msg or 'IS gate failed')
            notes.append('Implementation shortfall gate failed.')
    else:
        gates_failed.append('impl_shortfall gate not run')

    suggested = 'GO' if not gates_failed else 'NO_GO'
    rationale = (
        f'{len(gates_passed)} gate(s) passed, {len(gates_failed)} failed.  '
        + '  '.join(notes)
    ).strip()

    return {
        'suggested_verdict': suggested,
        'gates_passed':      gates_passed,
        'gates_failed':      gates_failed,
        'rationale':         rationale,
    }
