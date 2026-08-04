## Diagnosis summary

**Fatal bug** — the `snapshot_pdf` job has failed 7× since 2026-07-18 (last success: `data/snapshots/macro_2026-07-17_173842.pdf`). At `systems/reports/snapshot_generator.py:196`, an `event_date` value read from DuckDB via `.df()` is a `pandas.Timestamp`, and subtracting `datetime.now().date()` raises `TypeError: unsupported operand type(s) for -: 'Timestamp' and 'datetime.date'`. The job exits 1, retries (a1, a2) fail identically, then `JobManager._retry_or_alert` raises an alert. It started 07-18 because that's when `macro_calendar` first got populated by `fetch_calendar_data`.

**Secondary issue** — `kaleido 1.3.0` (unpinned) no longer bundles Chromium; without Chrome installed locally, `render_chart_png` falls back to `_render_chart_matplotlib`, which draws text-only placeholder panels instead of real charts. PDF still builds but the two figures are placeholders.

**Blast-radius scan result** — exactly **2** confirmed instances of the date-arithmetic bug class, both reading `event_date` from `macro_calendar` via `.df()` and subtracting stdlib `date` inside an `iterrows()` loop. Every other date-math site in the repo was traced and is safe (uses `fetchone`/`fetchall`, explicitly normalizes types, or does no date math).

## Fix plan

### 1. Fix bug #1 — `systems/reports/snapshot_generator.py:196`
Normalize the `event_date` column to stdlib `date` right after the `.df()` call (around line 73), matching the existing defensive pattern used elsewhere (`macro_feed.py:196`, `regime_analytics.py`). This fixes the subtraction at line 196 and any downstream use in one stroke.
```python
calendar_df = conn.execute("""...""").df()
calendar_df["event_date"] = pd.to_datetime(calendar_df["event_date"]).dt.date
```
(Adds `import pandas as pd` if not already imported at top of file — it isn't currently.)

### 2. Fix bug #2 — `systems/dashboard/macro_dashboard.py:1022` (same bug class, hot path)
Same normalization right after the `.df()` call at line 1009, inside `build_calendar_widget()`:
```python
df = conn.execute("""...""").df()
df["event_date"] = pd.to_datetime(df["event_date"]).dt.date
```
`pd` and `date` are already imported in this file. This fixes the subtraction at line 1022; the `.strftime("%b %d")` at line 1045 keeps working (stdlib `date` has `.strftime`).

### 3. Fix chart rendering — pin legacy kaleido in `requirements.txt:34`
Change `kaleido` → `kaleido<1.0` (resolves to `0.2.1.post1`, which bundles its own Chromium and has zero external deps — the standard zero-hassle pairing for `plotly.write_image`). This is independent of the plotly compatibility concerns noted in the adjacent comment block (those are about `vectorbt`, not kaleido).
Then reinstall in the venv:
```
venv/bin/pip install 'kaleido<1.0'
```

### 4. Verification (no new code — just exercising the fix)
- Run `venv/bin/python -m systems.orchestration.run_job snapshot_pdf` and confirm a fresh `data/snapshots/macro_<ts>.pdf` is written.
- Confirm the PDF's two chart panels are real figures (not text placeholders) — validates the kaleido downgrade.
- Optional: re-trigger via the Jobs page ("Run now" on `snapshot_pdf`) to confirm the full scheduler→JobManager→subprocess path is green end-to-end.

## Out of scope (noted, not touching)
- `systems/reports/weekly_review.py` has its own separate PDF path (different artifact: `reports/weekly/`). It was not reported failing and wraps rendering in try/except that degrades to markdown-only. Last file `weekly_review_2026-07-18.pdf` exists (3,802 B). Leaving alone unless you want it audited too.
- The retired `scheduler.py` (root) also calls `generate_snapshot` but is hard-disabled (`sys.exit(2)`); not a live failure source.