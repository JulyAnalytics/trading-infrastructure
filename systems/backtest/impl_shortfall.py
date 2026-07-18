"""
Layer 7a: Implementation Shortfall — four required production metrics.
Layer 7c: Production haircut and viability check.

Before any strategy is handed to Jordan for production simulation, the trade
log from the backtest must produce all four of these metrics.  A strategy
that clears the Sharpe and DSR gates but fails here has an edge that is
consumed by execution costs.

The four metrics (AFML Ch.14, pp.202-203):
  1. Broker fees per unit of turnover
  2. Average slippage per unit of turnover
  3. Dollar P&L per unit of turnover
  4. Return on execution costs  (net P&L / total execution costs)

Design decisions encoded here:
- DD-10: Three-level cost decomposition (option entry/exit → Level 1,
  hedge trade costs → Level 2, cumulative hedge drag → Level 3) is
  OptionsBacktester's responsibility.  This module consumes the completed
  trade_log and measures aggregate cost impact.  Optional 'hedge_cost'
  field in each log entry enables Level 3 attribution.
- The production haircut (OOS × 0.50) and viability threshold (haircut > 0.5)
  are constants from config.  Values are not duplicated here.

Ref: LdP AFML Ch.14, pp.202-203; Architecture v2.0 Layers 7a/7c.
"""

from __future__ import annotations

import math

from config import BACKTEST_PRODUCTION_HAIRCUT, BACKTEST_MIN_VIABLE_HAIRCUT_SR


class ImplementationShortfall:
    """
    Four required metrics before any production decision.
    Operates on a completed trade_log — each entry is a dict describing
    one round-trip trade.

    Required trade_log keys per entry:
      - turnover      : gross notional traded (absolute value)
      - broker_fee    : broker commission for this trade
      - slippage_cost : realised slippage cost for this trade
      - net_pnl       : net P&L after all costs for this trade

    Optional:
      - hedge_cost    : cumulative hedge trade cost over the trade's life
                        (Level 3 of the DD-10 decomposition).  Used for
                        hedge drag attribution; zero-filled when absent.

    Ref: LdP AFML Ch.14, pp.202-203; Architecture v2.0 Layer 7a.
    """

    @staticmethod
    def compute(trade_log: list) -> dict:
        """
        Compute the four implementation shortfall metrics from a trade log.

        Returns
        -------
        dict with keys:
            broker_fees_per_turnover      — Metric 1
            avg_slippage_per_turnover     — Metric 2
            dollar_pnl_per_turnover       — Metric 3
            return_on_execution_costs     — Metric 4 (primary gate metric)
            hedge_drag_pct_of_exec_costs  — Level 3 DD-10 attribution
            n_trades                      — trade count
            total_turnover / fees / slippage / exec_cost / net_pnl / hedge_cost
            interpretation                — plain-language assessment

        An empty trade_log returns an empty dict — caller is responsible
        for checking before interpreting results.
        """
        if not trade_log:
            return {}

        total_turnover   = sum(abs(t.get('turnover', 0.0))    for t in trade_log)
        total_fees       = sum(t.get('broker_fee', 0.0)        for t in trade_log)
        total_slippage   = sum(t.get('slippage_cost', 0.0)     for t in trade_log)
        total_pnl        = sum(t.get('net_pnl', 0.0)           for t in trade_log)
        total_hedge_cost = sum(t.get('hedge_cost', 0.0)        for t in trade_log)
        total_exec_cost  = total_fees + total_slippage
        n_trades         = len(trade_log)

        # ── Four required metrics ─────────────────────────────────────────────
        broker_fees_per_turnover = (
            total_fees / total_turnover if total_turnover > 0 else 0.0
        )
        avg_slippage_per_turnover = (
            total_slippage / total_turnover if total_turnover > 0 else 0.0
        )
        dollar_pnl_per_turnover = (
            total_pnl / total_turnover if total_turnover > 0 else 0.0
        )
        return_on_exec_costs = (
            total_pnl / total_exec_cost if total_exec_cost > 0 else float('inf')
        )

        # ── Level 3: hedge drag as fraction of total execution cost ───────────
        hedge_drag_pct = (
            total_hedge_cost / total_exec_cost if total_exec_cost > 0 else 0.0
        )

        # ── Interpretation ────────────────────────────────────────────────────
        if not math.isfinite(return_on_exec_costs):
            interp = (
                'Execution costs are zero (simulation artefact or costs not '
                'logged).  Verify that broker_fee and slippage_cost are '
                'populated in the trade log.'
            )
        elif return_on_exec_costs >= 5.0:
            interp = (
                f'Return on execution costs = {return_on_exec_costs:.1f}×.  '
                'Strong: execution costs are a small fraction of edge.  '
                'Strategy should survive realistic execution deterioration.'
            )
        elif return_on_exec_costs >= 2.0:
            interp = (
                f'Return on execution costs = {return_on_exec_costs:.1f}×.  '
                'Adequate: some margin for worse-than-expected execution, '
                'but monitor fills carefully in live trading.'
            )
        elif return_on_exec_costs >= 1.0:
            interp = (
                f'Return on execution costs = {return_on_exec_costs:.1f}×.  '
                'Thin: execution costs consume a large fraction of edge.  '
                'Small fill deterioration could make the strategy unprofitable.  '
                'Ref: AFML Ch.14 — "return on execution costs should be a large multiple."'
            )
        else:
            interp = (
                f'Return on execution costs = {return_on_exec_costs:.1f}×.  '
                'FAIL: execution costs exceed P&L.  Strategy is not viable '
                'at these cost assumptions.  Review cost model or position sizing.'
            )

        return {
            # Four required metrics
            'broker_fees_per_turnover':     round(broker_fees_per_turnover,  8),
            'avg_slippage_per_turnover':    round(avg_slippage_per_turnover, 8),
            'dollar_pnl_per_turnover':      round(dollar_pnl_per_turnover,   8),
            'return_on_execution_costs': (
                round(return_on_exec_costs, 4)
                if math.isfinite(return_on_exec_costs) else float('inf')
            ),
            # Level 3 hedge drag attribution (DD-10)
            'hedge_drag_pct_of_exec_costs': round(hedge_drag_pct, 4),
            # Totals (audit trail)
            'n_trades':          n_trades,
            'total_turnover':    round(total_turnover,    4),
            'total_fees':        round(total_fees,        4),
            'total_slippage':    round(total_slippage,    4),
            'total_exec_cost':   round(total_exec_cost,   4),
            'total_net_pnl':     round(total_pnl,         4),
            'total_hedge_cost':  round(total_hedge_cost,  4),
            # Per-trade averages
            'avg_pnl_per_trade':       round(total_pnl / n_trades,        4),
            'avg_exec_cost_per_trade': round(total_exec_cost / n_trades,  4),
            'interpretation':          interp,
        }

    @staticmethod
    def gate_check(result: dict,
                   min_return_on_exec_costs: float = 2.0) -> dict:
        """
        Production gate check on the output of ImplementationShortfall.compute().

        A strategy must pass this gate before being handed to Jordan.
        The default threshold of 2× is conservative — AFML implies
        "large multiple" without specifying a number; 2× is the minimum
        that provides a meaningful buffer for live execution deterioration.

        Parameters
        ----------
        result : dict
            Output of ImplementationShortfall.compute().
        min_return_on_exec_costs : float
            Minimum acceptable return_on_execution_costs.  Default 2.0.

        Returns
        -------
        dict with: passes (bool), metric (float), threshold (float), message (str).
        """
        if not result:
            return {
                'passes':    False,
                'metric':    None,
                'threshold': min_return_on_exec_costs,
                'message':   'IS gate FAIL: empty trade log.',
            }

        metric = result.get('return_on_execution_costs')
        if metric is None:
            return {
                'passes':    False,
                'metric':    None,
                'threshold': min_return_on_exec_costs,
                'message':   'IS gate FAIL: return_on_execution_costs not computed.',
            }

        if not math.isfinite(metric):
            return {
                'passes':    False,
                'metric':    float('inf'),
                'threshold': min_return_on_exec_costs,
                'message': (
                    'IS gate WARN: execution costs are zero.  '
                    'Verify cost model before production decision.'
                ),
            }

        passes = metric >= min_return_on_exec_costs
        return {
            'passes':    passes,
            'metric':    metric,
            'threshold': min_return_on_exec_costs,
            'message': (
                f'IS gate {"PASS" if passes else "FAIL"}: '
                f'return on execution costs = {metric:.2f}× '
                f'(threshold {min_return_on_exec_costs:.1f}×).'
            ),
        }


# ── Layer 7b/7c: Production haircut helpers ───────────────────────────────────

def production_haircut(oos_sharpe: float) -> float:
    """
    Apply the standard production haircut to an OOS Sharpe ratio.
    Haircut fraction is BACKTEST_PRODUCTION_HAIRCUT from config (currently 0.50).

    This is the number used for the production viability decision.
    Ref: Architecture v2.0 Layer 7c.
    """
    return oos_sharpe * BACKTEST_PRODUCTION_HAIRCUT


def viable_after_haircut(oos_sharpe: float) -> bool:
    """
    Return True if the haircutted Sharpe clears the minimum viable threshold.
    Threshold is BACKTEST_MIN_VIABLE_HAIRCUT_SR from config (currently 0.5).

    A False result means the strategy should be archived, not forwarded to Jordan.
    Ref: Architecture v2.0 Layer 7c.
    """
    return production_haircut(oos_sharpe) > BACKTEST_MIN_VIABLE_HAIRCUT_SR
