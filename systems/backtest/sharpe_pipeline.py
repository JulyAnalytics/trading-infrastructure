"""
Layer 6a: Sharpe Estimation Pipeline — Lo (2002) SE + PSR/DSR (LdP AFML Ch.14).

Every Sharpe ratio produced by this engine is accompanied by:
  1. Serial correlation diagnostic (Ljung-Box Q-statistic)
  2. Standard error and 95% CI — GMM/Newey-West if autocorrelated, IID if not
  3. Autocorrelation-adjusted annualization η(q) if needed (Lo 2002 Eq. 20)
  4. PSR — probability the true SR exceeds a benchmark, corrected for
     skewness and kurtosis (non-normality)
  5. DSR — PSR with benchmark set to the expected max SR from N independent
     trials on zero-edge data (multiple-testing correction)
  6. Minimum track record length
  7. Production haircut and viability flag

A bare Sharpe without these is incomplete output. Ref: Architecture v2.0 Layer 6a.

Design decisions encoded here:
- DD-02: Two-stage pipeline. Stage 1: Lo serial correlation diagnostic +
  robust SE. Stage 2: PSR/DSR on non-annualized SR. Applied independently.
- DD-06: Never use √q as default annualization. Ljung-Box first; branch
  to η(q) if autocorrelated, √q only if clean (and report both).
- DD-12: Both literal N (trial count) and N_eff (eigenvalue method) are
  reported. DSR is computed for both; more conservative is flagged primary.

Ref: Lo (2002); LdP AFML Ch.14, pp.202-205; Architecture v2.0.
"""

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.diagnostic import acorr_ljungbox

from config import (
    SHARPE_AUTOCORR_PVALUE_THRESHOLD,
    SHARPE_NEWEY_WEST_LAGS,
    BACKTEST_PRODUCTION_HAIRCUT,
    BACKTEST_MIN_VIABLE_HAIRCUT_SR,
)


class SharpeEstimationPipeline:
    """
    Complete Sharpe analysis pipeline per Architecture v2.0 Layer 6a.

    Parameters
    ----------
    n_trials : int
        Number of strategies / parameter configurations evaluated on this
        dataset. Required for DSR. A Sharpe without a trial count is
        informationally incomplete. Ref: LdP "Marcos' Third Law."
    risk_free_per_period : float
        Risk-free rate per return period (e.g., daily). Default 0.0.
    """

    def __init__(self, n_trials: int, risk_free_per_period: float = 0.0):
        self.n_trials = n_trials
        self.rf = risk_free_per_period

    # ─────────────────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────────────────

    def full_analysis(self, returns: pd.Series,
                      annualization_factor: int = 252,
                      n_eff: float = None) -> dict:
        """
        Run the complete Sharpe estimation pipeline.

        Parameters
        ----------
        returns : pd.Series
            Strategy return series at original frequency (daily, etc.).
            Must NOT be pre-annualized — PSR/DSR require the raw period SR.
        annualization_factor : int
            Periods per year: 252 (daily), 52 (weekly), 12 (monthly).
        n_eff : float, optional
            Effective number of independent trials from DD-12 eigenvalue
            method. If None, only literal n_trials is used for DSR.

        Returns
        -------
        dict — see Non-Negotiable Outputs #5, #6, #7 in Architecture v2.0.
        """
        returns = returns.dropna()
        T = len(returns)
        if T < 5:
            return {'error': f'Insufficient observations: {T} < 5'}

        mu = returns.mean()
        sigma = returns.std(ddof=0)
        sr_raw = (mu - self.rf) / sigma if sigma > 0 else 0.0

        # ── Stage 1: Serial correlation diagnostic (DD-02, DD-06) ────────────
        q_lags = min(annualization_factor, T // 4)
        q_lags = max(q_lags, 1)

        lb_result = acorr_ljungbox(returns, lags=[q_lags], return_df=True)
        lb_pvalue = float(lb_result['lb_pvalue'].iloc[0])
        has_autocorr = lb_pvalue < SHARPE_AUTOCORR_PVALUE_THRESHOLD

        # ── Stage 1b: SE estimation — branch on autocorrelation ──────────────
        se_results = {}
        for m in SHARPE_NEWEY_WEST_LAGS:
            _, se_m, ci_m = self._robust_se(returns, m=m)
            se_results[m] = {'se': se_m, 'ci_95': ci_m}

        if has_autocorr:
            # Primary SE from larger lag (more conservative); check sensitivity
            se_primary_m = max(SHARPE_NEWEY_WEST_LAGS)
            se_check_m   = min(SHARPE_NEWEY_WEST_LAGS)
            se   = se_results[se_primary_m]['se']
            ci   = se_results[se_primary_m]['ci_95']
            se_method = f'GMM_Newey_West_m{se_primary_m}'
            se_sensitivity = (
                abs(se - se_results[se_check_m]['se']) / se
                if se > 0 else 0.0
            )
        else:
            se = self._iid_se(sr_raw, T)
            ci = (sr_raw - 1.96 * se, sr_raw + 1.96 * se)
            se_method = 'IID'
            se_sensitivity = 0.0

        # ── Stage 2: Annualization (DD-06 — never √q as default) ─────────────
        if has_autocorr:
            rho_k = self._autocorrelations(returns, q_lags)
            eta   = self._eta_q(rho_k, q_lags)
            sr_annual = eta * sr_raw
            ann_method = f'eta_q (η={eta:.4f}, Lo 2002 Eq.20)'
        else:
            sr_annual = sr_raw * np.sqrt(annualization_factor)
            eta = np.sqrt(annualization_factor)
            ann_method = 'sqrt_q (IID — Ljung-Box passed)'

        # Always report η(q) alongside √q for comparison (DD-06)
        rho_k_all = self._autocorrelations(returns, q_lags)
        eta_q_comparison = self._eta_q(rho_k_all, q_lags)
        sr_annual_eta_comparison = eta_q_comparison * sr_raw

        # ── PSR (LdP AFML Ch.14) — non-annualized SR ─────────────────────────
        skew = float(returns.skew())
        kurt = float(returns.kurtosis()) + 3.0   # scipy returns excess kurtosis

        psr = self._psr(sr_raw, 0.0, T, skew, kurt)

        # ── DSR — literal N and N_eff (DD-12) ────────────────────────────────
        sr_variance = float(se ** 2) if se > 0 else 1.0

        dsr_literal = self._dsr(sr_raw, self.n_trials, T, skew, kurt, sr_variance)

        dsr_neff = None
        if n_eff is not None and n_eff > 0:
            dsr_neff = self._dsr(sr_raw, n_eff, T, skew, kurt, sr_variance)

        # More conservative DSR is primary (DD-12)
        if dsr_neff is not None:
            dsr_primary = min(dsr_literal, dsr_neff)
            dsr_primary_source = (
                'dsr_neff' if dsr_neff < dsr_literal else 'dsr_literal'
            )
        else:
            dsr_primary = dsr_literal
            dsr_primary_source = 'dsr_literal (n_eff not provided)'

        # ── Minimum Track Record Length ───────────────────────────────────────
        min_trl_years = self._min_track_record(sr_raw, 0.0, skew, kurt)

        # ── Production haircut (v1.0 retained, DD-10 production gate) ─────────
        production_sr = sr_annual * BACKTEST_PRODUCTION_HAIRCUT
        viable = production_sr > BACKTEST_MIN_VIABLE_HAIRCUT_SR

        return {
            # Raw estimates
            'sr_raw': round(sr_raw, 6),
            'sr_annual': round(sr_annual, 6),
            'annualization_method': ann_method,
            'sr_annual_eta_comparison': round(sr_annual_eta_comparison, 6),
            # Serial correlation
            'has_autocorrelation': has_autocorr,
            'ljung_box_pvalue': round(lb_pvalue, 6),
            'ljung_box_q_lags': q_lags,
            # Standard error (Non-Negotiable Output #5)
            'se': round(se, 6),
            'se_method': se_method,
            'ci_95': (round(ci[0], 6), round(ci[1], 6)),
            'se_sensitivity_across_lags': round(se_sensitivity, 4),
            'se_all_lags': {
                f'm{m}': {
                    'se': round(v['se'], 6),
                    'ci_95': (round(v['ci_95'][0], 6), round(v['ci_95'][1], 6)),
                }
                for m, v in se_results.items()
            },
            # Non-normality
            'skewness': round(skew, 4),
            'kurtosis': round(kurt, 4),
            # PSR / DSR (Non-Negotiable Output #7)
            'psr': round(psr, 6),
            'dsr_literal': round(dsr_literal, 6),
            'dsr_neff': round(dsr_neff, 6) if dsr_neff is not None else None,
            'dsr_primary': round(dsr_primary, 6),
            'dsr_primary_source': dsr_primary_source,
            'n_trials': self.n_trials,
            'n_eff': n_eff,
            # Track record
            'min_track_record_years': (
                round(min_trl_years, 2) if np.isfinite(min_trl_years) else None
            ),
            'T': T,
            # Production gate
            'production_haircut_sr': round(production_sr, 6),
            'viable_after_haircut': bool(viable),
        }

    def compute_n_eff(self, sharpe_matrix: np.ndarray) -> float:
        """
        Effective number of independent strategies via eigenvalue method (DD-12).

        N_eff = (Σλᵢ)² / Σλᵢ²

        Parameters
        ----------
        sharpe_matrix : np.ndarray, shape (T, N)
            Matrix of per-period returns or Sharpe contributions across N
            strategies. Correlation is computed across strategies (columns).

        Returns
        -------
        float — effective N for use in DSR.
        """
        if sharpe_matrix.ndim != 2 or sharpe_matrix.shape[1] < 2:
            return float(self.n_trials)

        corr = np.corrcoef(sharpe_matrix.T)
        eigenvalues = np.linalg.eigvalsh(corr)
        eigenvalues = eigenvalues[eigenvalues > 0]

        if len(eigenvalues) == 0:
            return float(self.n_trials)

        n_eff = float(eigenvalues.sum() ** 2 / (eigenvalues ** 2).sum())
        return round(n_eff, 4)

    # ─────────────────────────────────────────────────────────────────────────
    # Internal helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _iid_se(self, sr: float, T: int) -> float:
        """Lo (2002) Eq. 9 — SE under IID assumption."""
        return float(np.sqrt((1.0 + 0.5 * sr ** 2) / T))

    def _robust_se(self, returns: pd.Series, m: int):
        """
        GMM robust SE via Newey-West HAC covariance estimator.
        Lo (2002) Section 3.3, GMM approach.

        The moment conditions are:
          g1 = r_t - μ  (mean equation)
          g2 = (r_t - μ)² - σ²  (variance equation)
        The gradient of SR w.r.t. (μ, σ²) is:
          ∂SR/∂μ   = 1/σ
          ∂SR/∂σ²  = -(μ - rf) / (2σ³)

        Ref: Lo (2002), Section 3.3; Andrews (1991) for NW weights.
        """
        T = len(returns)
        mu_hat = float(returns.mean())
        sigma2_hat = float(returns.var(ddof=0))
        sigma_hat = float(np.sqrt(sigma2_hat))

        if sigma_hat == 0:
            return 0.0, 0.0, (0.0, 0.0)

        sr_hat = (mu_hat - self.rf) / sigma_hat

        psi = np.column_stack([
            returns.values - mu_hat,
            (returns.values - mu_hat) ** 2 - sigma2_hat,
        ])

        # Bartlett (Newey-West) kernel: w_j = 1 - j/(m+1)
        Gamma_0 = (psi.T @ psi) / T
        Sigma_hat = Gamma_0.copy()
        for j in range(1, m + 1):
            Gamma_j = (psi[j:].T @ psi[:-j]) / T
            w = 1.0 - j / (m + 1)
            Sigma_hat += w * (Gamma_j + Gamma_j.T)

        # Gradient of SR w.r.t. (μ, σ²)
        grad = np.array([
            1.0 / sigma_hat,
            -(mu_hat - self.rf) / (2.0 * sigma_hat ** 3),
        ])

        V_GMM = float(grad @ Sigma_hat @ grad)
        se = float(np.sqrt(max(V_GMM, 0.0) / T))
        ci = (sr_hat - 1.96 * se, sr_hat + 1.96 * se)
        return sr_hat, se, ci

    def _autocorrelations(self, returns: pd.Series, max_lag: int) -> np.ndarray:
        """Compute sample autocorrelations ρ_k for k = 1 … max_lag-1."""
        vals = returns.values
        n = len(vals)
        rho = []
        for k in range(1, min(max_lag, n // 2)):
            if n - k < 2:
                break
            r = float(np.corrcoef(vals[k:], vals[:-k])[0, 1])
            rho.append(r if np.isfinite(r) else 0.0)
        return np.array(rho)

    def _eta_q(self, rho_k: np.ndarray, q: int) -> float:
        """
        Lo (2002) Eq. 20 — autocorrelation-adjusted annualization scale factor.

        η(q) = q / √(q + 2·Σ_{k=1}^{q-1} (q-k)·ρ_k)

        Under IID, η(q) = √q. When returns exhibit positive autocorrelation
        (as in theta-harvesting strategies), √q overstates annualized Sharpe
        by up to 65%. η(q) corrects for this.
        """
        correction = sum(
            (q - k - 1) * rho_k[k]
            for k in range(min(len(rho_k), q - 1))
        )
        denom = q + 2.0 * correction
        if denom <= 0:
            return float(np.sqrt(q))
        return float(q / np.sqrt(denom))

    def _psr(self, sr: float, sr_benchmark: float,
             T: int, skew: float, kurt: float) -> float:
        """
        Probabilistic Sharpe Ratio (LdP AFML Ch.14, p.203).

        PSR(SR*) = Φ[ (SR - SR*) · √(T-1) / √(1 - γ₃·SR + (γ₄-1)/4·SR²) ]

        CRITICAL: sr must be the NON-ANNUALIZED period Sharpe (DD-02).
        PSR corrects for non-normality via the observed skewness (γ₃) and
        kurtosis (γ₄). Annualizing before calling this function produces
        incorrect results.

        Parameters
        ----------
        sr           : float — non-annualized Sharpe at original frequency
        sr_benchmark : float — benchmark SR (typically 0.0)
        T            : int   — number of observations
        skew         : float — sample skewness (3rd standardized moment)
        kurt         : float — sample kurtosis (4th moment, NOT excess)
        """
        if T <= 1:
            return 0.0

        variance_term = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr ** 2
        if variance_term <= 0:
            variance_term = 1e-8

        z = (sr - sr_benchmark) * np.sqrt(T - 1) / np.sqrt(variance_term)
        return float(stats.norm.cdf(z))

    def _dsr(self, sr: float, n_trials: float, T: int,
             skew: float, kurt: float,
             sr_variance: float = 1.0) -> float:
        """
        Deflated Sharpe Ratio (LdP AFML Ch.14, p.204).

        DSR = PSR with benchmark SR* set to the expected maximum SR from
        N independent trials on zero-edge data:

          SR* = √Var(SR) · [ (1-γ)·Φ⁻¹(1 - 1/N) + γ·Φ⁻¹(1 - 1/(N·e)) ]

        where γ ≈ 0.5772 (Euler–Mascheroni constant).

        Parameters
        ----------
        sr          : float — non-annualized period Sharpe
        n_trials    : float — number of strategies tested (literal N or N_eff)
        T           : int   — number of observations
        skew, kurt  : float — non-normality parameters
        sr_variance : float — variance of the SR estimator (from SE²)
        """
        n_trials = max(float(n_trials), 2.0)
        euler = 0.5772156649015329

        sr_star = float(np.sqrt(sr_variance)) * (
            (1.0 - euler) * stats.norm.ppf(1.0 - 1.0 / n_trials) +
            euler        * stats.norm.ppf(1.0 - 1.0 / (n_trials * np.e))
        )

        return self._psr(sr, sr_star, T, skew, kurt)

    def _min_track_record(self, sr: float, target_sr: float,
                          skew: float, kurt: float,
                          alpha: float = 0.05) -> float:
        """
        Minimum number of observations for PSR(SR*) ≥ 1-α.

        T_min = 1 + (1 - γ₃·SR + (γ₄-1)/4·SR²) · (Φ⁻¹(1-α) / (SR - SR*))²

        Returns years (T_min / 252).
        Ref: LdP 2018 Solution #10; AFML Ch.14, p.205.
        """
        if abs(sr - target_sr) < 1e-8:
            return float('inf')

        z = stats.norm.ppf(1.0 - alpha)
        variance_term = 1.0 - skew * sr + (kurt - 1.0) / 4.0 * sr ** 2
        if variance_term <= 0:
            return float('inf')

        n_obs = 1.0 + variance_term * (z / (sr - target_sr)) ** 2
        return float(n_obs / 252.0)


# ─────────────────────────────────────────────────────────────────────────────
# Layer 6b: Permutation Test (relocated from v1.0 ResearchValidator)
# ─────────────────────────────────────────────────────────────────────────────

def permutation_test(returns: pd.Series,
                     metric_func,
                     n_permutations: int = 1000,
                     random_seed: int = 42) -> dict:
    """
    Non-parametric permutation test for strategy significance.

    The null hypothesis is that the strategy has no edge — the return
    ordering is irrelevant. Under this null, any permutation of the
    return series is equally likely.

    Parameters
    ----------
    returns : pd.Series
        Strategy return series.
    metric_func : callable
        f(pd.Series) -> float. The statistic to test (e.g., Sharpe ratio).
        Applied to both the observed series and each permutation.
    n_permutations : int
        Number of random permutations. 1000 minimum; 10,000 for publication.
    random_seed : int
        Reproducibility seed.

    Returns
    -------
    dict with:
        observed_metric  : float — metric on original series
        null_mean        : float — mean metric under null
        null_std         : float — std of null distribution
        p_value          : float — fraction of permutations ≥ observed
        significant_at_5 : bool
        n_permutations   : int
    """
    rng = np.random.default_rng(seed=random_seed)
    observed = float(metric_func(returns))

    null_distribution = []
    vals = returns.values.copy()
    for _ in range(n_permutations):
        perm = rng.permutation(vals)
        null_distribution.append(float(metric_func(pd.Series(perm))))

    null_arr = np.array(null_distribution)
    p_value = float((null_arr >= observed).mean())

    return {
        'observed_metric': round(observed, 6),
        'null_mean': round(float(null_arr.mean()), 6),
        'null_std': round(float(null_arr.std()), 6),
        'p_value': round(p_value, 6),
        'significant_at_5': p_value < 0.05,
        'n_permutations': n_permutations,
    }
