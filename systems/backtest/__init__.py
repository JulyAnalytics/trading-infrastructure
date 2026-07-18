"""
systems/backtest — Priya's backtesting engine (Phase 3).

Layers:
  Layer 1: DataAuditReport        — data_audit.py
  Layer 2: HypothesisRegistration — hypothesis_registry.py
  Layer 3: Feature engineering    — feature_engineering.py, vol_estimators.py
  Layer 4: Execution engines      — vectorized_engine.py, options_engine.py,
                                     label_construction.py
  Layer 5: Cross-validation       — purged_cv.py, cpcv.py, overfit_statistics.py
  Layer 6: Statistical validation — sharpe_pipeline.py, strategy_risk.py
  Layer 7: Production simulation  — impl_shortfall.py
  Layer 8: Experiment tracking    — experiment_tracker.py
  Orchestrator                    — research_pipeline.py

Ensure the hypothesis_registry table exists on first import.
"""

from systems.backtest.hypothesis_registry import initialize_hypothesis_schema
from systems.backtest.impl_shortfall import (
    ImplementationShortfall,
    production_haircut,
    viable_after_haircut,
)
from systems.backtest.experiment_tracker import ResearchTracker, verdict_summary
from systems.backtest.research_pipeline import ResearchPipeline, PipelineGateError

initialize_hypothesis_schema()

__all__ = [
    'ImplementationShortfall',
    'production_haircut',
    'viable_after_haircut',
    'ResearchTracker',
    'verdict_summary',
    'ResearchPipeline',
    'PipelineGateError',
]
