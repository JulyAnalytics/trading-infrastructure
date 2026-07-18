"""
Layer 3: Feature Engineering — FracDiff and stationarity framework.

Fractional differentiation finds the minimum differencing order d that
achieves stationarity while retaining maximum memory. Standard integer
differencing (d=1) destroys predictive memory; raw prices (d=0) are
non-stationary. FracDiff finds the minimum d that passes ADF stationarity.

Gap 7.3 (LdP 2018): FracDiff is demonstrated on equity price series.
For vol surface features (IV, skew, term structure slope) that are already
roughly stationary, FracDiff may not be meaningful. Run ADF first — if the
series passes without differencing, skip FracDiff.

Ref: LdP 2018 Pitfall #4; AFML Ch.5.
"""

import numpy as np
import pandas as pd
from statsmodels.tsa.stattools import adfuller

from config import (
    BACKTEST_DEFAULT_SIGNIFICANCE,
    FRACDIFF_D_RANGE,
    FRACDIFF_D_STEP,
    FRACDIFF_WEIGHT_THRESHOLD,
)


class FracDiff:
    """
    Fractional differentiation: find minimum d that achieves
    stationarity while retaining maximum memory.

    Standard returns (d=1) destroy predictive memory.
    Raw prices (d=0) are non-stationary.
    FracDiff finds the sweet spot.

    Ref: LdP 2018 Pitfall #4.

    NOTE: For vol surface features (IV, skew, term structure slope)
    that are already roughly stationary, FracDiff may not be meaningful.
    Run ADF test first — if the series passes without differencing, skip
    FracDiff. This is Gap 7.3 in the LdP 2018 extraction.
    """

    @staticmethod
    def get_weights(d: float, threshold: float = FRACDIFF_WEIGHT_THRESHOLD) -> np.ndarray:
        """
        Compute binomial series weights for fractional differencing.
        Weights are truncated once abs(weight) < threshold.
        """
        w = [1.0]
        k = 1
        while abs(w[-1]) >= threshold:
            w.append(-w[-1] * (d - k + 1) / k)
            k += 1
        return np.array(w)

    @staticmethod
    def apply(series: pd.Series, d: float,
              threshold: float = FRACDIFF_WEIGHT_THRESHOLD) -> pd.Series:
        """
        Apply fractional differencing of order d to a series.
        Returns a Series with NaN dropped at the leading edge.
        """
        weights = FracDiff.get_weights(d, threshold)
        width = len(weights)
        result = pd.Series(index=series.index, dtype=float)
        for i in range(width - 1, len(series)):
            result.iloc[i] = np.dot(
                weights, series.iloc[i - width + 1:i + 1].values[::-1]
            )
        return result.dropna()

    @staticmethod
    def find_minimum_d(
        series: pd.Series,
        adf_confidence: float = BACKTEST_DEFAULT_SIGNIFICANCE,
        d_range: tuple = FRACDIFF_D_RANGE,
        step: float = FRACDIFF_D_STEP,
    ) -> dict:
        """
        Search for minimum d in d_range that achieves ADF stationarity.

        Returns a dict with:
          - d: minimum differencing order achieving stationarity
          - adf_stat: ADF test statistic at that d
          - adf_pvalue: p-value at that d
          - stationary: True if d achieves stationarity
          - correlation_with_original: Pearson correlation between
            the fractionally differenced series and the original.
            Higher correlation = more memory retained.
          - note: present only if no d < 1 achieves stationarity

        Usage pattern:
            result = FracDiff.find_minimum_d(price_series)
            if result.get('note'):
                # No d < 1 worked; use d=1 (standard differencing)
                fd = FracDiff.apply(price_series, d=1.0)
            else:
                fd = FracDiff.apply(price_series, d=result['d'])
        """
        results = []
        for d in np.arange(d_range[0], d_range[1] + step, step):
            d = round(float(d), 10)  # avoid floating-point drift
            fd = FracDiff.apply(series, d)
            if len(fd.dropna()) < 30:
                continue
            adf_stat, adf_pvalue, *_ = adfuller(fd.dropna())
            corr = fd.corr(series.reindex(fd.index))
            results.append({
                'd': round(d, 2),
                'adf_stat': adf_stat,
                'adf_pvalue': adf_pvalue,
                'stationary': adf_pvalue < adf_confidence,
                'correlation_with_original': corr,
            })

        if not results:
            return {'d': 1.0, 'note': 'Insufficient observations for any d'}

        df = pd.DataFrame(results)
        stationary = df[df['stationary']]
        if stationary.empty:
            return {'d': 1.0, 'note': 'No d < 1 achieved stationarity'}

        optimal = stationary.iloc[0]  # minimum d that is stationary
        return optimal.to_dict()
