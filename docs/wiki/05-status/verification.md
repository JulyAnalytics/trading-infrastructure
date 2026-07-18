# Verification — Results

**Gauntlet run: 2026-07-06 — GREEN.** The v1.0 migration's core promise —
default (seed) parameters produce output identical to v0.5 — is now
checked, not just assumed.

## What passed

| Check | Result |
|---|---|
| Golden master (config values, full Marcus classification incl. attribution + transition probability, scenario-engine grid/stress/kill/structures) | **identical**, before vs after, float tolerance 1e-9 |
| Legacy config-name resolution | all **47** names resolve through the registry facade |
| `verify_v1_platform.py` | **34/34** — registry seed/version/validate/rollback, guarded edits, facade container types, classifier weight assertion + params injection, scenario-engine params wiring, lock-fallback resilience |
| `verify_jordan.py` | **21/21** (after fixing one test-parameter bug, see below) — sizing formula + single-position cap, limit evaluation, verdict intake (fresh/GO/regime/stale), RCS bridge read-only guarantee, book assembly |
| API boot smoke test | `uvicorn systems.api.main:app` starts clean; `/health` (all six param hashes, both DBs, registry ok), `/api/params-hashes`, `/api/marcus/summary` (200, against **real** macro.db data), `/docs` all respond correctly |
| Frontend build | `npm install` (334 packages) + `npm run build` — `tsc -b` type-checks with **zero errors**, Vite production bundle succeeds |

## What this does NOT cover yet

- No manual/interactive browser click-through of the six workstation pages
  (Command Deck, Marcus, Sarah, Jordan, Params, Jobs) — only that the bundle
  compiles and one backend route was hit directly with `curl`.
- No live end-to-end job trigger (`POST /api/jobs` → subprocess → status
  update) — only that the job-table schema and `/health`'s `job_running`
  field work.
- Sarah's live endpoints (`/api/sarah/greeks`, `/scenario` pricing inputs)
  need yfinance network calls — untested this pass.
- `docs/audit/05_jordan_risk_layer.md` still not written.
- Phases 3/4/6 (Sarah data completions, Priya workbench, scheduler v2) are
  unbuilt, not just unverified.

Reasonable next step before relying on this daily: `venv/bin/python -m
uvicorn systems.api.main:app --port 8100` + `cd frontend && npm run dev` →
click through each page once
([running-and-operating.md](../04-workflows/running-and-operating.md)).

## Two environment bugs found and fixed during this run

1. **Corrupted venv** (Nextcloud sync artifact, not a code bug): the venv's
   interpreter symlinks (`venv/bin/python`, `python3`, `python3.11`) had been
   silently converted to plain-text files containing the symlink target
   instead of real symlinks, and every console-script shim's shebang line
   was hardcoded to a stale path from before the project moved cloud
   providers (`OneDrive-Personal/…` instead of the current `Nextcloud/…`
   location). Fix: recreated the three symlinks pointing at the pyenv
   3.11.9 interpreter, restored the executable bit venv-wide, and rewrote
   all 31 shim shebangs via `sed`. **Always use `venv/bin/python`**, not
   system `python3` (which has no pandas/duckdb/etc. at all).
2. **`py_vollib` missing from `requirements.txt`** despite being a genuine
   runtime dependency of `systems/utils/pricing.py` since v0.5 (pre-existing
   gap, not introduced by v1.0). Added it and reran
   `pip install -r requirements.txt`, which also pulled in `uvicorn[standard]`'s
   extras (`httptools`, `uvloop`, `watchfiles`) that a bare `uvicorn` install
   had left out.

## One test bug found and fixed

`verify_jordan.py`'s "uncapped sizing formula" check used
`entry=100, stop=96, risk_pct=0.01` against `JordanParams` **defaults**
(`max_single_position_pct=0.05`) — but that combination's uncapped notional
is 25% of NAV, which trips the 5%-of-NAV single-position cap the test
wasn't trying to exercise yet, so the assertion saw the *capped* result and
failed. The production code (`suggest_size` in
`systems/risk/verdict_intake.py`) was correct throughout — this was a
test-parameter oversight. Fixed by running the "pure formula" check under a
permissive `max_single_position_pct=1.0` and leaving the existing
tight-stop case (`stop=99.9`, which correctly triggers the cap) unchanged.

## Re-running the gauntlet

```bash
cd ~/Nextcloud/Trading/trading-infrastructure
PATH="$PWD/venv/bin:$PATH" bash scripts/run_phase0_gauntlet.sh <scratch_dir>
venv/bin/python scripts/verify_jordan.py
```

Scratch dir used this run:
`/private/tmp/claude-501/-Users-jun-Nextcloud-Trading-trading-infrastructure-docs/94c3e284-c4dc-4f53-9459-76fa4702be34/scratchpad`
(contains `orig_config.py`, needed because pre-migration `config.py` had
uncommitted changes `git show HEAD:` can't recover). If that temp dir is
gone, the v0.5 defaults are fully recorded in
[parameter-schemas.md](../03-contracts/parameter-schemas.md) and can
reconstruct it.

**Prepend `venv/bin` to `PATH`** (as above) so the gauntlet's internal
`python3` calls resolve to the project venv — its script shims now have
correct shebangs, but unqualified `python3` still depends on `$PATH`.

## If the golden master ever fails again

Do not rationalize a diff. The compare output names the exact path
(`$.marcus.scores.credit: …`) — fix the migration; the pre-migration
originals are recoverable from `git show HEAD:` (engines) and the scratch
copy or parameter-schemas.md (config values).
