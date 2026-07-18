# Frontend — the React Workstation

**Status:** 🟡 unverified (needs `npm install` + boot) · **Code:** `frontend/`
**Stack:** Vite + React 18 + TypeScript · react-plotly.js over `plotly.js-dist-min` · react-router
**Dev:** `npm run dev` → http://localhost:5173 (proxies `/api` + `/health` to :8100)

One dark-themed app (palette matches the legacy Dash look, `#1a1a2e` panels)
with a left nav: Command Deck · Marcus · Sarah · Priya (placeholder) ·
Jordan · Parameters · Jobs & Health.

## Pages

### Command Deck (`pages/CommandDeck.tsx`) — the 7am screen
Fragility-first hierarchy (Marcus improvements Gap 3): **fragility level**
(STABLE→BREAKING, color-coded) is the headline; the regime label is a badge
beside it. Then: 30d transition probability, 7-day composite momentum,
regime-contract freshness (stale = red), missing inputs, active-divergence
banner with duration/trend (or an explicit "no divergence" all-clear).
Below: per-ticker vol snapshot, latest research verdict chips
(GO/NO_GO · haircut SR · DSR · PBO), recent jobs.

### Marcus (`pages/MarcusPage.tsx`)
Regime banner → component score bars (±1, green/red) with staleness chips →
attribution table (drivers/contradictors, flip-watch context) →
**interpretation cards** (vol + credit: headline, regime-consistency, amber
watch-condition) → **state vector card** (sub-composites, distances to
CAUTION/STRESS, aligned/contradicting chips) + **historical analogues
table** → implications headline with reliability chip and caveat → regime
history chart → tabbed series charts (VIX/HY/curve/breakeven, threshold
lines drawn from the live registry values) → transitions, calendar, COT,
regime-conditional returns table (low-sample rows flagged).

### Sarah (`pages/SarahPage.tsx`)
Vol monitor table (click a row to focus a ticker) → IV-vs-RV +
term-structure charts → **Greeks tool** form → interpretation block →
**Scenario lab**: P&L heatmap with DTE-checkpoint tabs, stress-scenario
table (from the editable registry library), kill-scenario card with its
assumptions labeled as parameters.

### Jordan (`pages/JordanPage.tsx`)
Breach banner (red) or all-clear → book table (RCS rows deep-link to :8099;
manual rows closable) → *Analyze book* / *Analyze + stress* → net-exposure
and limit-check cards (per-position pricing failures listed, never fatal) →
stress table with worst-case chip → **verdict intake** checklist →
**position sizer** → add-manual-position form.

### Parameters (`pages/ParamsPage.tsx`) — the control surface
Component tabs → a form generated from `FIELD_SPECS`: scalars as typed
inputs, dicts/lists as JSON editors with live parse errors; per-field chips
for `research gate` (guarded) and `edit → <recompute job>`; dirty fields
highlighted with per-field reset. Save requires nothing but writes a **note**
alongside the new version; the response surfaces guarded-change and
recompute warnings. **Preview today under draft** (Marcus tab) diffs the
classification before you commit. History table with one-click
**activate** (rollback-as-new-version).

### Jobs & Health (`pages/JobsPage.tsx`)
Health chips (registry, both DBs, running job, all six param hashes) →
one-click job launchers (disabled while anything runs — single-writer) →
recent runs with status, param-hash provenance, and expandable log tails.
Polls every 3s.

## Implementation notes

- **Charts**: pages fetch server-built Plotly `{data, layout}` JSON
  (`components/PlotlyFig.tsx`); chart logic stays in Python.
- **API client**: `src/api.ts` — thin fetch wrappers that surface FastAPI
  `detail` strings into the red error boxes.
- **No state library**: local `useState` + polling; adequate at this scale.
- Build: `npm run build` (tsc + vite) → static bundle; `npm run preview`
  serves it on :4173 (CORS-allowed).
