#!/bin/bash
# scripts/cron_weekly.sh
# Full history pull + COT. Run Sunday evenings.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

if [ -f "$PROJECT_ROOT/venv/bin/activate" ]; then
    source "$PROJECT_ROOT/venv/bin/activate"
elif [ -f "$PROJECT_ROOT/.venv/bin/activate" ]; then
    source "$PROJECT_ROOT/.venv/bin/activate"
else
    echo "ERROR: Could not find virtualenv." >&2
    exit 1
fi

cd "$PROJECT_ROOT"

LOGFILE="$PROJECT_ROOT/logs/cron.log"
mkdir -p "$PROJECT_ROOT/logs"

{
    echo ""
    echo "========================================"
    echo "Weekly full refresh started: $(date)"
    echo "========================================"

    python systems/data_feeds/macro_feed.py --full \
        && echo "Full refresh: OK" \
        || echo "Full refresh: FAILED"

    python -c "
from systems.data_feeds.macro_feed import build_fred_client, fetch_calendar_data
from systems.utils.db import get_connection
fetch_calendar_data(build_fred_client(), get_connection())
print('Calendar: OK')
" || echo "Calendar fetch: FAILED"

    echo "Weekly refresh finished: $(date)"

} >> "$LOGFILE" 2>&1
