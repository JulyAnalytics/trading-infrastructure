"""
Layer 4c: Label Construction — triple-barrier labeling and sample weights.

Triple-barrier labeling produces path-dependent labels for financial time
series. Fixed-time-horizon labels are not the default here; each observation's
label is determined by which of three barriers is hit first:
  1. Upper (profit-target): +pt_multiplier × σ above entry
  2. Lower (stop-loss):     -sl_multiplier × σ below entry
  3. Vertical (time expiry): at the horizon timestamp t1

SampleWeights addresses the label-overlap problem that is structural for
options strategies with multi-day holding periods. Standard ML training
over-weights correlated overlapping observations; uniqueness weighting
downweights them to match their effective information contribution.

Design decisions:
  - DD-04: Mode A (barriers on underlying price) is the default.
    Mode B (barriers on options P&L) is available when the
    path-dependent options engine has already produced a P&L series.
  - DD-05: Purging and embargoing is applied within CPCV splits;
    label overlap is handled here at the sample-weight level.

Ref: LdP AFML Ch.3 (triple-barrier), Ch.4 (sample weights).
"""

import numpy as np
import pandas as pd
from typing import Optional

from config import (
    TRIPLE_BARRIER_PT_MULTIPLIER,
    TRIPLE_BARRIER_SL_MULTIPLIER,
    TRIPLE_BARRIER_EWMA_SPAN,
)


class TripleBarrierLabeler:
    """
    Path-dependent labeling. Fixed-time horizon labels are not the default.

    Three barriers:
      1. Upper: profit target at +pt_multiplier × σ above entry
      2. Lower: stop-loss at -sl_multiplier × σ below entry
      3. Vertical: time expiry at t1

    Labels are in {-1, 0, +1}:
      +1: upper barrier hit first (profit target reached)
      -1: lower barrier hit first (stop-loss triggered)
       0: vertical barrier hit first (time expiry, no directional resolution)

    If a `side` column is present in the events DataFrame (meta-labeling
    mode), the barrier directions are flipped for short-side events.

    Mode A (default): barriers on underlying price series.
    Mode B: barriers on an already-computed P&L series (pass the P&L
            series as `close`). The caller is responsible for P&L path
            construction via the options engine.

    Ref: LdP AFML Ch.3, pp.45-51; LdP 2018 Solution #5.
    """

    @staticmethod
    def compute_ewma_vol(
        close: pd.Series,
        span: int = TRIPLE_BARRIER_EWMA_SPAN,
    ) -> pd.Series:
        """
        EWMA standard deviation of log returns for barrier-width scaling.
        Returns a Series aligned to `close`'s index. The first `span` values
        are NaN until the EWMA accumulates sufficient history.

        Ref: AFML Snippet 3.1.
        """
        log_ret = np.log(close / close.shift(1))
        return log_ret.ewm(span=span).std()

    @staticmethod
    def build_events(
        close: pd.Series,
        entry_times: pd.DatetimeIndex,
        horizon_bars: int,
        vol: Optional[pd.Series] = None,
        side: Optional[pd.Series] = None,
    ) -> pd.DataFrame:
        """
        Construct an events DataFrame from entry timestamps and a fixed
        horizon (in bars). This is a convenience builder; callers can also
        construct events manually.

        Parameters
        ----------
        close : pd.Series
            Price series (DatetimeIndex).
        entry_times : pd.DatetimeIndex
            Timestamps at which positions are entered.
        horizon_bars : int
            Number of bars until the vertical barrier (t1).
        vol : pd.Series, optional
            Pre-computed EWMA vol series. If None, computed internally
            using the default span. Used as `trgt` (barrier width).
        side : pd.Series, optional
            Position direction (+1 long, -1 short) indexed by entry_times.
            Required for meta-labeling mode. If None, all entries are long (+1).

        Returns
        -------
        pd.DataFrame with index = entry_times, columns:
            t1   : vertical barrier timestamp (DatetimeIndex element)
            trgt : volatility-scaled barrier width (daily vol at entry)
            side : direction (+1 or -1)
        """
        if vol is None:
            vol = TripleBarrierLabeler.compute_ewma_vol(close)

        idx = close.index
        rows = []
        for t0 in entry_times:
            if t0 not in idx:
                continue
            loc = idx.get_loc(t0)
            t1_loc = min(loc + horizon_bars, len(idx) - 1)
            t1 = idx[t1_loc]
            trgt = vol.reindex([t0]).iloc[0]
            if pd.isna(trgt) or trgt <= 0:
                continue
            s = 1
            if side is not None and t0 in side.index:
                s = int(side.loc[t0])
            rows.append({'t0': t0, 't1': t1, 'trgt': trgt, 'side': s})

        if not rows:
            return pd.DataFrame(columns=['t1', 'trgt', 'side'])

        df = pd.DataFrame(rows).set_index('t0')
        df.index.name = None
        return df

    @staticmethod
    def apply_barriers(
        close: pd.Series,
        events: pd.DataFrame,
        pt_multiplier: float = TRIPLE_BARRIER_PT_MULTIPLIER,
        sl_multiplier: float = TRIPLE_BARRIER_SL_MULTIPLIER,
    ) -> pd.DataFrame:
        """
        Apply triple-barrier labeling to a price (or P&L) series.

        Parameters
        ----------
        close : pd.Series
            Price series. For Mode B, pass the options P&L series directly.
        events : pd.DataFrame
            Index = entry timestamps. Required columns:
              t1   : vertical barrier exit timestamp
              trgt : vol-scaled barrier width (daily vol at entry)
            Optional column:
              side : direction +1 or -1 (default +1 for all events)
        pt_multiplier : float
            Upper-barrier width multiplier. Set to 0 to disable upper barrier.
        sl_multiplier : float
            Lower-barrier width multiplier. Set to 0 to disable lower barrier.

        Returns
        -------
        pd.DataFrame indexed by entry timestamp, columns:
            exit_time : timestamp of first barrier touch
            label     : {-1, 0, +1}
            ret       : price return from entry to exit (or P&L difference
                        for Mode B series)
            barrier_hit : 'upper', 'lower', or 'vertical'
        """
        results = []
        for t0, event in events.iterrows():
            t1 = event['t1']
            trgt = event['trgt']
            side = int(event.get('side', 1))

            path = close.loc[t0:t1]
            if len(path) < 2:
                continue

            entry_price = float(path.iloc[0])

            # Upper barrier (profit target)
            upper: Optional[float]
            if pt_multiplier > 0:
                upper = entry_price * (1 + pt_multiplier * trgt * side)
            else:
                upper = None

            # Lower barrier (stop-loss)
            lower: Optional[float]
            if sl_multiplier > 0:
                lower = entry_price * (1 - sl_multiplier * trgt * side)
            else:
                lower = None

            # Walk the path and find the first barrier touch
            first_touch = t1
            label = 0
            barrier_hit = 'vertical'

            for t, price in path.iloc[1:].items():
                price = float(price)
                if upper is not None and price >= upper:
                    first_touch = t
                    label = 1 * side
                    barrier_hit = 'upper'
                    break
                if lower is not None and price <= lower:
                    first_touch = t
                    label = -1 * side
                    barrier_hit = 'lower'
                    break

            exit_price = float(close.loc[first_touch])
            ret = (exit_price - entry_price) / entry_price

            results.append({
                'entry_time':  t0,
                'exit_time':   first_touch,
                'label':       label,
                'ret':         ret,
                'barrier_hit': barrier_hit,
            })

        if not results:
            return pd.DataFrame(
                columns=['exit_time', 'label', 'ret', 'barrier_hit']
            )

        return (
            pd.DataFrame(results)
            .set_index('entry_time')
        )


class SampleWeights:
    """
    Uniqueness weighting for overlapping labels.

    Standard ML training treats each observation as equally informative.
    For financial time series with multi-day holding periods, labels overlap
    structurally — information from the same price path appears in multiple
    training observations. SampleWeights downweights each observation by its
    average uniqueness across its label window.

    For options strategies with 45-DTE positions, almost all observations in
    a typical backtest window overlap with their neighbors. Not applying
    uniqueness weights is equivalent to inflating the effective sample size
    by a factor that grows with holding period / sampling frequency.

    Workflow:
        t1 = labeled['exit_time']  # Series: entry_time → exit_time
        weights = SampleWeights.compute(t1, close.index)

    Ref: LdP AFML Ch.4, pp.59-72.
    """

    @staticmethod
    def compute_concurrency(
        t1: pd.Series,
        close_index: pd.DatetimeIndex,
    ) -> pd.Series:
        """
        Count the number of concurrent active labels at each timestamp.

        A label initiated at t0 with exit at t1 is "active" at every bar
        in [t0, t1]. Concurrency at timestamp t = number of active labels
        that span t.

        Parameters
        ----------
        t1 : pd.Series
            Index = entry timestamps, values = exit timestamps.
        close_index : pd.DatetimeIndex
            Full bar index of the price series.

        Returns
        -------
        pd.Series indexed by close_index with integer concurrency counts.
        """
        concurrency = pd.Series(0, index=close_index, dtype=int)
        for t0, end in t1.items():
            try:
                concurrency.loc[t0:end] += 1
            except KeyError:
                continue
        return concurrency

    @staticmethod
    def compute_uniqueness(
        t1: pd.Series,
        close_index: pd.DatetimeIndex,
    ) -> pd.Series:
        """
        Compute the average uniqueness of each label.

        Uniqueness at bar t within label [t0, t1] = 1 / concurrency(t).
        Average uniqueness of label [t0, t1] = mean(1 / concurrency(t))
        over all bars t in [t0, t1] where concurrency > 0.

        A uniqueness of 1.0 means the label window has no overlap with any
        other active label — it is the only claim on that stretch of data.
        A uniqueness of 0.1 means 10 labels are simultaneously active on
        average; this label contributes ~1/10th of independent information.

        Parameters
        ----------
        t1 : pd.Series
            Index = entry timestamps, values = exit timestamps.
        close_index : pd.DatetimeIndex
            Full bar index of the price series.

        Returns
        -------
        pd.Series indexed by entry timestamps, values in (0, 1].
        """
        conc = SampleWeights.compute_concurrency(t1, close_index)
        uniqueness = pd.Series(index=t1.index, dtype=float)
        for t0, end in t1.items():
            try:
                window = conc.loc[t0:end]
            except KeyError:
                uniqueness.loc[t0] = 1.0
                continue
            window_nonzero = window[window > 0]
            if len(window_nonzero) > 0:
                uniqueness.loc[t0] = float((1.0 / window_nonzero).mean())
            else:
                uniqueness.loc[t0] = 1.0
        return uniqueness

    @staticmethod
    def compute(
        t1: pd.Series,
        close_index: pd.DatetimeIndex,
        normalize: bool = True,
    ) -> pd.Series:
        """
        Compute sample weights from average uniqueness.

        This is the primary entry point for callers. Returns weights
        ready for use as `sample_weight` in sklearn estimators.

        Parameters
        ----------
        t1 : pd.Series
            Index = entry timestamps, values = exit timestamps.
        close_index : pd.DatetimeIndex
            Full bar index of the price series.
        normalize : bool
            If True, weights sum to len(t1) (mean weight = 1.0).
            Preserves the scale of sklearn loss functions.

        Returns
        -------
        pd.Series of weights indexed by entry timestamps.
        """
        weights = SampleWeights.compute_uniqueness(t1, close_index)
        if normalize and weights.sum() > 0:
            weights = weights / weights.mean()
        return weights
