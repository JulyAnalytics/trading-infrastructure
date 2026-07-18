"""
Layer 5a: Purged K-Fold Cross-Validation with embargo.

Standard sklearn KFold is NOT valid for financial time series — label
windows overlap across folds, causing information leakage. This class
purges training observations whose label windows overlap with test
label windows, then embargoes a buffer after the test set.

Design decisions encoded here:
- DD-05: Apply purging AND embargoing within each CPCV split.
  Embargo defaults to h ≈ 0.01T. For options with long holding periods
  (> T/S), increase pct_embargo to match the holding period.

Ref: AFML Ch.7, pp.105-110; Snippet 7.3.
Architecture v2.0 Layer 5a.
"""

import numpy as np
import pandas as pd
from sklearn.model_selection._split import _BaseKFold

from config import CPCV_DEFAULT_PCT_EMBARGO


class PurgedKFold(_BaseKFold):
    """
    K-fold CV with purging and embargoing for financial time series.

    Parameters
    ----------
    n_splits : int
        Number of folds.
    t1 : pd.Series
        Series indexed by observation start time, values are label end times.
        Required for purging. If None, purging is skipped (only embargo applied).
    pct_embargo : float
        Fraction of total observations to embargo after each test block.
        Default: CPCV_DEFAULT_PCT_EMBARGO (0.01). For options strategies
        with holding periods > T/n_splits, increase to match holding period.
    """

    def __init__(self, n_splits: int = 5, t1: pd.Series = None,
                 pct_embargo: float = CPCV_DEFAULT_PCT_EMBARGO):
        super().__init__(n_splits=n_splits, shuffle=False, random_state=None)
        self.t1 = t1
        self.pct_embargo = pct_embargo

    def split(self, X, y=None, groups=None):
        """
        Yield (train_indices, test_indices) for each fold.
        Purging and embargoing are applied before yielding.
        """
        n = len(X)
        indices = np.arange(n)
        embargo_size = int(n * self.pct_embargo)
        test_size = n // self.n_splits

        for i in range(self.n_splits):
            test_start = i * test_size
            test_end = min((i + 1) * test_size, n)
            test_indices = indices[test_start:test_end]

            # All non-test indices as candidate train set
            train_indices = np.concatenate([
                indices[:test_start],
                indices[test_end:]
            ])

            # Purge: remove training obs whose label windows overlap test
            if self.t1 is not None:
                train_indices = self._purge(train_indices, test_indices)

            # Embargo: remove training obs within embargo_size bars after test
            embargo_start = test_end
            embargo_end = min(test_end + embargo_size, n)
            embargo_set = set(range(embargo_start, embargo_end))
            train_indices = train_indices[
                ~np.isin(train_indices, list(embargo_set))
            ]

            yield train_indices, test_indices

    def _purge(self, train_indices: np.ndarray,
               test_indices: np.ndarray) -> np.ndarray:
        """
        Remove training observations whose label windows overlap
        with the test set's time range.

        Three overlap conditions (AFML p.106):
          1. Training label starts within test window
          2. Training label ends within test window
          3. Training label spans the entire test window
        """
        if self.t1 is None or len(test_indices) == 0:
            return train_indices

        # Get time range of test labels
        test_t0s = self.t1.index[test_indices]
        test_t1s = self.t1.iloc[test_indices]
        test_start = test_t0s.min()
        test_end = test_t1s.max()

        purge_mask = np.zeros(len(train_indices), dtype=bool)
        for j, idx in enumerate(train_indices):
            if idx >= len(self.t1):
                continue
            train_t0 = self.t1.index[idx]
            train_t1 = self.t1.iloc[idx]

            overlaps = (
                (test_start <= train_t0 <= test_end) or
                (test_start <= train_t1 <= test_end) or
                (train_t0 <= test_start and train_t1 >= test_end)
            )
            if overlaps:
                purge_mask[j] = True

        return train_indices[~purge_mask]
