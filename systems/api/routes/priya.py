"""
Priya research workbench API — hypothesis registration (gate 1 in the UI),
data-audit runner, backtest configurator (sweep → full Stage 5-8 pipeline),
verdict view, failure-archive browser, and the gates display.

Reads are read-only (deps helpers). Writes are the registry insert on
hypothesis registration (short-lived, Jordan-book pattern) plus the research
run itself, which writes MLflow files and the registry trial counter — not a
DuckDB pipeline table, so it is safe to run inside the request. A full run
(CPCV + 1000-permutation test) takes ~10-60s; the frontend sets a generous
timeout and shows progress state.
"""
from __future__ import annotations

import json
import warnings
from pathlib import Path

from fastapi import APIRouter, Body, HTTPException

from systems.api.deps import macro_conn, trading_conn, rows_as_dicts

router = APIRouter(prefix="/api/priya", tags=["priya"])


def _py(v):
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and v != v:
        return None
    return v


def _to_native(o):
    if isinstance(o, dict):
        return {k: _to_native(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [_to_native(v) for v in o]
    return _py(o)


# ── Hypotheses (Stage 0 — pre-registration gate) ─────────────────────────────

@router.get("/hypotheses")
def hypotheses() -> dict:
    conn = trading_conn()
    try:
        rel = conn.execute("""
            SELECT hypothesis_id, hypothesis, dataset_id, signal_type,
                   rationale, registered_at, trial_count
            FROM hypothesis_registry ORDER BY registered_at DESC
        """)
        rows = rows_as_dicts(rel)
    except Exception:
        rows = []  # registry table not created yet
    finally:
        conn.close()
    return {"hypotheses": rows}


@router.post("/hypotheses")
def register_hypothesis(body: dict = Body(...)) -> dict:
    from systems.backtest.hypothesis_registry import HypothesisRegistration
    required = ("hypothesis", "dataset_id", "signal_type", "rationale")
    missing = [f for f in required if not body.get(f)]
    if missing:
        raise HTTPException(422, f"missing fields: {missing} — the rationale "
                            "is the pre-registration discipline, not paperwork")
    hid = HypothesisRegistration().register(
        hypothesis=body["hypothesis"], dataset_id=body["dataset_id"],
        signal_type=body["signal_type"], rationale=body["rationale"],
    )
    return {"hypothesis_id": hid}


# ── Data audit runner (Stage 1 gate) ─────────────────────────────────────────

@router.post("/data-audit")
def data_audit(body: dict = Body(...)) -> dict:
    """Body: {ticker, days?=1008}. Fetches OHLC via yfinance and runs the
    full audit (blockers stop the pipeline; flags are warnings)."""
    from systems.backtest.data_audit import DataAuditReport

    ticker = str(body.get("ticker", "")).upper()
    if not ticker:
        raise HTTPException(422, "ticker required")
    days = int(body.get("days", 1008))

    try:
        import yfinance as yf
        df = yf.Ticker(ticker).history(period=f"{days}d")
    except Exception as e:
        raise HTTPException(502, f"price fetch failed: {e}")
    if df is None or df.empty:
        raise HTTPException(502, f"no price history for {ticker}")
    df = df.rename(columns=str.lower)
    df.index = df.index.tz_localize(None)   # audit engine expects naive daily bars

    audit = DataAuditReport()
    audit.set_bar_type("time")
    report = audit.run_full_audit(df, label=f"{ticker} {days}d yfinance")
    report["n_rows"] = int(len(df))
    report["start"] = str(df.index[0])[:10]
    report["end"] = str(df.index[-1])[:10]
    return _to_native(report)


# ── Signal builders for the configurator ─────────────────────────────────────

def _signal_momentum(returns, window: int = 20, **_):
    import numpy as np
    return returns.rolling(int(window)).mean().apply(
        lambda x: 1.0 if x > 0 else (-1.0 if x < 0 else 0.0))


def _signal_mean_reversion(returns, window: int = 20, z_entry: float = 1.0, **_):
    mean = returns.rolling(int(window)).mean()
    std = returns.rolling(int(window)).std()
    z = (returns - mean) / std
    return z.apply(lambda v: -1.0 if v > float(z_entry)
                   else (1.0 if v < -float(z_entry) else 0.0))


SIGNALS = {
    "momentum": {
        "func": _signal_momentum,
        "params": {"window": 20},
        "help": "sign of rolling mean return over `window` days",
    },
    "mean_reversion": {
        "func": _signal_mean_reversion,
        "params": {"window": 20, "z_entry": 1.0},
        "help": "fade daily-return z-scores beyond ±z_entry over `window` days",
    },
}


@router.get("/signals")
def signal_types() -> dict:
    return {"signals": {k: {"params": v["params"], "help": v["help"]}
                        for k, v in SIGNALS.items()}}


def _regime_series():
    """Marcus regime labels from macro.db as a date-indexed Series."""
    import pandas as pd
    conn = macro_conn()
    try:
        df = conn.execute(
            "SELECT date, regime FROM regime_history ORDER BY date").fetchdf()
    finally:
        conn.close()
    if df.empty:
        return None
    df["date"] = pd.to_datetime(df["date"])
    return df.set_index("date")["regime"]


# ── The configurator: sweep → full Stage 5-8 pipeline ────────────────────────

@router.post("/run")
def run_research(body: dict = Body(...)) -> dict:
    """
    Body: {hypothesis_id, ticker, signal_type, params?, sweep?, cost_bps?,
           days?}. `sweep` maps param name → list of values; a single config
    is a 1-point sweep (so the trial counter always increments — G4-1).
    Runs: price fetch → sweep (trials recorded) → best config → trade log
    (G4-2) → ResearchPipeline (n_trials auto from registry) → verdict.
    A failed process gate returns 200 with `gate_failed` — that outcome is
    the product working, not an error.
    """
    import numpy as np
    import pandas as pd
    from systems.backtest.hypothesis_registry import HypothesisRegistration
    from systems.backtest.research_pipeline import (
        PipelineGateError, ResearchPipeline,
    )
    from systems.backtest.vectorized_engine import VectorizedBacktester

    hid = body.get("hypothesis_id")
    ticker = str(body.get("ticker", "")).upper()
    stype = body.get("signal_type")
    if not hid or not ticker or stype not in SIGNALS:
        raise HTTPException(
            422, f"need hypothesis_id, ticker, signal_type in {list(SIGNALS)}")

    reg = HypothesisRegistration()
    hyp = reg.get(hid)
    if hyp is None:
        raise HTTPException(404, f"hypothesis '{hid}' not registered — "
                            "pre-registration is gate 1")

    days = int(body.get("days", 1008))
    cost_bps = float(body.get("cost_bps", 10.0))

    try:
        import yfinance as yf
        close = yf.Ticker(ticker).history(period=f"{days}d")["Close"]
    except Exception as e:
        raise HTTPException(502, f"price fetch failed: {e}")
    if close is None or len(close) < 260:
        raise HTTPException(
            502, f"insufficient history for {ticker} "
            f"({0 if close is None else len(close)} rows; need 260+)")
    close.index = close.index.tz_localize(None)
    returns = close.pct_change().dropna()

    spec = SIGNALS[stype]
    base = {**spec["params"], **(body.get("params") or {})}
    sweep_grid = body.get("sweep") or {k: [v] for k, v in base.items()}
    # normalise: every param present, lists of scalars
    for k, v in base.items():
        sweep_grid.setdefault(k, [v])
    sweep_grid = {k: (v if isinstance(v, list) else [v])
                  for k, v in sweep_grid.items()}

    captured: "list[str]" = []
    with warnings.catch_warnings(record=True) as wlist:
        warnings.simplefilter("always")

        bt = VectorizedBacktester(
            signal=returns * 0.0, returns=returns, cost_bps=cost_bps)
        sweep_df = bt.parameter_sweep(
            sweep_grid, spec["func"], label_prefix=f"{ticker}-{stype}-",
            dataset_id=hyp["dataset_id"],
        )
        if sweep_df.empty:
            raise HTTPException(500, "sweep produced no results — signal_func "
                                "failed for every combination")

        best = sweep_df.iloc[0]
        best_params = {k: _py(best[k]) for k in sweep_grid}

        sig = spec["func"](returns, **best_params)
        bt_best = VectorizedBacktester(
            signal=sig, returns=returns, cost_bps=cost_bps)
        single = bt_best.run_single(label=f"{ticker}-{stype}-best")
        trade_log = bt_best.build_trade_log(single)

        pipeline = ResearchPipeline(hypothesis_id=hid)   # n_trials auto (G4-1)
        gate_failed = None
        result = None
        try:
            result = pipeline.run_equity(
                returns=single["strategy_returns"],
                trade_log=trade_log,
                params={**best_params, "ticker": ticker, "signal_type": stype,
                        "cost_bps": cost_bps},
                run_name=f"{ticker}-{stype}",
                regime_series=_regime_series(),
            )
        except PipelineGateError as e:
            gate_failed = str(e)

        captured = sorted({str(w.message) for w in wlist})

    sweep_records = _to_native(
        sweep_df.drop(columns=[c for c in ("viable_after_haircut",)
                               if c not in sweep_grid], errors="ignore")
        .head(25).to_dict(orient="records"))

    out = {
        "hypothesis_id": hid,
        "ticker": ticker,
        "signal_type": stype,
        "best_params": best_params,
        "n_trials_used": pipeline.n_trials,
        "sweep": sweep_records,
        "single_run": _to_native({k: single[k] for k in (
            "sharpe_annual", "sharpe_is", "sharpe_oos", "degradation_ratio",
            "production_haircut_sr", "viable_after_haircut", "max_drawdown",
            "hit_rate", "n_trades", "cost_drag_annual", "total_return")}),
        "n_trade_log_entries": len(trade_log),
        "warnings": captured,
        "gate_failed": gate_failed,
        "data_note": f"{ticker} {len(returns)}d yfinance daily closes — "
                     "research-grade only.",
    }

    if result is not None:
        sa = result["sharpe_analysis"]
        out["pipeline"] = _to_native({
            "run_id": result["run_id"],
            "verdict": result["verdict"],
            "suggested_verdict": result["suggested_verdict"],
            "verdict_rationale": result["verdict_rationale"],
            "gates_passed": result["gates_passed"],
            "gates_failed": result["gates_failed"],
            "dsr": sa.get("dsr_primary"),
            "sr_annual": sa.get("sr_annual"),
            "production_haircut_sr": sa.get("production_haircut_sr"),
            "viable_after_haircut": sa.get("viable_after_haircut"),
            "n_eff": sa.get("n_eff"),
            "min_track_record_years": sa.get("min_track_record_years"),
            "ljung_box_pvalue": sa.get("ljung_box_pvalue"),
            "pbo": result["cpcv_results"].get("pbo"),
            "cpcv_path_sharpes": result["cpcv_results"].get("path_sharpes"),
            "regime_conditional_sharpes":
                result["validation_results"].get("regime_conditional_sharpes"),
            "permutation_p": result["permutation_test"].get("p_value"),
            "impl_shortfall": {
                k: result["impl_shortfall"].get(k) for k in (
                    "return_on_execution_costs", "dollar_pnl_per_turnover",
                    "n_trades", "total_exec_cost", "total_net_pnl")
            } if result["impl_shortfall"] else None,
            "strategy_risk_prob_failure":
                result.get("strategy_risk_prob_failure"),
        })

    return out


# ── Verdict + archive + gates ────────────────────────────────────────────────

@router.get("/verdict")
def current_verdict() -> dict:
    from config import OUTPUTS_DIR
    fp = Path(OUTPUTS_DIR) / "research_verdict.json"
    if not fp.exists():
        raise HTTPException(404, "research_verdict.json not written yet")
    return json.loads(fp.read_text())


@router.get("/runs")
def archive(verdict: "str | None" = None, limit: int = 50) -> dict:
    from systems.backtest.experiment_tracker import ResearchTracker
    if verdict not in (None, "GO", "NO_GO"):
        raise HTTPException(422, "verdict must be GO or NO_GO")
    runs = ResearchTracker().list_runs(verdict_filter=verdict,
                                       max_results=limit)
    return {"runs": _to_native(runs),
            "note": "NO_GO runs are the failure archive — negative results "
                    "are retained deliberately (is_failure_archive_entry)."}


_GATE_FIELDS = (
    "backtest_pbo_reject_threshold",
    "backtest_dsr_accept_threshold",
    "backtest_production_haircut",
    "backtest_min_viable_haircut_sr",
    "backtest_default_significance",
    "sharpe_autocorr_pvalue_threshold",
)


@router.get("/gates")
def gates() -> dict:
    from systems.params import get_params
    from systems.params.models import PriyaParams
    p = get_params("priya")
    out = []
    for f in _GATE_FIELDS:
        spec = PriyaParams.FIELD_SPECS.get(f, {})
        out.append({
            "field": f,
            "value": getattr(p, f),
            "label": spec.get("label", f),
            "help": spec.get("help"),
            "guarded": bool(spec.get("guarded")),
        })
    return {
        "gates": out,
        "note": ("Gates are registry parameters — edit on the Parameters page. "
                 "Guarded fields log loudly and stamp their hash on every "
                 "verdict produced under the changed gate; relaxing a gate to "
                 "get a GO is visible forever in the run record."),
    }
