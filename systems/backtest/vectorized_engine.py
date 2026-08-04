"""
Layer 4a: Vectorized Backtest Engine — equity/index signal research.

Fast, vectorized parameter sweeps over a signal Series against a return
Series. Designed for initial hypothesis validation before committing to
the path-dependent options engine (Layer 4b).

Key outputs per the architecture v2.0 non-negotiable requirements:
  - Regime-conditional Sharpe table (required before any IS conclusion)
  - Parameter sensitivity surface (±20% sweep; median Sharpe is the result)
  - Degradation ratio (IS vs. OOS)
  - Production haircut Sharpe (OOS × 0.50)

Design decisions:
  - Walk-forward split is the single-path OOS estimate; it is labeled as such
    and superseded by CPCV in Layer 5. Both are produced.
  - _flag_overfitting() warns when Sharpe variance across the sweep is high
    relative to its mean (CV > BACKTEST_OVERFITTING_SHARPE_CV_THRESHOLD).
    High CV means the reported Sharpe depends critically on the exact parameter
    choice — the peak is likely a fluke.
  - regime_conditional_analysis() is mandatory before any in-sample conclusion.
    A signal that fails in any recurring regime is a regime bet, not an edge.

Architecture ref: v2.0 Layer 4a.
"""

import warnings
from itertools import product
from typing import Callable, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from config import (
    BACKTEST_DEFAULT_SIGNIFICANCE,
    BACKTEST_OVERFITTING_SHARPE_CV_THRESHOLD,
    BACKTEST_PRODUCTION_HAIRCUT,
    BACKTEST_MIN_VIABLE_HAIRCUT_SR,
    BACKTEST_SWEEP_MIN_POINTS,
)


class VectorizedBacktester:
    """
    Vectorized equity/index signal backtester.

    Accepts a signal Series and a returns Series. The signal is a position
    series: values should be in {-1, 0, +1} or continuous weights. A
    signal value at time t is applied to the return at time t+1 (one-bar
    execution lag is enforced via apply_shift).

    Usage::

        bt = VectorizedBacktester(signal=signal, returns=returns)
        result = bt.run_single()

        sweep_results = bt.parameter_sweep(
            param_grid={'window': [10, 20, 30, 40, 60]},
            signal_func=lambda returns, window: compute_signal(returns, window),
        )

        regime_table = bt.regime_conditional_analysis(
            regime_series=regime_series,
        )
    """

    def __init__(
        self,
        signal: pd.Series,
        returns: pd.Series,
        cost_bps: float = 10.0,
        oos_fraction: float = 0.3,
    ):
        """
        Parameters
        ----------
        signal : pd.Series
            Position signal. DatetimeIndex, aligned to returns.
            Values in {-1, 0, +1} or continuous weights.
            Must NOT be pre-shifted — apply_shift() enforces the lag.
        returns : pd.Series
            Arithmetic or log returns of the underlying. DatetimeIndex.
        cost_bps : float
            Round-trip transaction cost in basis points applied on every
            position change (|Δsignal| > 0). Default 10 bps.
        oos_fraction : float
            Fraction of the data reserved as OOS for walk-forward.
            Default 0.30 (last 30%).
        """
        self.signal = signal
        self.returns = returns
        self.cost_bps = cost_bps / 10_000.0
        self.oos_fraction = oos_fraction

        # Align on intersection
        common = signal.index.intersection(returns.index)
        if len(common) == 0:
            raise ValueError(
                "signal and returns share no common index dates. "
                "Verify that both are DatetimeIndex-aligned."
            )
        self._signal = signal.reindex(common)
        self._returns = returns.reindex(common)
        self._T = len(common)

    # ── Public API ─────────────────────────────────────────────────────────────

    def run_single(
        self,
        signal: Optional[pd.Series] = None,
        returns: Optional[pd.Series] = None,
        label: str = '',
    ) -> dict:
        """
        Run a single backtest on the provided (or constructor) signal/returns.

        Enforces the one-bar execution lag, computes strategy returns net of
        transaction costs, and returns a metrics dict.

        Parameters
        ----------
        signal : pd.Series, optional
            Override the constructor signal for this run.
        returns : pd.Series, optional
            Override the constructor returns for this run.
        label : str
            Human-readable label for this run (logged in output dict).

        Returns
        -------
        dict with keys:
            label, n_obs, sharpe_annual, sharpe_is, sharpe_oos,
            degradation_ratio, production_haircut_sr, viable_after_haircut,
            total_return, ann_return, ann_vol, max_drawdown,
            hit_rate, avg_win, avg_loss, profit_factor,
            n_trades, turnover_annual, cost_drag_annual,
            strategy_returns (pd.Series), equity_curve (pd.Series)
        """
        sig, ret = self._resolve_inputs(signal, returns)
        sig = self.apply_shift(sig)
        sig, ret = self._align(sig, ret)

        strat_ret = self._strategy_returns(sig, ret)
        split = int(len(strat_ret) * (1 - self.oos_fraction))

        is_ret = strat_ret.iloc[:split]
        oos_ret = strat_ret.iloc[split:]

        sharpe_is = self._sharpe(is_ret)
        sharpe_oos = self._sharpe(oos_ret)
        sharpe_full = self._sharpe(strat_ret)

        degradation = (
            (sharpe_is - sharpe_oos) / abs(sharpe_is)
            if sharpe_is != 0 else float('nan')
        )
        haircut_sr = sharpe_oos * BACKTEST_PRODUCTION_HAIRCUT

        equity = (1 + strat_ret).cumprod()
        max_dd = self._max_drawdown(equity)

        wins = strat_ret[strat_ret > 0]
        losses = strat_ret[strat_ret < 0]
        profit_factor = (
            wins.sum() / abs(losses.sum())
            if losses.sum() != 0 else float('inf')
        )

        turnover = sig.diff().abs().sum() / len(sig)
        cost_drag = turnover * self.cost_bps * 252

        return {
            'label': label,
            'n_obs': len(strat_ret),
            'sharpe_annual': sharpe_full,
            'sharpe_is': sharpe_is,
            'sharpe_oos': sharpe_oos,
            'degradation_ratio': degradation,
            'production_haircut_sr': haircut_sr,
            'viable_after_haircut': haircut_sr > BACKTEST_MIN_VIABLE_HAIRCUT_SR,
            'total_return': float(equity.iloc[-1] - 1),
            'ann_return': float(strat_ret.mean() * 252),
            'ann_vol': float(strat_ret.std() * np.sqrt(252)),
            'max_drawdown': max_dd,
            'hit_rate': float((strat_ret > 0).mean()),
            'avg_win': float(wins.mean()) if len(wins) > 0 else 0.0,
            'avg_loss': float(losses.mean()) if len(losses) > 0 else 0.0,
            'profit_factor': profit_factor,
            'n_trades': int(sig.diff().abs().gt(0).sum()),
            'turnover_annual': float(turnover * 252),
            'cost_drag_annual': cost_drag,
            'strategy_returns': strat_ret,
            'equity_curve': equity,
            # Aligned post-shift inputs, kept so build_trade_log() (G4-2) can
            # decompose the run into trades without re-deriving the alignment.
            'signal_used': sig,
            'returns_used': ret,
        }

    def build_trade_log(
        self,
        result: dict,
        notional: float = 10_000.0,
        fee_fraction: float = 0.3,
    ) -> list:
        """
        G4-2: build an ImplementationShortfall-format trade log from a
        run_single() result — the automated path from vectorized results to
        `trade_log` that audit #4 flagged as missing.

        One entry per contiguous non-zero position block. Per-bar cost
        (|Δsignal| × cost_bps) is attributed to the trade being closed when
        one is open, else to the trade being opened, so summed trade costs
        equal the costs inside strategy_returns exactly.

        fee_fraction splits the single cost_bps assumption into broker_fee
        vs slippage_cost (yfinance backtests have no separate fill data —
        the split is an assumption, not a measurement; documented here and
        in the IS output).

        Keys per trade: entry_date, exit_date, direction, bars_held,
        turnover, broker_fee, slippage_cost, gross_pnl, net_pnl, hedge_cost.
        """
        sig = result.get('signal_used')
        ret = result.get('returns_used')
        if sig is None or ret is None:
            raise ValueError(
                'result lacks signal_used/returns_used — pass a run_single() '
                'result produced by this version of the engine.'
            )
        sig = sig.fillna(0.0)
        ret = ret.reindex(sig.index).fillna(0.0)

        trades: list[dict] = []
        open_trade: "dict | None" = None
        prev_pos = 0.0

        def close(trade: dict, exit_date) -> None:
            fees = trade['_cost'] * fee_fraction
            slip = trade['_cost'] - fees
            trades.append({
                'entry_date':    str(trade['entry_date'])[:10],
                'exit_date':     str(exit_date)[:10],
                'direction':     'long' if trade['position'] > 0 else 'short',
                'bars_held':     trade['bars'],
                'turnover':      round(trade['_turnover'], 2),
                'broker_fee':    round(fees, 4),
                'slippage_cost': round(slip, 4),
                'gross_pnl':     round(trade['_gross'], 4),
                'net_pnl':       round(trade['_gross'] - trade['_cost'], 4),
                'hedge_cost':    0.0,   # delta-one equity — no hedge leg
            })

        for date, pos in sig.items():
            change = pos - prev_pos
            if change != 0:
                cost = abs(change) * self.cost_bps * notional
                turn = abs(change) * notional
                if open_trade is not None:
                    open_trade['_cost'] += cost
                    open_trade['_turnover'] += turn
                    close(open_trade, date)
                    open_trade = None
                    cost = turn = 0.0   # consumed by the closing trade
                if pos != 0:
                    open_trade = {
                        'entry_date': date, 'position': float(pos),
                        'bars': 0, '_gross': 0.0,
                        '_cost': cost, '_turnover': turn,
                    }
            if open_trade is not None and pos != 0:
                open_trade['_gross'] += float(pos * ret.loc[date]) * notional
                open_trade['bars'] += 1
            prev_pos = pos

        if open_trade is not None:
            close(open_trade, sig.index[-1])
        return trades

    def parameter_sweep(
        self,
        param_grid: Dict[str, List],
        signal_func: Callable[..., pd.Series],
        label_prefix: str = '',
        dataset_id: Optional[str] = None,
    ) -> pd.DataFrame:
        """
        Sweep over a parameter grid, run a backtest for each combination,
        and return a summary DataFrame sorted by OOS Sharpe descending.

        Calls _flag_overfitting() on the resulting Sharpe distribution and
        logs a warning if Sharpe variance is high relative to the mean.

        Parameters
        ----------
        param_grid : dict
            Keys are parameter names; values are lists of values to try.
            Example: {'window': [10, 20, 30], 'threshold': [0.5, 1.0]}
        signal_func : callable
            Function with signature signal_func(returns, **params) → pd.Series.
            Receives self._returns and the current parameter combination.
        label_prefix : str
            Prepended to each result's label for identification.
        dataset_id : str, optional
            G4-1: when provided, every evaluated combination increments the
            hypothesis registry's trial counter for this dataset, so DSR's
            n_trials reflects the sweep automatically instead of relying on
            the researcher remembering to call increment_trial_count().

        Returns
        -------
        pd.DataFrame with columns:
            all param names, sharpe_annual, sharpe_is, sharpe_oos,
            degradation_ratio, production_haircut_sr, viable_after_haircut,
            max_drawdown, hit_rate, n_trades, cost_drag_annual.
        Sorted by sharpe_oos descending. Best row = index 0.
        """
        param_names = list(param_grid.keys())
        param_values = list(param_grid.values())
        combinations = list(product(*param_values))

        rows = []
        for combo in combinations:
            params = dict(zip(param_names, combo))
            try:
                sig = signal_func(self._returns, **params)
            except Exception as exc:
                warnings.warn(
                    f"parameter_sweep: signal_func failed for {params}: {exc}",
                    stacklevel=2,
                )
                continue

            label = label_prefix + ','.join(f'{k}={v}' for k, v in params.items())
            result = self.run_single(signal=sig, label=label)

            row = {**params}
            for key in (
                'sharpe_annual', 'sharpe_is', 'sharpe_oos',
                'degradation_ratio', 'production_haircut_sr',
                'viable_after_haircut', 'max_drawdown', 'hit_rate',
                'n_trades', 'cost_drag_annual',
            ):
                row[key] = result[key]
            rows.append(row)

        if not rows:
            return pd.DataFrame()

        if dataset_id:
            try:
                from systems.backtest.hypothesis_registry import (
                    HypothesisRegistration,
                )
                reg = HypothesisRegistration()
                for _ in rows:
                    n = reg.increment_trial_count(dataset_id)
                warnings.warn(
                    f'parameter_sweep: {len(rows)} trials recorded against '
                    f'dataset {dataset_id} (total now {n}).',
                    stacklevel=2,
                )
            except Exception as exc:
                warnings.warn(
                    f'parameter_sweep: trial-count auto-increment failed '
                    f'({exc}) — record {len(rows)} trials manually or DSR '
                    'will be overstated.',
                    stacklevel=2,
                )

        df = pd.DataFrame(rows).sort_values('sharpe_oos', ascending=False)
        df = df.reset_index(drop=True)

        self._flag_overfitting(df['sharpe_oos'].values, param_names)
        return df

    def regime_conditional_analysis(
        self,
        regime_series: pd.Series,
        signal: Optional[pd.Series] = None,
        returns: Optional[pd.Series] = None,
        min_obs_per_regime: int = 30,
    ) -> pd.DataFrame:
        """
        Compute Sharpe, hit rate, and trade count stratified by macro regime.

        This is mandatory before drawing any in-sample conclusion. A signal
        that fails in any recurring regime is a regime bet, not an edge.

        Parameters
        ----------
        regime_series : pd.Series
            Regime label series. DatetimeIndex, same frequency as returns.
            Values are strings, e.g. 'RISK_ON_LOW_VOL', 'RISK_OFF_HIGH_VOL'.
        signal : pd.Series, optional
            Override constructor signal.
        returns : pd.Series, optional
            Override constructor returns.
        min_obs_per_regime : int
            Regimes with fewer observations than this are reported but flagged
            as insufficient for statistical conclusions.

        Returns
        -------
        pd.DataFrame indexed by regime label, columns:
            n_obs, sharpe_annual, ann_return, ann_vol,
            hit_rate, avg_win, avg_loss, profit_factor,
            pct_of_total, sufficient_obs.
        Sorted by sharpe_annual descending.
        """
        sig, ret = self._resolve_inputs(signal, returns)
        sig = self.apply_shift(sig)
        sig, ret = self._align(sig, ret)
        strat_ret = self._strategy_returns(sig, ret)

        # Align regime to strategy return index
        regime_aligned = regime_series.reindex(strat_ret.index, method='ffill')

        regimes = regime_aligned.dropna().unique()
        rows = []
        for regime in regimes:
            mask = regime_aligned == regime
            r = strat_ret[mask]
            if len(r) == 0:
                continue

            wins = r[r > 0]
            losses = r[r < 0]
            profit_factor = (
                wins.sum() / abs(losses.sum())
                if losses.sum() != 0 else float('inf')
            )

            rows.append({
                'regime': regime,
                'n_obs': len(r),
                'sharpe_annual': self._sharpe(r),
                'ann_return': float(r.mean() * 252),
                'ann_vol': float(r.std() * np.sqrt(252)),
                'hit_rate': float((r > 0).mean()),
                'avg_win': float(wins.mean()) if len(wins) > 0 else 0.0,
                'avg_loss': float(losses.mean()) if len(losses) > 0 else 0.0,
                'profit_factor': profit_factor,
                'pct_of_total': float(len(r) / len(strat_ret)),
                'sufficient_obs': len(r) >= min_obs_per_regime,
            })

        if not rows:
            return pd.DataFrame()

        df = (
            pd.DataFrame(rows)
            .set_index('regime')
            .sort_values('sharpe_annual', ascending=False)
        )

        # Warn on regimes where signal underperforms
        failing = df[(df['sharpe_annual'] < 0) & df['sufficient_obs']]
        if not failing.empty:
            regime_list = ', '.join(failing.index.tolist())
            warnings.warn(
                f"Regime-conditional analysis: signal has negative Sharpe in "
                f"regime(s) [{regime_list}]. This is a regime bet, not a "
                f"general edge. Do not proceed to OOS without addressing this.",
                stacklevel=2,
            )

        return df

    # ── Internal methods ───────────────────────────────────────────────────────

    @staticmethod
    def apply_shift(signal: pd.Series, periods: int = 1) -> pd.Series:
        """
        Enforce the execution lag: signal at t is applied to return at t+1.

        This is a one-way gate — calling apply_shift on an already-shifted
        signal would double-shift. The caller is responsible for not passing
        a pre-shifted signal to run_single() or parameter_sweep().
        """
        return signal.shift(periods)

    def _flag_overfitting(
        self,
        sharpe_values: np.ndarray,
        param_names: List[str],
    ) -> None:
        """
        Warn when Sharpe variance across a parameter sweep is high relative
        to its mean. High coefficient of variation (std/mean) means the
        result is sensitive to the exact parameter choice — the peak Sharpe
        is likely a fluke of the specific parameter combination, not a robust
        signal.

        Threshold: BACKTEST_OVERFITTING_SHARPE_CV_THRESHOLD (default 0.5).
        Only applied when the sweep has >= BACKTEST_SWEEP_MIN_POINTS results.
        """
        valid = sharpe_values[np.isfinite(sharpe_values)]
        if len(valid) < BACKTEST_SWEEP_MIN_POINTS:
            return

        mean_sr = np.mean(valid)
        std_sr = np.std(valid)

        if mean_sr == 0:
            return

        cv = std_sr / abs(mean_sr)
        if cv > BACKTEST_OVERFITTING_SHARPE_CV_THRESHOLD:
            warnings.warn(
                f"Overfitting flag: Sharpe CV across {len(valid)} parameter "
                f"combinations = {cv:.2f} (threshold {BACKTEST_OVERFITTING_SHARPE_CV_THRESHOLD}). "
                f"Parameters swept: {param_names}. "
                f"Sharpe range: [{valid.min():.2f}, {valid.max():.2f}], "
                f"median: {np.median(valid):.2f}. "
                "The median Sharpe, not the peak, is the research finding. "
                "High variance signals the strategy is not robust to parameter choice.",
                stacklevel=3,
            )

    def _strategy_returns(
        self,
        signal: pd.Series,
        returns: pd.Series,
    ) -> pd.Series:
        """
        Compute net strategy returns: signal × returns minus transaction costs.
        Costs are applied on every bar where the position changes.
        """
        raw = signal * returns
        # Cost is applied whenever the position changes
        position_change = signal.diff().abs()
        cost = position_change * self.cost_bps
        return (raw - cost).dropna()

    def _sharpe(self, returns: pd.Series, annualization: int = 252) -> float:
        """Annualized Sharpe ratio. Returns 0.0 if vol is zero or series is empty."""
        if len(returns) < 2:
            return 0.0
        std = returns.std()
        if std == 0:
            return 0.0
        return float(returns.mean() / std * np.sqrt(annualization))

    def _max_drawdown(self, equity_curve: pd.Series) -> float:
        """Maximum peak-to-trough drawdown as a positive fraction."""
        roll_max = equity_curve.cummax()
        drawdown = (equity_curve - roll_max) / roll_max
        return float(drawdown.min())

    def _resolve_inputs(
        self,
        signal: Optional[pd.Series],
        returns: Optional[pd.Series],
    ) -> Tuple[pd.Series, pd.Series]:
        sig = signal if signal is not None else self._signal
        ret = returns if returns is not None else self._returns
        return sig, ret

    @staticmethod
    def _align(
        signal: pd.Series,
        returns: pd.Series,
    ) -> Tuple[pd.Series, pd.Series]:
        common = signal.index.intersection(returns.index)
        return signal.reindex(common), returns.reindex(common)
