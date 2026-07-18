#!/bin/bash
# scripts/cron_pipeline.sh
# Called by cron. Uses absolute paths — do not use relative paths here.

set -euo pipefail

# ── Resolve project root (one level up from this script) ──────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# ── Activate virtualenv ───────────────────────────────────────────────────────
# Detect venv location — check common names
if [ -f "$PROJECT_ROOT/venv/bin/activate" ]; then
    VENV_ACTIVATE="$PROJECT_ROOT/venv/bin/activate"
elif [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    VENV_ACTIVATE="$PROJECT_ROOT/.venv/bin/activate"
else
    echo "ERROR: Could not find virtualenv. Tried venv/ and .venv/" >&2
    exit 1
fi

source "$VENV_ACTIVATE"

# ── Run pipeline ──────────────────────────────────────────────────────────────
cd "$PROJECT_ROOT"

LOGFILE="$PROJECT_ROOT/logs/cron.log"
mkdir -p "$PROJECT_ROOT/logs"

{
    echo ""
    echo "========================================"
    echo "Cron pipeline started: $(date)"
    echo "========================================"

    python systems/data_feeds/macro_feed.py \
        && echo "Feed: OK" \
        || echo "Feed: FAILED"

    python -c "
from systems.signals.regime_classifier import RegimeClassifier
r = RegimeClassifier().classify(persist=True)
print(f'Regime: {r.regime} ({r.composite_score:+.2f})')
" && echo "Classifier: OK" || echo "Classifier: FAILED"

    echo "Pipeline finished: $(date)"

} >> "$LOGFILE" 2>&1
