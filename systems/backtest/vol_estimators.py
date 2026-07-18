"""
Layer 3: Volatility Estimator Suite — five OHLC estimators + vol cones.

Provides five realized volatility estimators with different efficiency/bias
tradeoffs, and a vol cone that shows the percentile distribution of historical
vol by window length with Hodges-Tompkins overlap correction.

Relationship to Sarah's vol pipeline:
    Sarah's backward_vrp_proxy() in research/signals/vol_signals.py computes
    rv_21d as a specific 21-day close-to-close realized vol used for signal
    extraction. VolEstimatorSuite.close_to_close() is a generic rolling
    estimator with configurable window and does not duplicate that logic.
    Both coexist: Sarah's is for daily signal production; VolEstimatorSuite
    is for research-time comparison of estimator choices.

On real S&P 500 data, correlations between estimators approach 0.99
(Sinclair). But the biases differ, and for VRP signals the bias direction
matters — Parkinson is biased low (discrete sampling), Garman-Klass is
more biased than Parkinson. Yang-Zhang is the minimum-error estimator
and degrades to close-to-close when jumps dominate.

Ref: Sinclair Ch.2 (estimators), Ch.2 (vol cones).
"""

import numpy as np
import pandas as pd

from config import VOL_CONE_WINDOWS, VOL_CONE_PERCENTILES


class VolEstimatorSuite:
    """
    Five OHLC-based realized volatility estimators.
    Any signal built on a single estimator is preliminary.
    Compare all five before committing to one for a research hypothesis.

    Ref: Sinclair Ch.2. On real S&P 500 data, correlations between
    estimators approach 0.99 — estimator choice matters less on real
    data than in simulation. But the biases differ, and for VRP
    signals, the bias direction matters.
    """

    @staticmethod
    def close_to_close(
        close: pd.Series,
        window: int = 21,
        annualize: float = 252 ** 0.5,
    ) -> pd.Series:
        """
        Standard close-to-close log-return volatility.
        Least efficient estimator. Baseline for comparison.
        Relationship to Sarah: Sarah's rv_21d is a fixed 21-day
        version of this; VolEstimatorSuite.close_to_close() is
        the configurable research version.
        """
        log_ret = np.log(close / close.shift(1))
        return log_ret.rolling(window).std() * annualize

    @staticmethod
    def parkinson(
        high: pd.Series,
        low: pd.Series,
        window: int = 21,
        annualize: float = 252 ** 0.5,
    ) -> pd.Series:
        """
        Parkinson (1980) high-low estimator.
        ~5x more efficient than close-to-close on GBM.
        Biased low due to discrete sampling (true high/low exceed observed).
        Does not handle drift or opening jumps.
        """
        log_hl = np.log(high / low)
        return (
            (log_hl ** 2).rolling(window).mean().apply(
                lambda x: np.sqrt(x / (4 * np.log(2)))
            )
            * annualize
        )

    @staticmethod
    def garman_klass(
        open_: pd.Series,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int = 21,
        annualize: float = 252 ** 0.5,
    ) -> pd.Series:
        """
        Garman-Klass (1980) OHLC estimator.
        Up to 8x more efficient than close-to-close.
        More biased than Parkinson — does not handle drift or opening gaps.
        """
        log_hl = np.log(high / low)
        log_cc = np.log(close / close.shift(1))
        daily = 0.5 * log_hl ** 2 - (2 * np.log(2) - 1) * log_cc ** 2
        return daily.rolling(window).mean().apply(np.sqrt) * annualize

    @staticmethod
    def rogers_satchell(
        open_: pd.Series,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int = 21,
        annualize: float = 252 ** 0.5,
    ) -> pd.Series:
        """
        Rogers-Satchell (1991) estimator.
        Handles drift but not opening gaps between sessions.
        """
        daily = (
            np.log(high / close) * np.log(high / open_)
            + np.log(low / close) * np.log(low / open_)
        )
        return daily.rolling(window).mean().apply(np.sqrt) * annualize

    @staticmethod
    def yang_zhang(
        open_: pd.Series,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int = 21,
        annualize: float = 252 ** 0.5,
    ) -> pd.Series:
        """
        Yang-Zhang (2000) minimum-error estimator.
        Handles drift and opening jumps between sessions.
        Degrades to close-to-close when jumps dominate.
        Preferred default for research unless jump regime analysis
        suggests otherwise.
        """
        n = window
        k = 0.34 / (1 + (n + 1) / (n - 1))

        log_oc = np.log(open_ / close.shift(1))
        log_cc = np.log(close / close.shift(1))

        sigma_o_sq = log_oc.rolling(window).var()
        sigma_c_sq = log_cc.rolling(window).var()
        sigma_rs = (
            VolEstimatorSuite.rogers_satchell(
                open_, high, low, close, window, annualize=1.0
            )
            ** 2
        )

        yz = np.sqrt(sigma_o_sq + k * sigma_c_sq + (1 - k) * sigma_rs)
        return yz * annualize

    @staticmethod
    def compare_all(
        open_: pd.Series,
        high: pd.Series,
        low: pd.Series,
        close: pd.Series,
        window: int = 21,
        annualize: float = 252 ** 0.5,
    ) -> pd.DataFrame:
        """
        Return all five estimators as a DataFrame for comparison.
        Columns: close_to_close, parkinson, garman_klass,
                 rogers_satchell, yang_zhang.
        """
        return pd.DataFrame({
            'close_to_close': VolEstimatorSuite.close_to_close(
                close, window, annualize
            ),
            'parkinson': VolEstimatorSuite.parkinson(
                high, low, window, annualize
            ),
            'garman_klass': VolEstimatorSuite.garman_klass(
                open_, high, low, close, window, annualize
            ),
            'rogers_satchell': VolEstimatorSuite.rogers_satchell(
                open_, high, low, close, window, annualize
            ),
            'yang_zhang': VolEstimatorSuite.yang_zhang(
                open_, high, low, close, window, annualize
            ),
        })


class VolCone:
    """
    Percentile distribution of historical realized vol by window length.

    Sinclair: "the vol cone context is more important for trade decisions
    than a GARCH point forecast."

    Uses Hodges-Tompkins overlap correction for rolling windows so that
    the variance of overlapping windows is estimated correctly.
    The correction factor m scales the variance estimate upward to account
    for the artificial smoothing introduced by overlapping observations.

    Ref: Sinclair Eq. 2.35 (overlap correction).
    """

    @staticmethod
    def overlap_correction(h: int, n: int) -> float:
        """
        Hodges-Tompkins correction factor m for overlapping rolling windows.
        h: window length. n: number of non-overlapping observations.
        Ref: Sinclair Eq. 2.35.
        """
        return 1.0 / (1.0 - h / n + (h ** 2 - 1) / (3 * n ** 2))

    @staticmethod
    def compute(
        close: pd.Series,
        windows: list = None,
        percentiles: list = None,
        annualize: float = 252 ** 0.5,
    ) -> pd.DataFrame:
        """
        Compute vol cone percentile table.

        Parameters
        ----------
        close : pd.Series
            Close price series.
        windows : list of int, optional
            Rolling window lengths (days). Defaults to VOL_CONE_WINDOWS.
        percentiles : list of int, optional
            Percentiles to compute (0–100). Defaults to VOL_CONE_PERCENTILES.
        annualize : float
            Annualization factor. Default sqrt(252).

        Returns
        -------
        pd.DataFrame with columns:
            window, p5, p25, p50, p75, p95 (or configured percentiles),
            current (most recent vol value), rank (0-1 within historical range)
        """
        if windows is None:
            windows = VOL_CONE_WINDOWS
        if percentiles is None:
            percentiles = VOL_CONE_PERCENTILES

        T = len(close)
        results = []
        for w in windows:
            log_ret = np.log(close / close.shift(1)).dropna()
            vol = log_ret.rolling(w).std() * annualize
            vol = vol.dropna()
            if len(vol) < 2:
                continue
            n = T - w + 1
            if n <= 1:
                continue
            m = VolCone.overlap_correction(w, n)
            corrected_vol = vol * np.sqrt(m)
            row = {'window': w}
            for p in percentiles:
                row[f'p{p}'] = float(np.percentile(corrected_vol, p))
            row['current'] = float(corrected_vol.iloc[-1])
            vol_min = corrected_vol.min()
            vol_max = corrected_vol.max()
            row['rank'] = float(
                (corrected_vol.iloc[-1] - vol_min) / (vol_max - vol_min)
                if vol_max > vol_min else 0.5
            )
            results.append(row)

        return pd.DataFrame(results)
