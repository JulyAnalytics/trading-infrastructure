# systems/sarah/regime_library.py
"""
Stage 5: Historical Regime Library.

Surface state analog search with normalized feature vectors
and macro compatibility filtering.

This is a probability estimation tool for the distribution of outcomes
that historically followed similar surface states. It is NOT a prediction tool.

Feature vector: 6 dimensions, Z-score normalized before distance computation.
VVIX added as 7th dimension once sufficient history accumulated.
"""
from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional
from loguru import logger

from config import (
    VOL_DB_PATH, ANALOG_MIN_HISTORY_DAYS, VVIX_CONFIDENCE_MIN_DAYS
)
from systems.utils.db import get_connection


# ── Feature set ───────────────────────────────────────────────────────────────

SURFACE_FEATURES = [
    'atm_iv_30d',       # vol level
    'iv_rank',          # percentile context (already 0–1, still normalize)
    'ts_front_slope',   # near-term term structure shape
    'ts_back_slope',    # long-end term structure shape (catches humped)
    'skew_25d_rr',      # skew steepness (25Δ risk reversal)
    'vix_z1y',          # VIX vs. its own 1-year history
]

# VVIX added as 7th feature once VVIX_CONFIDENCE_MIN_DAYS of data accumulated
VVIX_FEATURE = 'vvix_z1y'


# ── Feature Vector ────────────────────────────────────────────────────────────

def build_normalized_feature_vector(
    snapshot: dict,
    feature_history: pd.DataFrame,
    include_vvix: bool = False,
) -> tuple[np.ndarray, list[str]]:
    """
    Six-dimensional surface state vector, Z-score normalized.
    Each feature is (value - historical_mean) / historical_std.

    After normalization, all features contribute equally to Euclidean distance.
    A 1-unit change = 1 standard deviation move in that feature.

    Args:
        snapshot: Current surface state as dict
        feature_history: DataFrame with all historical snapshots
        include_vvix: If True, add VVIX as 7th feature

    Returns:
        (normalized_vector, feature_names)
    """
    features = list(SURFACE_FEATURES)
    if include_vvix:
        features.append(VVIX_FEATURE)

    # Filter to features that exist in history
    available = [f for f in features if f in feature_history.columns]
    if not available:
        logger.warning("No features available in history for normalization")
        return np.zeros(len(features)), features

    means = feature_history[available].mean()
    stds  = feature_history[available].std()
    stds  = stds.replace(0, 1)  # avoid division by zero on constant features

    raw = np.array([snapshot.get(f, 0.0) for f in available])
    normalized = (raw - means.values) / stds.values

    return normalized, available


def surface_similarity(
    query_vector:     np.ndarray,
    candidate_vector: np.ndarray,
) -> float:
    """
    Euclidean distance on normalized vectors.
    Lower distance = more similar. Convert to similarity score in [0, 1].
    similarity = 1 / (1 + dist)  maps [0, ∞) to (0, 1]
    """
    dist = np.linalg.norm(query_vector - candidate_vector)
    return 1.0 / (1.0 + dist)


# ── VIX/VVIX Signals ─────────────────────────────────────────────────────────

def compute_vix_vvix_signals(
    vix:          float,
    vvix:         Optional[float],
    vix_history:  pd.Series,
    vvix_history: Optional[pd.Series] = None,
) -> dict:
    """
    Compute VIX and VVIX normalized signals.

    Key signals:
    - vix_z1y:  VIX normalized by its 1-year history
    - vvix_z1y: VVIX normalized by its 1-year history (if available)
    - vvix_vix_ratio: vol-of-vol per unit of vol level
      Elevated (>6.0): market uncertain about vol path
      Typical range: 3.5–6.0
    - pre_transition_flag: VVIX elevated while VIX is not
    """
    # VIX z-score
    vix_z1y = 0.0
    if len(vix_history) >= 252:
        rolling_mean = vix_history.rolling(252).mean().iloc[-1]
        rolling_std  = vix_history.rolling(252).std().iloc[-1]
        if rolling_std > 0:
            vix_z1y = (vix - rolling_mean) / rolling_std

    # VVIX z-score (if available)
    vvix_z1y = None
    ratio = None
    pre_transition_flag = False

    if vvix is not None and vvix_history is not None and len(vvix_history) >= 252:
        rolling_mean = vvix_history.rolling(252).mean().iloc[-1]
        rolling_std  = vvix_history.rolling(252).std().iloc[-1]
        if rolling_std > 0:
            vvix_z1y = (vvix - rolling_mean) / rolling_std

        ratio = vvix / vix if vix > 0 else None

        # Pre-transition: VVIX elevated while VIX is not
        pre_transition_flag = (vvix_z1y is not None and vvix_z1y > 1.5 and vix_z1y < 0.5)

    return {
        'vix':                 vix,
        'vvix':                vvix,
        'vix_z1y':             round(vix_z1y, 4),
        'vvix_z1y':            round(vvix_z1y, 4) if vvix_z1y is not None else None,
        'vvix_vix_ratio':      round(ratio, 2) if ratio is not None else None,
        'pre_transition_flag': pre_transition_flag,
        'pre_transition_note': (
            'VVIX elevated relative to its history while VIX is not. '
            'Historically precedes regime transitions. '
            'Treat as a caution flag, not a timing signal.'
            if pre_transition_flag else None
        ),
    }


# ── Analog Search ─────────────────────────────────────────────────────────────

def _regimes_compatible(regime_a: str, regime_b: str) -> bool:
    """
    Conservative compatibility: regimes must not be opposites.
    RISK_OFF_STRESS is incompatible with RISK_ON_LOW_VOL.
    All other combinations are treated as compatible.
    """
    incompatible_pairs = {
        ('RISK_OFF_STRESS', 'RISK_ON_LOW_VOL'),
        ('RISK_ON_LOW_VOL', 'RISK_OFF_STRESS'),
    }
    return (regime_a, regime_b) not in incompatible_pairs


def analog_search(
    current_snapshot:      dict,
    historical_snapshots:  pd.DataFrame,
    macro_filter:          dict,
    n_results:             int = 10,
    include_vvix:          bool = False,
) -> pd.DataFrame:
    """
    Two-stage analog search:
      Stage 1: Surface similarity (normalized Euclidean distance)
      Stage 2: Macro regime compatibility filter

    Returns top N surface-similar states that pass the macro filter.

    Args:
        current_snapshot: Current surface state as dict
        historical_snapshots: DataFrame of all historical vol_signals rows
        macro_filter: Dict with optional keys:
            'exclude_zero_rate_era' (bool): exclude pre-2022 if current is rate-positive
            'require_regime_match' (bool): filter by compatible regimes
            'current_regime' (str): current Marcus regime
        n_results: Number of results to return
        include_vvix: Whether to include VVIX in feature vector

    Returns:
        DataFrame with columns: date, similarity, and all original signal columns
    """
    if len(historical_snapshots) < ANALOG_MIN_HISTORY_DAYS:
        logger.warning(
            "Only {} days of history (minimum {}). Results may be unreliable.",
            len(historical_snapshots), ANALOG_MIN_HISTORY_DAYS
        )

    # Stage 1: Normalize and compute all pairwise surface distances
    query_vec, features = build_normalized_feature_vector(
        current_snapshot, historical_snapshots, include_vvix
    )

    results = []
    for idx, row in historical_snapshots.iterrows():
        cand_vec, _ = build_normalized_feature_vector(
            row.to_dict(), historical_snapshots, include_vvix
        )
        sim = surface_similarity(query_vec, cand_vec)
        results.append({
            'date': idx if isinstance(idx, str) else str(idx),
            'similarity': sim,
            **{f: row.get(f) for f in features},
            'macro_regime': row.get('macro_regime', 'unknown'),
        })

    results_df = pd.DataFrame(results).sort_values('similarity', ascending=False)

    # Stage 2: Macro compatibility filter
    if macro_filter.get('exclude_zero_rate_era', False):
        results_df = results_df[results_df['date'] >= '2022-01-01']

    if macro_filter.get('require_regime_match', False):
        current_regime = macro_filter.get('current_regime', '')
        results_df = results_df[
            results_df['macro_regime'].apply(
                lambda r: _regimes_compatible(r, current_regime)
            )
        ]

    return results_df.head(n_results)


def get_historical_snapshots(ticker: str) -> pd.DataFrame:
    """
    Load all historical vol_signals for ticker from trading.db.
    Used as input to analog_search.
    """
    conn = get_connection(VOL_DB_PATH)
    try:
        df = conn.execute(
            "SELECT * FROM vol_signals WHERE ticker = ? ORDER BY date",
            [ticker]
        ).fetchdf()
        if not df.empty and 'date' in df.columns:
            df = df.set_index('date')
        return df
    finally:
        conn.close()


def get_vvix_history() -> pd.Series:
    """Load VVIX history from vvix_daily table in trading.db."""
    conn = get_connection(VOL_DB_PATH)
    try:
        df = conn.execute(
            "SELECT date, vvix FROM vvix_daily ORDER BY date"
        ).fetchdf()
        if df.empty:
            return pd.Series(dtype=float)
        return df.set_index('date')['vvix'].sort_index()
    except Exception:
        return pd.Series(dtype=float)
    finally:
        conn.close()


def get_vix_history() -> pd.Series:
    """Load VIX history from macro.db macro_series table."""
    from config import DUCKDB_PATH
    conn = get_connection(DUCKDB_PATH)
    try:
        df = conn.execute(
            "SELECT date, value FROM macro_series "
            "WHERE series_id = 'vix' ORDER BY date"
        ).fetchdf()
        if df.empty:
            return pd.Series(dtype=float)
        return df.set_index('date')['value'].sort_index()
    except Exception:
        return pd.Series(dtype=float)
    finally:
        conn.close()


# ── Event Library ─────────────────────────────────────────────────────────────

def load_event_library(path: str = "data/events/regime_events.yaml") -> list[dict]:
    """
    Load the named historical event library from YAML.
    Returns list of event dicts.
    """
    import yaml
    from pathlib import Path

    p = Path(path)
    if not p.exists():
        logger.warning("Event library not found at {}", path)
        return []

    data = yaml.safe_load(p.read_text())
    events = data.get('events', [])
    logger.info("Loaded {} events from regime library", len(events))
    return events


def event_browser(event_id: str, library_path: str = "data/events/regime_events.yaml") -> Optional[dict]:
    """
    Retrieve a single named event by ID.
    Returns the full event dict for display, or None if not found.
    """
    events = load_event_library(library_path)
    for e in events:
        if e.get('id') == event_id:
            return e
    logger.warning("Event '{}' not found in library", event_id)
    return None


def list_events(library_path: str = "data/events/regime_events.yaml") -> list[dict]:
    """
    List all events in the library with summary info.
    Returns list of {id, name, acute_date, spot_move, vol_move}.
    """
    events = load_event_library(library_path)
    return [
        {
            'id':        e['id'],
            'name':      e['name'],
            'acute_date': e.get('dates', {}).get('acute'),
            'spot_move':  e.get('spot_move_pct'),
            'vol_move':   e.get('vol_move_vpts'),
            'duration':   e.get('duration_days'),
        }
        for e in events
    ]


# ── Pre-Transition Monitor ───────────────────────────────────────────────────

def pre_transition_monitor(
    vix:           float,
    vvix:          Optional[float],
    vix_history:   pd.Series,
    vvix_history:  Optional[pd.Series] = None,
) -> dict:
    """
    Daily pre-transition check.

    Flags if the current surface shows the VVIX/VIX pre-transition pattern
    or other early-warning surface configurations.

    Flags only — no recommendation, no directional label.

    Requires 252 days of VVIX history for z-score reliability.
    If insufficient history, returns with confidence='insufficient_history'.
    """
    signals = compute_vix_vvix_signals(vix, vvix, vix_history, vvix_history)

    # Confidence assessment
    if vvix_history is None or len(vvix_history) < 252:
        confidence = 'insufficient_history'
        confidence_note = (
            f'Only {len(vvix_history) if vvix_history is not None else 0} days of VVIX history. '
            'Need 252+ days for reliable z-score computation. '
            'Pre-transition flag may be unreliable.'
        )
    elif len(vvix_history) < VVIX_CONFIDENCE_MIN_DAYS:
        confidence = 'developing'
        confidence_note = (
            f'{len(vvix_history)} days of VVIX history (need {VVIX_CONFIDENCE_MIN_DAYS} for full confidence). '
            'Pre-transition flag is directionally informative but z-scores are noisy.'
        )
    else:
        confidence = 'reliable'
        confidence_note = None

    # Additional surface warning patterns
    warnings = []

    # Pattern 1: VVIX/VIX ratio elevated (>6.0)
    ratio = signals.get('vvix_vix_ratio')
    if ratio is not None and ratio > 6.0:
        warnings.append({
            'pattern':     'elevated_vol_of_vol',
            'description': f'VVIX/VIX ratio at {ratio:.1f} (>6.0). '
                           'Market uncertain about which vol level it is pricing.',
        })

    # Pattern 2: VIX z-score extreme (> 2.0)
    if signals['vix_z1y'] > 2.0:
        warnings.append({
            'pattern':     'vix_extreme',
            'description': f'VIX z-score at {signals["vix_z1y"]:.2f} (>2.0). '
                           'Vol significantly elevated vs. 1-year history.',
        })

    # Pattern 3: Pre-transition flag from compute_vix_vvix_signals
    if signals['pre_transition_flag']:
        warnings.append({
            'pattern':     'pre_transition',
            'description': signals['pre_transition_note'],
        })

    return {
        'date':               pd.Timestamp.now().strftime('%Y-%m-%d'),
        'vix_vvix_signals':   signals,
        'confidence':         confidence,
        'confidence_note':    confidence_note,
        'warnings':           warnings,
        'warning_count':      len(warnings),
        'note':               ('Pre-transition monitor provides flags only — not timing signals. '
                               'Treat elevated readings as context for position sizing and '
                               'hedging decisions, not as entry/exit triggers.'),
    }
