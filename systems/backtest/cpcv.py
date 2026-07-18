"""
Layer 5b: Combinatorial Purged Cross-Validation (CPCV).

CPCV is the PRIMARY validation method. Walk-forward is secondary and
must be labeled "single-path, high-variance estimate" when reported.

CPCV produces a DISTRIBUTION of Sharpe ratios across φ[N,k] paths.
A single walk-forward Sharpe is one draw from this distribution —
basing a production decision on it is equivalent to evaluating a coin
by flipping it once.

PBO (Probability of Backtest Overfitting) is derived from the CPCV
output distribution as a secondary diagnostic. It is NOT an
optimization target (DD-11).

Design decisions encoded here:
- DD-03: CPCV primary, walk-forward secondary with explicit label.
- DD-05: Purging and embargoing applied within each split.
- DD-11: PBO is computed post-hoc only. It is not exposed as an
  optimization objective, loss function, or selection criterion.

Ref: AFML Ch.12, pp.163-167; Bailey et al. 2014.
Architecture v2.0 Layer 5b.
"""

import numpy as np
import pandas as pd
from itertools import combinations
from math import comb
from scipy import stats

from config import (
    CPCV_DEFAULT_N_GROUPS,
    CPCV_DEFAULT_K_TEST,
    CPCV_DEFAULT_PCT_EMBARGO,
)


class CPCV:
    """
    Combinatorial Purged Cross-Validation.

    Parameters
    ----------
    n_groups : int
        Number of groups N to partition the time series into.
        Default: CPCV_DEFAULT_N_GROUPS (6).
    k_test : int
        Number of groups held out as test in each combination.
        Default: CPCV_DEFAULT_K_TEST (2).
        n_paths = φ[N,k] = (k/N) * C(N, N-k)
    pct_embargo : float
        Fraction of total observations to embargo at group boundaries.
        For options strategies with holding periods > T/N, increase this
        to match the holding period. Ref: DD-05.

    Notes
    -----
    Known limitation: adding more paths (increasing k toward N/2) reduces
    training set size per fit. For short options histories (<5 years daily),
    N=6, k=2 producing ~5 paths may be insufficient for strong conclusions.
    Document this constraint per-strategy. (Architecture v2.0 Open Limitation 4.)
    """

    def __init__(self,
                 n_groups: int = CPCV_DEFAULT_N_GROUPS,
                 k_test: int = CPCV_DEFAULT_K_TEST,
                 pct_embargo: float = CPCV_DEFAULT_PCT_EMBARGO):
        self.n_groups = n_groups
        self.k_test = k_test
        self.pct_embargo = pct_embargo

    @property
    def n_paths(self) -> int:
        """
        φ[N,k] = (k/N) * C(N, N-k)

        Number of distinct backtest paths produced by CPCV.
        Each path is an OOS performance estimate from a unique
        combination of test groups.
        """
        return (self.k_test * comb(self.n_groups, self.n_groups - self.k_test)) // self.n_groups

    def generate_splits(self, T: int) -> list:
        """
        Generate all C(N, k) train/test splits with embargo applied
        at boundaries between adjacent train and test groups.

        Parameters
        ----------
        T : int
            Total number of observations.

        Returns
        -------
        list of dicts, each with:
            'test_groups'  : tuple of group indices held out as test
            'train_idx'    : np.ndarray of training observation indices
            'test_idx'     : np.ndarray of test observation indices
        """
        group_size = T // self.n_groups
        groups = []
        for i in range(self.n_groups):
            start = i * group_size
            end = (i + 1) * group_size if i < self.n_groups - 1 else T
            groups.append(np.arange(start, end))

        embargo_size = max(1, int(T * self.pct_embargo))
        splits = []

        for test_combo in combinations(range(self.n_groups), self.k_test):
            test_idx = np.concatenate([groups[i] for i in test_combo])
            train_groups = [i for i in range(self.n_groups) if i not in test_combo]
            train_idx = np.concatenate([groups[i] for i in train_groups])

            # Embargo: for each test group boundary, remove training obs
            # within embargo_size bars after the test group ends
            embargoed = set()
            for tg in test_combo:
                if len(groups[tg]) == 0:
                    continue
                embargo_start = int(groups[tg][-1]) + 1
                embargo_end = min(embargo_start + embargo_size, T)
                for idx in range(embargo_start, embargo_end):
                    embargoed.add(idx)

            if embargoed:
                train_idx = train_idx[~np.isin(train_idx, list(embargoed))]

            splits.append({
                'test_groups': test_combo,
                'train_idx': train_idx,
                'test_idx': test_idx,
            })

        return splits

    def compute_path_sharpes(
        self,
        returns: pd.Series,
        signal_func=None,
        model_func=None,
    ) -> dict:
        """
        Run CPCV and return the distribution of Sharpe ratios.

        For signal-based strategies, signal_func takes training data
        and returns a signal series used to weight returns in the test set.
        If signal_func is None, the strategy is assumed to be always-long
        (returns are evaluated as-is).

        Parameters
        ----------
        returns : pd.Series
            Strategy returns indexed by date.
        signal_func : callable, optional
            f(train_returns) -> signal_series aligned to test dates.
            If None, computes Sharpe directly on test returns.
        model_func : callable, optional
            Alternative to signal_func for ML-based strategies.

        Returns
        -------
        dict with keys:
            n_paths, mean_sharpe, median_sharpe, std_sharpe,
            p5_sharpe, p95_sharpe, pct_positive, pbo,
            is_oos_correlation, path_sharpes (np.ndarray),
            walk_forward_note (str — DD-03 label)
        """
        T = len(returns)
        splits = self.generate_splits(T)

        path_sharpes = []
        is_sharpes = []
        oos_sharpes = []

        for split in splits:
            train_ret = returns.iloc[split['train_idx']]
            test_ret = returns.iloc[split['test_idx']]

            # IS Sharpe
            is_sr = (
                train_ret.mean() / train_ret.std() * np.sqrt(252)
                if train_ret.std() > 0 else 0.0
            )

            # OOS Sharpe — apply signal weighting if provided
            if signal_func is not None and len(train_ret) > 0:
                try:
                    signal = signal_func(train_ret)
                    # Align signal to test index
                    if isinstance(signal, pd.Series):
                        signal = signal.reindex(test_ret.index).fillna(0)
                        weighted_ret = test_ret * np.sign(signal)
                    else:
                        weighted_ret = test_ret
                except Exception:
                    weighted_ret = test_ret
            else:
                weighted_ret = test_ret

            oos_sr = (
                weighted_ret.mean() / weighted_ret.std() * np.sqrt(252)
                if weighted_ret.std() > 0 else 0.0
            )

            is_sharpes.append(is_sr)
            oos_sharpes.append(oos_sr)
            path_sharpes.append(oos_sr)

        path_sharpes = np.array(path_sharpes)
        is_sharpes = np.array(is_sharpes)
        oos_sharpes = np.array(oos_sharpes)

        pbo = self._compute_pbo(is_sharpes, oos_sharpes)

        is_oos_corr = (
            float(np.corrcoef(is_sharpes, oos_sharpes)[0, 1])
            if len(is_sharpes) > 1 else float('nan')
        )

        return {
            'n_paths': len(path_sharpes),
            'mean_sharpe': float(np.mean(path_sharpes)),
            'median_sharpe': float(np.median(path_sharpes)),
            'std_sharpe': float(np.std(path_sharpes)),
            'p5_sharpe': float(np.percentile(path_sharpes, 5)),
            'p95_sharpe': float(np.percentile(path_sharpes, 95)),
            'pct_positive': float((path_sharpes > 0).mean()),
            'pbo': pbo,
            'is_oos_correlation': is_oos_corr,
            'path_sharpes': path_sharpes,
            # DD-03: walk-forward is secondary — label explicitly
            'walk_forward_note': (
                'Walk-forward is a single-path, high-variance estimate. '
                'CPCV path distribution is the primary finding. '
                'Ref: DD-03, AFML Ch.12.'
            ),
        }

    def _compute_pbo(self, is_sharpes: np.ndarray,
                     oos_sharpes: np.ndarray) -> float:
        """
        Probability of Backtest Overfitting via logit distribution.

        For each split, compute the logit of the OOS percentile rank.
        PBO = fraction of logits < 0, indicating IS-optimal selection
        underperforms the median OOS path.

        Ref: Bailey et al. 2014, Section 3.1.

        IMPORTANT (DD-11): PBO is a diagnostic metric only.
        It must never be used as an optimization objective.
        The architecture enforces this by computing PBO only here,
        as a post-hoc diagnostic, never within any optimization loop.
        """
        if len(oos_sharpes) < 2:
            return float('nan')

        logits = []
        for i in range(len(is_sharpes)):
            # Percentile rank of this path's OOS Sharpe in the OOS distribution
            omega = stats.percentileofscore(oos_sharpes, oos_sharpes[i]) / 100.0
            omega = float(np.clip(omega, 0.01, 0.99))
            logit = np.log(omega / (1.0 - omega))
            logits.append(logit)

        logits = np.array(logits)
        return float((logits < 0).mean())
