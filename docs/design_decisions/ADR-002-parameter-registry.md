# ADR-002 — Versioned parameter registry replaces config-constant tunables

**Date:** 2026-07-06 · **Status:** accepted

## Context
Granular user control over the parameters that determine component outputs is
a central v1.0 requirement. v0.5 spread tunables across ~60 config.py
constants plus hardcoded module values, with a known weights-duplication bug
(config.py vs RegimeClassifier.WEIGHTS).

## Decision
- One dataclass per component in `systems/params/models.py`; code defaults
  mirror v0.5 exactly. `FIELD_SPECS` metadata (bounds/help/guarded/recompute)
  drives GUI forms and validation.
- Versioned storage in `trading.db:parameter_versions`; every save is a new
  version; rollback re-activates as a new version (append-only audit trail).
- Every run stamps `all_active_hashes()` — reproducibility extends Priya's
  discipline system-wide.
- config.py keeps the legacy names working via PEP 562 `__getattr__` →
  `systems/params/compat.py`, returning defensive copies with original
  container types (tuples restored). Refactored engines call `get_params()`
  directly and see edits live; facade consumers bind at import and pick up
  edits on their next fresh process (jobs run as fresh subprocesses).
- Research gates are `guarded`: editable, but loudly logged and stamped.
- Dataclasses, not pydantic, deliberately: zero new dependencies in the
  engine path and no pydantic v1/v2 coupling.

## Consequences
- CLAUDE.md Rule 1 changes from "all paths/constants from config.py" to
  "paths from config.py; tunables from the registry".
- Behavior-neutrality is enforced by `scripts/golden_master.py`; the seed
  values ARE the v0.5 values.
- A locked registry degrades to code defaults with a loud warning — a
  pipeline never crashes because the GUI was mid-edit.
