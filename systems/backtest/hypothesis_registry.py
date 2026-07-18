"""
Layer 2: Hypothesis Registration

Enforces pre-registration of every research hypothesis before any data is
examined. Stores hypotheses and running trial counts in DuckDB (trading.db)
for consistency with all other persistent state.

Architecture ref: v2.0 Layer 2, DD-11 (PBO must not be an optimisation
objective), DD-12 (effective N for correlated strategies).

Usage::

    reg = HypothesisRegistration()
    h_id = reg.register(
        hypothesis='VRP signal: sell 30-DTE straddles when IV rank > 0.7',
        dataset_id='SPY_2010_2024',
        signal_type='vol_surface',
        rationale='IVR above 0.7 historically precedes vol compression',
    )
    # later, each time a new parameter configuration is evaluated:
    trial_n = reg.increment_trial_count('SPY_2010_2024')
    n_total = reg.get_trial_count('SPY_2010_2024')
"""

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from config import (
    HYPOTHESIS_REGISTRY_DB,
    BACKTEST_DEFAULT_SIGNIFICANCE,
)
from systems.utils.db import get_connection


# ── DDL ───────────────────────────────────────────────────────────────────────

HYPOTHESIS_REGISTRY_DDL = """
CREATE TABLE IF NOT EXISTS hypothesis_registry (
    hypothesis_id  VARCHAR PRIMARY KEY,
    hypothesis     VARCHAR  NOT NULL,
    dataset_id     VARCHAR  NOT NULL,
    signal_type    VARCHAR  NOT NULL,
    rationale      VARCHAR  NOT NULL,
    content_hash   VARCHAR  NOT NULL,
    registered_at  TIMESTAMP NOT NULL,
    trial_count    INTEGER  DEFAULT 1
);
"""


def initialize_hypothesis_schema() -> None:
    """
    Ensure the hypothesis_registry table exists in trading.db.
    Called from systems/backtest/__init__.py on package import.
    Safe to call multiple times (CREATE TABLE IF NOT EXISTS).
    """
    conn = get_connection(HYPOTHESIS_REGISTRY_DB)
    try:
        conn.execute(HYPOTHESIS_REGISTRY_DDL)
    finally:
        conn.close()


# ── Main class ────────────────────────────────────────────────────────────────

class HypothesisRegistration:
    """
    Pre-register a research hypothesis before examining any data.

    Pre-registration enforcement:
        The `register()` method hashes the hypothesis content and
        timestamps the registration. Any analysis that cannot produce
        a hypothesis_id from this registry has not been pre-registered
        and is therefore inadmissible as confirmatory evidence.

    Multiple-testing correction:
        `adjusted_significance()` returns the Bonferroni-adjusted alpha
        for a given dataset based on its accumulated trial count. This
        is the significance threshold that should be applied to any
        permutation test on that dataset.

    Trial counting:
        Every strategy/parameter configuration evaluated on a given
        dataset increments the trial counter via `increment_trial_count()`.
        The counter feeds into DSR (Deflated Sharpe Ratio) in Layer 6.
        A Sharpe ratio without an associated trial count is
        informationally incomplete (LdP AFML p.205 — "Marcos' Third Law
        of Backtesting").
    """

    def __init__(self):
        # Ensure table exists (idempotent)
        initialize_hypothesis_schema()

    # ── Registration ─────────────────────────────────────────────────────────

    def register(
        self,
        hypothesis: str,
        dataset_id: str,
        signal_type: str,
        rationale: str,
    ) -> str:
        """
        Register a new hypothesis. Returns the hypothesis_id.

        If an identical hypothesis (same content hash) has already been
        registered for this dataset, returns the existing hypothesis_id
        without creating a duplicate and without incrementing the trial count.
        Registering is not a trial — running a parameter configuration is.

        Parameters
        ----------
        hypothesis  : Human-readable description of the hypothesis
        dataset_id  : Identifier for the dataset this hypothesis will be tested on
        signal_type : Category e.g. 'vol_surface', 'macro', 'technical'
        rationale   : Economic or empirical basis for the hypothesis
        """
        content_hash = self._hash_content(hypothesis, dataset_id, signal_type)
        existing_id = self._find_by_hash(content_hash)
        if existing_id:
            return existing_id

        hypothesis_id = self._generate_id(dataset_id, content_hash)
        registered_at = datetime.now(timezone.utc).replace(tzinfo=None)  # store as UTC naive

        conn = get_connection(HYPOTHESIS_REGISTRY_DB)
        try:
            conn.execute(
                """
                INSERT INTO hypothesis_registry
                    (hypothesis_id, hypothesis, dataset_id, signal_type,
                     rationale, content_hash, registered_at, trial_count)
                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                """,
                [
                    hypothesis_id,
                    hypothesis,
                    dataset_id,
                    signal_type,
                    rationale,
                    content_hash,
                    registered_at,
                ],
            )
        finally:
            conn.close()

        return hypothesis_id

    # ── Trial counting ────────────────────────────────────────────────────────

    def increment_trial_count(self, dataset_id: str) -> int:
        """
        Increment the trial counter for `dataset_id` and return the new count.

        Call this every time a new strategy / parameter configuration is
        evaluated on the dataset — before evaluating, so that the count
        reflects total attempts including the current one.

        This counter is a required input to DSR computation (Layer 6).
        """
        conn = get_connection(HYPOTHESIS_REGISTRY_DB)
        try:
            conn.execute(
                """
                UPDATE hypothesis_registry
                SET trial_count = trial_count + 1
                WHERE dataset_id = ?
                """,
                [dataset_id],
            )
            result = conn.execute(
                """
                SELECT MAX(trial_count) FROM hypothesis_registry
                WHERE dataset_id = ?
                """,
                [dataset_id],
            ).fetchone()
        finally:
            conn.close()

        return result[0] if result and result[0] is not None else 1

    def get_trial_count(self, dataset_id: str) -> int:
        """
        Return the total number of trials recorded for `dataset_id`.
        Returns 0 if no hypothesis has been registered for this dataset.
        """
        conn = get_connection(HYPOTHESIS_REGISTRY_DB)
        try:
            result = conn.execute(
                """
                SELECT MAX(trial_count) FROM hypothesis_registry
                WHERE dataset_id = ?
                """,
                [dataset_id],
            ).fetchone()
        finally:
            conn.close()

        return result[0] if result and result[0] is not None else 0

    # ── Significance threshold ────────────────────────────────────────────────

    def adjusted_significance(
        self,
        dataset_id: str,
        base_alpha: float = BACKTEST_DEFAULT_SIGNIFICANCE,
    ) -> float:
        """
        Return the Bonferroni-adjusted significance threshold for `dataset_id`.

        With N trials on a dataset, the family-wise error rate is controlled
        by testing each trial at alpha / N.

        Returns base_alpha unchanged if no trials are recorded (i.e., the
        first hypothesis on a new dataset is tested at the full alpha).
        """
        n = self.get_trial_count(dataset_id)
        if n <= 1:
            return base_alpha
        return base_alpha / n

    # ── Lookup / inspection ───────────────────────────────────────────────────

    def get(self, hypothesis_id: str) -> Optional[dict]:
        """Return the full registration record, or None if not found."""
        conn = get_connection(HYPOTHESIS_REGISTRY_DB)
        try:
            result = conn.execute(
                """
                SELECT hypothesis_id, hypothesis, dataset_id, signal_type,
                       rationale, content_hash, registered_at, trial_count
                FROM hypothesis_registry
                WHERE hypothesis_id = ?
                """,
                [hypothesis_id],
            ).fetchone()
        finally:
            conn.close()

        if result is None:
            return None
        keys = [
            'hypothesis_id', 'hypothesis', 'dataset_id', 'signal_type',
            'rationale', 'content_hash', 'registered_at', 'trial_count',
        ]
        return dict(zip(keys, result))

    def list_all(self, dataset_id: Optional[str] = None) -> list[dict]:
        """
        List all registered hypotheses, optionally filtered by dataset_id.
        """
        conn = get_connection(HYPOTHESIS_REGISTRY_DB)
        try:
            if dataset_id:
                rows = conn.execute(
                    """
                    SELECT hypothesis_id, hypothesis, dataset_id, signal_type,
                           rationale, content_hash, registered_at, trial_count
                    FROM hypothesis_registry
                    WHERE dataset_id = ?
                    ORDER BY registered_at
                    """,
                    [dataset_id],
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT hypothesis_id, hypothesis, dataset_id, signal_type,
                           rationale, content_hash, registered_at, trial_count
                    FROM hypothesis_registry
                    ORDER BY registered_at
                    """
                ).fetchall()
        finally:
            conn.close()

        keys = [
            'hypothesis_id', 'hypothesis', 'dataset_id', 'signal_type',
            'rationale', 'content_hash', 'registered_at', 'trial_count',
        ]
        return [dict(zip(keys, row)) for row in rows]

    # ── Private helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _hash_content(hypothesis: str, dataset_id: str, signal_type: str) -> str:
        payload = json.dumps(
            {'hypothesis': hypothesis, 'dataset_id': dataset_id, 'signal_type': signal_type},
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _generate_id(dataset_id: str, content_hash: str) -> str:
        timestamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')
        short_hash = content_hash[:8]
        safe_dataset = dataset_id.replace(' ', '_').replace('/', '_')[:24]
        return f"{safe_dataset}_{timestamp}_{short_hash}"

    def _find_by_hash(self, content_hash: str) -> Optional[str]:
        conn = get_connection(HYPOTHESIS_REGISTRY_DB)
        try:
            result = conn.execute(
                """
                SELECT hypothesis_id FROM hypothesis_registry
                WHERE content_hash = ?
                LIMIT 1
                """,
                [content_hash],
            ).fetchone()
        finally:
            conn.close()
        return result[0] if result else None
