"""
Layer 5c: Overfitting diagnostics — PBO + three companion statistics.

PBO alone is insufficient to characterise overfitting. All four statistics
must be reported together:
  1. PBO               — from CPCV output (cpcv.py)
  2. Performance degradation regression (β) — this module
  3. Probability of OOS loss — this module
  4. Stochastic dominance (KS test) — this module

Design decisions encoded here:
- DD-11: PBO is DIAGNOSTIC ONLY. This module does not expose any function
  that accepts PBO as an input to an optimisation loop, loss function, or
  selection criterion. All functions here are post-hoc diagnostics.

Ref: Bailey et al. 2014, Section 3.
Architecture v2.0 Layer 5c.
"""

import numpy as np
from scipy import stats


class OverfitDiagnostics:
    """
    Four complementary overfitting diagnostics.

    All methods are static — they operate on arrays of IS and OOS
    Sharpe ratios produced by CPCV (Layer 5b). None of these methods
    should be called within an optimisation loop; they are post-hoc
    diagnostics on finalised strategies.

    Usage
    -----
    After running CPCV:
        cpcv_result = cpcv.compute_path_sharpes(returns)
        is_sr  = cpcv_result['path_sharpes']  # or separate IS array
        oos_sr = cpcv_result['path_sharpes']

        deg = OverfitDiagnostics.performance_degradation(is_sr, oos_sr)
        pol = OverfitDiagnostics.probability_of_loss(oos_sr)
        dom = OverfitDiagnostics.stochastic_dominance(oos_sr, random_baseline)
        # PBO comes from cpcv_result['pbo']

    All four outputs should be logged together in the research run.
    Ref: Architecture v2.0 Non-Negotiable Output #9.
    """

    @staticmethod
    def performance_degradation(is_sharpes: np.ndarray,
                                oos_sharpes: np.ndarray) -> dict:
        """
        Regression of OOS performance on IS performance.

        A negative slope (β < 0) is an overfit signal: strategies that
        look better in-sample tend to perform worse out-of-sample. This
        is the hallmark of selection bias — the optimiser found noise,
        not signal.

        Parameters
        ----------
        is_sharpes : np.ndarray
            In-sample Sharpe ratios from each CPCV split.
        oos_sharpes : np.ndarray
            Out-of-sample Sharpe ratios from corresponding CPCV splits.

        Returns
        -------
        dict with:
            beta          : OLS slope (negative = overfit signal)
            alpha         : OLS intercept
            r_squared     : R² of the regression
            p_value       : two-tailed p-value for the slope
            interpretation: plain-language summary

        Ref: Bailey et al. 2014, Section 3.2.
        """
        if len(is_sharpes) < 3 or len(oos_sharpes) < 3:
            return {
                'beta': float('nan'),
                'alpha': float('nan'),
                'r_squared': float('nan'),
                'p_value': float('nan'),
                'interpretation': 'Insufficient data for regression (n < 3).',
            }

        slope, intercept, r_value, p_value, std_err = stats.linregress(
            is_sharpes, oos_sharpes
        )

        if slope < 0:
            interp = (
                f'β={slope:.3f} < 0: higher IS performance predicts lower OOS '
                'performance. Overfit signal — the strategy may be fitting noise. '
                'Ref: Bailey et al. 2014, Section 3.2.'
            )
        else:
            interp = (
                f'β={slope:.3f} ≥ 0: IS/OOS relationship is not inverted. '
                'No overfit signal from this diagnostic alone.'
            )

        return {
            'beta': float(slope),
            'alpha': float(intercept),
            'r_squared': float(r_value ** 2),
            'p_value': float(p_value),
            'interpretation': interp,
        }

    @staticmethod
    def probability_of_loss(oos_sharpes: np.ndarray) -> float:
        """
        Probability that the strategy loses money out-of-sample.

        P[OOS Sharpe < 0] computed empirically from the CPCV path
        distribution. A high value (> 0.5) indicates the strategy
        loses more often than it profits across backtested paths.

        Parameters
        ----------
        oos_sharpes : np.ndarray
            Array of OOS Sharpe ratios from CPCV paths.

        Returns
        -------
        float in [0, 1]

        Ref: Bailey et al. 2014, Section 3.2.
        """
        if len(oos_sharpes) == 0:
            return float('nan')
        return float((oos_sharpes < 0).mean())

    @staticmethod
    def stochastic_dominance(oos_selected: np.ndarray,
                             oos_random: np.ndarray) -> dict:
        """
        Does IS-optimal selection stochastically dominate random selection OOS?

        If the optimisation process provides genuine value, the IS-optimal
        strategy selection should produce higher OOS returns than random
        selection from the same strategy pool. A one-sided KS test assesses
        whether the IS-optimal OOS distribution is stochastically greater.

        If it does NOT dominate (p ≥ 0.05), the optimisation process provided
        no benefit over random selection — a strong overfit indicator.

        Parameters
        ----------
        oos_selected : np.ndarray
            OOS Sharpes for the IS-optimal selected strategies.
        oos_random : np.ndarray
            OOS Sharpes for randomly selected strategies (baseline).

        Returns
        -------
        dict with:
            ks_statistic  : KS test statistic
            p_value       : one-sided p-value (H1: selected > random)
            dominates     : bool — True if p_value < 0.05
            interpretation: plain-language summary

        Ref: Bailey et al. 2014, Section 3.3.
        """
        if len(oos_selected) == 0 or len(oos_random) == 0:
            return {
                'ks_statistic': float('nan'),
                'p_value': float('nan'),
                'dominates': False,
                'interpretation': 'Insufficient data for stochastic dominance test.',
            }

        ks_stat, ks_pvalue = stats.ks_2samp(
            oos_selected, oos_random, alternative='greater'
        )

        if ks_pvalue < 0.05:
            interp = (
                f'KS={ks_stat:.3f}, p={ks_pvalue:.4f}: IS-optimal selection '
                'stochastically dominates random selection at 5% significance. '
                'The optimisation process provided value OOS.'
            )
        else:
            interp = (
                f'KS={ks_stat:.3f}, p={ks_pvalue:.4f}: IS-optimal selection does '
                'NOT stochastically dominate random selection OOS. The optimisation '
                'process provided no detectable value. Strong overfit signal. '
                'Ref: Bailey et al. 2014, Section 3.3.'
            )

        return {
            'ks_statistic': float(ks_stat),
            'p_value': float(ks_pvalue),
            'dominates': ks_pvalue < 0.05,
            'interpretation': interp,
        }

    @staticmethod
    def full_report(is_sharpes: np.ndarray,
                    oos_sharpes: np.ndarray,
                    pbo: float,
                    oos_random: np.ndarray = None) -> dict:
        """
        Convenience method: compute all four overfit statistics together.

        PBO is passed in from CPCV output (not recomputed here — DD-11).
        Stochastic dominance requires a random OOS baseline; if not provided,
        it is computed by shuffling oos_sharpes.

        Parameters
        ----------
        is_sharpes : np.ndarray
        oos_sharpes : np.ndarray
        pbo : float
            PBO from CPCV._compute_pbo(). Passed in, not re-derived here.
        oos_random : np.ndarray, optional
            Random-selection OOS baseline for stochastic dominance test.
            If None, generated by permuting oos_sharpes.

        Returns
        -------
        dict with all four diagnostic results plus a summary verdict.
        """
        if oos_random is None:
            rng = np.random.default_rng(seed=42)
            oos_random = rng.permutation(oos_sharpes)

        deg = OverfitDiagnostics.performance_degradation(is_sharpes, oos_sharpes)
        pol = OverfitDiagnostics.probability_of_loss(oos_sharpes)
        dom = OverfitDiagnostics.stochastic_dominance(oos_sharpes, oos_random)

        # Tally overfit signals
        overfit_signals = 0
        if not np.isnan(deg['beta']) and deg['beta'] < 0:
            overfit_signals += 1
        if not np.isnan(pol) and pol > 0.5:
            overfit_signals += 1
        if not dom['dominates']:
            overfit_signals += 1
        if not np.isnan(pbo) and pbo > 0.05:
            overfit_signals += 1

        if overfit_signals >= 3:
            verdict = 'HIGH_OVERFIT_RISK'
        elif overfit_signals == 2:
            verdict = 'MODERATE_OVERFIT_RISK'
        elif overfit_signals == 1:
            verdict = 'LOW_OVERFIT_SIGNAL'
        else:
            verdict = 'NO_OVERFIT_SIGNAL'

        return {
            'pbo': pbo,
            'performance_degradation': deg,
            'probability_of_loss': pol,
            'stochastic_dominance': dom,
            'overfit_signals_count': overfit_signals,
            'verdict': verdict,
        }
