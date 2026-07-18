"""
Layer 6c: Strategy Risk — P[precision < breakeven], binomial precision model.

Strategy risk is distinct from portfolio risk. It asks: given the observed
precision p of this strategy's bets, what is the probability that the true
precision falls below the breakeven level p* required to cover costs?

This is the last gate before any strategy is handed to Jordan for production
simulation. A strategy that clears the Sharpe and DSR gates but fails here
has an edge too fragile to rely on.

Design decisions encoded here:
- The binomial precision model is used rather than a Gaussian approximation
  because bet counts in backtests are small (O(100–1000)), where the
  Gaussian CDF is unreliable.
- Asymmetric payoffs are the default for options strategies. The symmetric
  shortcut is available but should not be used for short-vol or spread trades.

Ref: LdP AFML Ch.15, pp.211-218; Architecture v2.0 Layer 6c.
"""

import numpy as np
from scipy.stats import binom, norm


class StrategyRisk:
    """
    Binomial precision model for strategy risk assessment.

    All methods are static — they operate on summary statistics
    (precision p, trade count n, payoff parameters π⁺/π⁻).

    Usage
    -----
    After collecting the trade log from a backtest:

        n_trades  = len(trade_log)
        n_wins    = sum(1 for t in trade_log if t['pnl'] > 0)
        p_obs     = n_wins / n_trades
        pi_pos    = mean win P&L
        pi_neg    = mean loss P&L  (negative number)

        risk = StrategyRisk.full_report(p_obs, n_trades, pi_neg, pi_pos)

    The primary output is `prob_failure` — P[p < p*]. Strategies with
    prob_failure > 0.10 should not advance to production simulation.
    """

    @staticmethod
    def breakeven_precision(pi_neg: float, pi_pos: float) -> float:
        """
        Minimum precision required for expected P&L ≥ 0.

        p* = -π⁻ / (π⁺ - π⁻)

        For a strategy with win rate p, average win π⁺, average loss π⁻:
          E[P&L] = p·π⁺ + (1-p)·π⁻ = 0  ⟹  p* = -π⁻ / (π⁺ - π⁻)

        Parameters
        ----------
        pi_neg : float — mean loss per losing trade (must be negative)
        pi_pos : float — mean win per winning trade (must be positive)

        Returns
        -------
        float in (0, 1) — breakeven precision
        """
        if pi_pos <= 0:
            raise ValueError(f'pi_pos must be positive, got {pi_pos}')
        if pi_neg >= 0:
            raise ValueError(f'pi_neg must be negative, got {pi_neg}')
        if pi_pos - pi_neg == 0:
            raise ValueError('pi_pos - pi_neg must be non-zero')

        return float(-pi_neg / (pi_pos - pi_neg))

    @staticmethod
    def prob_failure(p: float, n: int,
                     pi_neg: float, pi_pos: float) -> float:
        """
        P[strategy precision < breakeven precision].

        Uses binomial CDF. The null is that the strategy's true precision
        equals the observed p. We compute the probability that fewer than
        p*·n wins are observed in n independent bets.

        A high value (> 0.10) means the edge is too fragile: even if the
        observed precision is correct, sampling variation can push the
        strategy below breakeven with material probability.

        Parameters
        ----------
        p      : float — observed win rate (0, 1)
        n      : int   — number of trades in the backtest
        pi_neg : float — mean loss per losing trade (negative)
        pi_pos : float — mean win per winning trade (positive)

        Returns
        -------
        float in [0, 1]

        Ref: LdP AFML Snippet 15.5.
        """
        p_star = StrategyRisk.breakeven_precision(pi_neg, pi_pos)
        k_threshold = int(np.ceil(p_star * n))
        return float(binom.cdf(k_threshold, n, p))

    @staticmethod
    def implied_precision(target_sharpe: float, n: int,
                          symmetric: bool = True) -> float:
        """
        Minimum precision required to achieve target_sharpe with n trades.

        Symmetric case (equal payoffs):
          θ = (2p - 1) / (2√(p(1-p))) · √n = target_sharpe
          Solving for p:
          p = ½ · (1 + √(1 - n / (θ² + n)))

        This gives the hurdle win rate needed for the strategy to be viable.

        Parameters
        ----------
        target_sharpe : float — annualized Sharpe target
        n             : int   — number of bets per year
        symmetric     : bool  — if False, precision is undefined without
                                payoff parameters; raises NotImplementedError.

        Returns
        -------
        float in (0.5, 1.0) — required precision

        Ref: LdP AFML Ch.15, Eq.15.2.
        """
        if not symmetric:
            raise NotImplementedError(
                'Asymmetric implied_precision requires payoff parameters. '
                'Compute analytically from breakeven_precision and '
                'sharpe_from_precision for your specific π⁺/π⁻.'
            )
        theta = target_sharpe
        denom = theta ** 2 + n
        if denom == 0:
            return 0.5
        inner = 1.0 - n / denom
        if inner < 0:
            return 0.5
        return float(0.5 * (1.0 + np.sqrt(inner)))

    @staticmethod
    def sharpe_from_precision(p: float, n: int,
                              pi_neg: float = None,
                              pi_pos: float = None) -> float:
        """
        Annualized Sharpe implied by bet precision p with n bets per year.

        Symmetric case (π⁺ = |π⁻|):
          SR = (2p - 1) / (2√(p(1-p))) · √n

        Asymmetric case (options, spreads):
          SR = [(π⁺ - π⁻)·p + π⁻] / [(π⁺ - π⁻)·√(p(1-p))] · √n

        Parameters
        ----------
        p      : float — win rate in (0, 1)
        n      : int   — number of bets per year
        pi_neg : float, optional — mean loss (negative); required for asymmetric
        pi_pos : float, optional — mean win (positive); required for asymmetric

        Returns
        -------
        float — annualized Sharpe ratio

        Ref: LdP AFML Ch.15, Eq.15.2 (symmetric) and Eq.15.3 (asymmetric).
        """
        if p <= 0 or p >= 1:
            return 0.0

        std_p = np.sqrt(p * (1.0 - p))
        if std_p == 0:
            return 0.0

        if pi_neg is not None and pi_pos is not None:
            # Asymmetric payoff
            payoff_range = pi_pos - pi_neg
            mean_pnl = payoff_range * p + pi_neg
            std_pnl = payoff_range * std_p
            if std_pnl == 0:
                return 0.0
            return float(mean_pnl / std_pnl * np.sqrt(n))
        else:
            # Symmetric case
            return float((2.0 * p - 1.0) / (2.0 * std_p) * np.sqrt(n))

    @staticmethod
    def precision_confidence_interval(p: float, n: int,
                                      confidence: float = 0.95) -> tuple:
        """
        Wilson score confidence interval for observed precision p with n bets.

        The Wilson interval is used rather than the Wald interval because
        it performs well at extreme proportions and small n.

        Parameters
        ----------
        p          : float — observed win rate
        n          : int   — total number of bets
        confidence : float — confidence level (default 0.95)

        Returns
        -------
        (lower, upper) : tuple of floats
        """
        z = float(norm.ppf(1.0 - (1.0 - confidence) / 2.0))
        n = float(n)
        denominator = 1.0 + z ** 2 / n
        centre = (p + z ** 2 / (2.0 * n)) / denominator
        margin = z * np.sqrt(p * (1.0 - p) / n + z ** 2 / (4.0 * n ** 2)) / denominator
        return (max(0.0, float(centre - margin)), min(1.0, float(centre + margin)))

    @staticmethod
    def full_report(p: float, n: int,
                    pi_neg: float, pi_pos: float,
                    target_sharpe: float = 0.5) -> dict:
        """
        Complete strategy risk report.

        Parameters
        ----------
        p             : float — observed win rate
        n             : int   — number of trades in backtest
        pi_neg        : float — mean loss per losing trade (negative)
        pi_pos        : float — mean win per winning trade (positive)
        target_sharpe : float — Sharpe hurdle for implied_precision check

        Returns
        -------
        dict with all strategy risk diagnostics.
        """
        p_star = StrategyRisk.breakeven_precision(pi_neg, pi_pos)
        pf = StrategyRisk.prob_failure(p, n, pi_neg, pi_pos)
        sr_implied = StrategyRisk.sharpe_from_precision(p, n, pi_neg, pi_pos)
        p_required = StrategyRisk.implied_precision(target_sharpe, n)
        ci_lower, ci_upper = StrategyRisk.precision_confidence_interval(p, n)

        edge_above_breakeven = p - p_star
        ci_lower_above_breakeven = ci_lower > p_star

        if pf < 0.01:
            verdict = 'ROBUST_EDGE'
        elif pf < 0.05:
            verdict = 'ADEQUATE_EDGE'
        elif pf < 0.10:
            verdict = 'FRAGILE_EDGE'
        else:
            verdict = 'INSUFFICIENT_EDGE'

        return {
            'observed_precision': round(p, 4),
            'n_trades': n,
            'breakeven_precision': round(p_star, 4),
            'edge_above_breakeven': round(edge_above_breakeven, 4),
            'precision_ci_95': (round(ci_lower, 4), round(ci_upper, 4)),
            'ci_lower_above_breakeven': bool(ci_lower_above_breakeven),
            'prob_failure': round(pf, 6),
            'sharpe_from_precision': round(sr_implied, 4),
            'required_precision_for_sharpe_target': round(p_required, 4),
            'target_sharpe': target_sharpe,
            'verdict': verdict,
            'verdict_rationale': (
                f'P[p < p*={p_star:.3f}] = {pf:.4f}. '
                f'Observed precision {p:.3f} is {edge_above_breakeven:+.3f} '
                f'above breakeven. '
                f'95% CI: ({ci_lower:.3f}, {ci_upper:.3f}). '
                f'Verdict: {verdict}.'
            ),
            'pi_pos': pi_pos,
            'pi_neg': pi_neg,
        }
