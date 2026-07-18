"""
Layer 1: Data Audit Report

Validates datasets before they enter the backtest pipeline. Checks for
survivorship bias, look-ahead contamination, point-in-time integrity,
data gaps, bar type, and (for options data) spread realism.

Architecture ref: v2.0 Layer 1, DD-01 (bar type), Hilpisch (spread bounds).
"""

import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional

from config import (
    BACKTEST_MIN_OBSERVATIONS,
    BACKTEST_MIN_OPTIONS_OBS,
    SPREAD_FLOOR_OTM_SHORT,
    SPREAD_FLOOR_OTM_LONG,
    SPREAD_FLOOR_ATM_SHORT,
    SPREAD_FLOOR_ATM_LONG,
    SPREAD_FLOOR_ITM_SHORT,
    SPREAD_FLOOR_ITM_LONG,
)


class DataAuditReport:
    """
    Run a structured pre-flight audit on any dataset before it enters
    the backtest pipeline. Call `run_full_audit()` to execute all checks;
    inspect `flags` and `blockers` for results.

    Usage::

        audit = DataAuditReport()
        audit.set_bar_type('time')
        report = audit.run_full_audit(price_df, label='SPY daily')
        if audit.has_blockers():
            raise RuntimeError(audit.blocker_summary())

    Flags are non-fatal observations; blockers prevent the pipeline from
    proceeding.
    """

    # DD-01: Bar type metadata annotations
    BAR_TYPE_FLAGS = {
        'time': (
            'Time-bar data. Known pathologies: serial correlation, '
            'heteroskedasticity, non-normality may inflate significance. '
            'Apply Lo robust SE correction to all Sharpe estimates. '
            'Ref: LdP 2018 Pitfall #3.'
        ),
        'dollar': 'Dollar-bar data. Improved statistical properties per LdP.',
        'volume': 'Volume-bar data.',
        'tick':   'Tick-bar data.',
    }

    # Empirical spread floor by moneyness × maturity (Hilpisch Table 3.1).
    # Used in check_spread_realism().
    SPREAD_FLOORS = {
        'otm_short': SPREAD_FLOOR_OTM_SHORT,
        'otm_long':  SPREAD_FLOOR_OTM_LONG,
        'atm_short': SPREAD_FLOOR_ATM_SHORT,
        'atm_long':  SPREAD_FLOOR_ATM_LONG,
        'itm_short': SPREAD_FLOOR_ITM_SHORT,
        'itm_long':  SPREAD_FLOOR_ITM_LONG,
    }

    # Blanket floor: most liquid options still show ~3.7% relative spread.
    # Any observation below this is suspicious regardless of bucket.
    _BLANKET_SPREAD_FLOOR = SPREAD_FLOOR_ITM_LONG

    def __init__(self):
        self.flags: list[dict] = []
        self.blockers: list[dict] = []
        self.bar_type: Optional[str] = None
        self._run_at: Optional[datetime] = None

    # ── Bar type ──────────────────────────────────────────────────────────────

    def set_bar_type(self, bar_type: str) -> None:
        """
        Register the bar type for this dataset. Must be called before
        `run_full_audit()`. Time bars trigger a mandatory warning per DD-01.
        """
        if bar_type not in self.BAR_TYPE_FLAGS:
            raise ValueError(
                f"Unknown bar type '{bar_type}'. "
                f"Valid: {list(self.BAR_TYPE_FLAGS)}"
            )
        self.bar_type = bar_type
        if bar_type == 'time':
            self.flags.append({
                'check':    'BAR_TYPE_TIME',
                'severity': 'WARNING',
                'detail':   self.BAR_TYPE_FLAGS['time'],
            })

    # ── Core checks ───────────────────────────────────────────────────────────

    def check_minimum_observations(
        self,
        df: pd.DataFrame,
        options: bool = False,
    ) -> None:
        """Fail if fewer than the configured minimum observations are present."""
        n = len(df)
        threshold = BACKTEST_MIN_OPTIONS_OBS if options else BACKTEST_MIN_OBSERVATIONS
        label = 'options' if options else 'equity/macro'
        if n < threshold:
            self.blockers.append({
                'check':    'MIN_OBSERVATIONS',
                'severity': 'BLOCKER',
                'detail':   (
                    f"Dataset has {n} observations; minimum for {label} "
                    f"analysis is {threshold}. Extend history before proceeding."
                ),
            })

    def check_survivorship_bias(
        self,
        df: pd.DataFrame,
        universe_start: Optional[pd.Timestamp] = None,
    ) -> None:
        """
        Heuristic survivorship check. Flags if the dataset starts significantly
        after `universe_start` (suggesting delisted instruments were dropped),
        or if the index is missing any dates that would be expected for a
        continuously traded instrument.
        """
        if universe_start is not None and hasattr(df.index, 'min'):
            actual_start = pd.Timestamp(df.index.min())
            expected_start = pd.Timestamp(universe_start)
            gap_days = (actual_start - expected_start).days
            if gap_days > 30:
                self.flags.append({
                    'check':    'SURVIVORSHIP_BIAS',
                    'severity': 'WARNING',
                    'detail':   (
                        f"Dataset starts {gap_days} days after the declared "
                        f"universe start ({expected_start.date()}). If this "
                        "represents a filtered universe, survivorship bias "
                        "may inflate performance."
                    ),
                })

    def check_lookahead(
        self,
        df: pd.DataFrame,
        as_of: Optional[pd.Timestamp] = None,
    ) -> None:
        """
        Block if the dataset contains rows dated after `as_of` (default: today).
        Future-dated rows indicate a look-ahead contamination.
        """
        cutoff = as_of or pd.Timestamp.today().normalize()
        if not hasattr(df.index, 'max'):
            return
        latest = pd.Timestamp(df.index.max())
        if latest > cutoff:
            self.blockers.append({
                'check':    'LOOK_AHEAD',
                'severity': 'BLOCKER',
                'detail':   (
                    f"Dataset contains rows dated {latest.date()}, which is "
                    f"after the as-of cutoff ({cutoff.date()}). Remove future "
                    "rows before proceeding."
                ),
            })

    def check_point_in_time_integrity(
        self,
        df: pd.DataFrame,
        timestamp_col: Optional[str] = None,
    ) -> None:
        """
        Flag if the DataFrame has a non-monotonic index (records out of
        chronological order) or duplicate index values.
        """
        if not hasattr(df.index, 'is_monotonic_increasing'):
            return
        if not df.index.is_monotonic_increasing:
            self.blockers.append({
                'check':    'NON_MONOTONIC_INDEX',
                'severity': 'BLOCKER',
                'detail':   (
                    "Index is not strictly monotonically increasing. "
                    "Sort the DataFrame by date before proceeding."
                ),
            })
        n_dupes = df.index.duplicated().sum()
        if n_dupes > 0:
            self.flags.append({
                'check':    'DUPLICATE_INDEX',
                'severity': 'WARNING',
                'detail':   (
                    f"Index contains {n_dupes} duplicate value(s). "
                    "Verify that deduplication is intentional."
                ),
            })

    def check_data_gaps(
        self,
        df: pd.DataFrame,
        freq: str = 'B',
        max_gap_days: int = 5,
    ) -> None:
        """
        Flag unexpectedly large gaps in a date-indexed DataFrame.
        `freq='B'` assumes business-day data; adjust for intraday.
        """
        if not hasattr(df.index, 'to_series'):
            return
        try:
            idx = pd.DatetimeIndex(df.index)
        except Exception:
            return
        gaps = idx.to_series().diff().dt.days.dropna()
        # Business-day data: normal gap is 1 (weekday) or up to 3 (over weekend)
        # Anything > max_gap_days is unexpected
        large_gaps = gaps[gaps > max_gap_days]
        if not large_gaps.empty:
            worst = large_gaps.max()
            self.flags.append({
                'check':    'DATA_GAPS',
                'severity': 'WARNING',
                'detail':   (
                    f"Found {len(large_gaps)} gap(s) exceeding {max_gap_days} "
                    f"calendar days (largest: {int(worst)} days). Verify that "
                    "gaps correspond to expected closures (holidays, halts)."
                ),
            })

    def check_missing_values(self, df: pd.DataFrame) -> None:
        """Flag columns with significant NaN proportions (> 5%)."""
        for col in df.columns:
            null_pct = df[col].isna().mean()
            if null_pct > 0.05:
                self.flags.append({
                    'check':    'MISSING_VALUES',
                    'severity': 'WARNING',
                    'detail':   (
                        f"Column '{col}' has {null_pct:.1%} missing values. "
                        "Imputation or exclusion is required before feature "
                        "engineering."
                    ),
                })

    # ── Options-specific ─────────────────────────────────────────────────────

    def check_spread_realism(self, options_df: pd.DataFrame) -> None:
        """
        Validate that bid/ask spreads are within empirically documented bounds.
        Spreads below the Hilpisch floor suggest data errors or unrealistically
        favourable fill assumptions.

        Ref: Hilpisch Table 3.1 — DJIA components 1996-2010. Architecture DD-10.
        """
        if 'bid' not in options_df.columns or 'ask' not in options_df.columns:
            self.flags.append({
                'check':    'SPREAD_REALISM_SKIPPED',
                'severity': 'INFO',
                'detail':   (
                    "No 'bid'/'ask' columns found. Spread realism check skipped. "
                    "If this is live options data, add bid/ask before proceeding."
                ),
            })
            return

        mid = (options_df['bid'] + options_df['ask']) / 2
        spread_pct = (options_df['ask'] - options_df['bid']) / mid.replace(0, np.nan)

        # Blanket floor: 3.7% (ITM long maturity — most liquid bucket)
        below_floor_pct = (spread_pct < self._BLANKET_SPREAD_FLOOR).mean()
        if below_floor_pct > 0.10:
            self.flags.append({
                'check':    'SPREAD_BELOW_EMPIRICAL_FLOOR',
                'severity': 'WARNING',
                'detail':   (
                    f"{below_floor_pct:.1%} of observations have relative spread "
                    f"below {self._BLANKET_SPREAD_FLOOR:.1%}. Hilpisch Table 3.1 "
                    "documents minimum relative spreads of 3.7% for the most "
                    "liquid options (ITM long maturity). Verify data quality or "
                    "document why these spreads are realistic."
                ),
            })

        # Zero or negative spreads are always blockers
        zero_spread = (spread_pct <= 0).sum()
        if zero_spread > 0:
            self.blockers.append({
                'check':    'ZERO_OR_NEGATIVE_SPREAD',
                'severity': 'BLOCKER',
                'detail':   (
                    f"{zero_spread} rows have zero or negative bid/ask spread. "
                    "This indicates data corruption or mid-price approximation "
                    "used as both bid and ask."
                ),
            })

        # Unrealistically wide spreads (> 200% relative) may indicate stale quotes
        very_wide = (spread_pct > 2.0).sum()
        if very_wide > 0:
            self.flags.append({
                'check':    'VERY_WIDE_SPREAD',
                'severity': 'WARNING',
                'detail':   (
                    f"{very_wide} rows have relative spread > 200%. These may "
                    "be stale or illiquid quotes. Consider excluding from "
                    "fill-price calculations."
                ),
            })

    # ── Orchestrator ─────────────────────────────────────────────────────────

    def run_full_audit(
        self,
        df: pd.DataFrame,
        label: str = '',
        options: bool = False,
        universe_start: Optional[pd.Timestamp] = None,
        as_of: Optional[pd.Timestamp] = None,
        freq: str = 'B',
        max_gap_days: int = 5,
    ) -> dict:
        """
        Run all applicable checks and return the audit report dict.

        Params
        ------
        df             : the dataset to audit
        label          : human-readable name for logging
        options        : use the lower (6-month) minimum observation threshold
                         and run the spread realism check
        universe_start : declared start of the investable universe
        as_of          : look-ahead cutoff (defaults to today)
        freq           : expected bar frequency for gap detection ('B', 'D', etc.)
        max_gap_days   : gap size (calendar days) that triggers a warning
        """
        self._run_at = datetime.utcnow()

        if self.bar_type is None:
            self.flags.append({
                'check':    'BAR_TYPE_NOT_SET',
                'severity': 'WARNING',
                'detail':   (
                    "bar_type not set. Call set_bar_type() before run_full_audit(). "
                    "Defaulting to 'time' assumption — apply Lo robust SE correction."
                ),
            })

        self.check_minimum_observations(df, options=options)
        self.check_survivorship_bias(df, universe_start=universe_start)
        self.check_lookahead(df, as_of=as_of)
        self.check_point_in_time_integrity(df)
        self.check_data_gaps(df, freq=freq, max_gap_days=max_gap_days)
        self.check_missing_values(df)

        if options:
            self.check_spread_realism(df)

        return self.report(label=label)

    # ── Output helpers ────────────────────────────────────────────────────────

    def report(self, label: str = '') -> dict:
        """Return a structured dict representation of the audit."""
        return {
            'label':     label,
            'bar_type':  self.bar_type,
            'run_at':    self._run_at.isoformat() if self._run_at else None,
            'n_flags':   len(self.flags),
            'n_blockers': len(self.blockers),
            'cleared':   len(self.blockers) == 0,
            'flags':     self.flags,
            'blockers':  self.blockers,
        }

    def has_blockers(self) -> bool:
        return len(self.blockers) > 0

    def blocker_summary(self) -> str:
        lines = [f"DataAuditReport: {len(self.blockers)} blocker(s) — cannot proceed:"]
        for b in self.blockers:
            lines.append(f"  [{b['check']}] {b['detail']}")
        return '\n'.join(lines)

    def __repr__(self) -> str:
        return (
            f"DataAuditReport(bar_type={self.bar_type!r}, "
            f"flags={len(self.flags)}, blockers={len(self.blockers)}, "
            f"cleared={not self.has_blockers()})"
        )
