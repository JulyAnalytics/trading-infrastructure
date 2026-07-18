#!/bin/bash
# Phase 0 verification gauntlet — one shot, fail-fast.
#
# Proves the parameter-registry migration is behavior-neutral by running the
# golden-master capture against the ORIGINAL code (restored temporarily),
# then against the migrated code, and diffing. Then seeds the registry and
# runs the platform verify suite.
#
# Usage: bash scripts/run_phase0_gauntlet.sh <scratch_dir>
#   <scratch_dir> must contain orig_config.py (pre-migration working-tree
#   config.py — it had uncommitted changes, so git cannot restore it).
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCRATCH="${1:?usage: run_phase0_gauntlet.sh <scratch_dir>}"
cd "$REPO"

CLS="systems/signals/regime_classifier.py"
ENG="systems/sarah/scenario_engine.py"
step() { printf '\n━━━ %s ━━━\n' "$*"; }

[ -f "$SCRATCH/orig_config.py" ] || { echo "missing $SCRATCH/orig_config.py"; exit 2; }

step "0. Preserve migrated versions"
mkdir -p "$SCRATCH/new"
cp config.py "$SCRATCH/new/config.py"
cp "$CLS"    "$SCRATCH/new/regime_classifier.py"
cp "$ENG"    "$SCRATCH/new/scenario_engine.py"

restore_new() {
  cp "$SCRATCH/new/config.py"            config.py
  cp "$SCRATCH/new/regime_classifier.py" "$CLS"
  cp "$SCRATCH/new/scenario_engine.py"   "$ENG"
}
trap restore_new EXIT   # never leave the tree in the half-restored state

step "1. Restore ORIGINAL code (config from scratch copy; engines from git HEAD)"
cp "$SCRATCH/orig_config.py" config.py
git show "HEAD:$CLS" > "$CLS"
git show "HEAD:$ENG" > "$ENG"

step "2. Golden master BEFORE (original code)"
python3 scripts/golden_master.py capture "$SCRATCH/golden_before.json"

step "3. Re-apply migrated code"
restore_new

step "4. Golden master AFTER (migrated code)"
python3 scripts/golden_master.py capture "$SCRATCH/golden_after.json"

step "5. Compare"
python3 scripts/golden_master.py compare "$SCRATCH/golden_before.json" "$SCRATCH/golden_after.json"

step "6. Seed registry + legacy-name resolution check"
python3 scripts/migrate_params.py --check

step "7. Platform verify suite"
python3 scripts/verify_v1_platform.py

step "GAUNTLET GREEN — Phase 0 verified"
