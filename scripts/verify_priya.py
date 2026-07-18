"""
Priya synthetic end-to-end verification.

Generates synthetic price data and runs the full ResearchPipeline.run_equity()
workflow.  Verifies all 10 equity non-negotiable outputs are present and that
an MLflow (or fallback JSON) run is logged.

Run from the repo root:
    python scripts/verify_priya.py

Expected output:
    All gates pass (or produce expected warnings for weak synthetic data).
    All 10 equity outputs present.
    MLflow / fallback run logged.
"""

import sys
import os
import warnings

# Ensure repo root is on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd

from systems.backtest.hypothesis_registry import HypothesisRegistration
from systems.backtest.research_pipeline import ResearchPipeline, validate_outputs, NON_NEGOTIABLE_OUTPUTS

# ── 1. Pre-register a test hypothesis ─────────────────────────────────────────

reg = HypothesisRegistration()
DATASET_ID    = 'SYNTH_VERIFY_DATASET'

HYPOTHESIS_ID = reg.register(
    hypothesis='Synthetic verification: momentum signal on simulated returns',
    dataset_id=DATASET_ID,
    signal_type='momentum',
    rationale='End-to-end smoke test using synthetic data — not a real research hypothesis.',
)
print(f'Hypothesis ID: {HYPOTHESIS_ID}')

# ── 2. Generate synthetic data ─────────────────────────────────────────────────

np.random.seed(42)
N = 504  # 2 years of daily data
dates = pd.date_range('2023-01-02', periods=N, freq='B')

# Returns: mild positive drift with noise
returns = pd.Series(
    np.random.normal(0.0003, 0.010, N),
    index=dates,
    name='returns',
)

# Signal: lagged sign of returns (momentum proxy — deliberately weak)
raw_signal = returns.shift(1).fillna(0)
signal = raw_signal.apply(lambda x: 1 if x > 0 else -1).astype(float)

# Regime series: alternating regimes
regime_labels = ['RISK_ON_LOW_VOL', 'NEUTRAL', 'CAUTION', 'RISK_OFF_STRESS']
regime_series = pd.Series(
    [regime_labels[i % len(regime_labels)] for i in range(N)],
    index=dates,
    name='regime',
)

print(f'\nSynthetic data: {N} observations from {dates[0].date()} to {dates[-1].date()}')
print(f'Returns mean={returns.mean():.4f}, std={returns.std():.4f}')

# ── 3. Instantiate and run the pipeline ───────────────────────────────────────

print('\nInstantiating ResearchPipeline...')
pipeline = ResearchPipeline(
    hypothesis_id=HYPOTHESIS_ID,
    n_trials=1,
    allow_continue=True,   # weak synthetic data will trigger gate warnings — that's expected
)

print('Running equity signal pipeline...')
with warnings.catch_warnings(record=True) as caught_warnings:
    warnings.simplefilter('always')
    result = pipeline.run_equity(
        returns=returns,
        trade_log=[],   # no trade log for synthetic run
        params={'signal_type': 'momentum_lag1', 'dataset': 'synthetic'},
        run_name='verify_priya_synthetic',
        regime_series=regime_series,
        additional_metrics={'synthetic_run': 1},
    )

# ── 4. Report gate warnings ───────────────────────────────────────────────────

gate_warnings = [w for w in caught_warnings if issubclass(w.category, UserWarning)]
if gate_warnings:
    print(f'\nGate warnings ({len(gate_warnings)}) — expected for weak synthetic data:')
    for w in gate_warnings:
        print(f'  ⚠  {w.message}')

# ── 5. Validate outputs ───────────────────────────────────────────────────────

missing = validate_outputs(result, is_options=False)

print('\n── Output validation ────────────────────────────────────────')
all_equity_outputs = [k for k in NON_NEGOTIABLE_OUTPUTS if k not in ('mc_pnl_distribution', 'three_level_cost_decomposition')]
for key in all_equity_outputs:
    present = bool(result.get(key))
    status = '✓' if present else '✗ MISSING'
    print(f'  {status}  {key}')

if missing:
    print(f'\nFAIL — {len(missing)} missing outputs: {missing}')
    sys.exit(1)

print(f'\nPASS — all {len(all_equity_outputs)} equity non-negotiable outputs present')

# ── 6. Verify MLflow / fallback run logged ───────────────────────────────────

run_id = result.get('run_id')
if not run_id:
    print('FAIL — no run_id returned (MLflow / fallback logging failed)')
    sys.exit(1)

print(f'\nMLflow / fallback run logged: run_id={run_id}')
print(f'Verdict: {result["verdict"]}')
print(f'Gates passed: {result["gates_passed"]}')
print(f'Gates failed: {result["gates_failed"]}')

# ── 7. Verify Jordan output contract ─────────────────────────────────────────

from pathlib import Path
from config import OUTPUTS_DIR
import json

contract_path = Path(OUTPUTS_DIR) / 'research_verdict.json'
if not contract_path.exists():
    print('FAIL — research_verdict.json was not written')
    sys.exit(1)

contract = json.loads(contract_path.read_text())
required_keys = [
    'hypothesis_id', 'strategy_type', 'verdict',
    'production_haircut_sharpe', 'viable_after_haircut',
    'pbo', 'dsr', 'written_at',
]
missing_keys = [k for k in required_keys if k not in contract]
if missing_keys:
    print(f'FAIL — Jordan contract missing keys: {missing_keys}')
    sys.exit(1)

print(f'\nJordan contract written: {contract_path}')
print(f'  hypothesis_id={contract["hypothesis_id"]}')
print(f'  verdict={contract["verdict"]}')
print(f'  dsr={contract["dsr"]}')
print(f'  production_haircut_sharpe={contract["production_haircut_sharpe"]}')

print('\n' + '='*60)
print('VERIFY_PRIYA PASS — synthetic end-to-end complete')
print('='*60)
