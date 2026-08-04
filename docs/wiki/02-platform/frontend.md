---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# Frontend — the React Workstation

**Status:** ✅ all pages live (browser-verified 2026-07-17/18) · **Code:** `frontend/`
**Stack:** Vite + React 18 + TypeScript · react-plotly.js over `plotly.js-dist-min` · react-router
**Dev:** `npm run dev` → http://localhost:5173 (proxies `/api` + `/health` to :8100)

Themable dark app (default palette matches the legacy Dash look,
`#1a1a2e` panels; light theme ships alongside) with a left nav:
Command Deck · Marcus · Sarah · Priya · Jordan ·
Parameters · Jobs & Health. Screenshots of every page live in
`docs/wiki/images/` (regenerate: `node scripts/capture_wiki_screenshots.mjs`).

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

### Sarah (`pages/SarahPage.tsx` + `pages/sarah/*`)
Four tabs (the five tools):
1. **Vol monitor** (`VolMonitor.tsx`) — signals table + IV-vs-RV, term
   structure, IV-surface heatmap, realized-vol cone.
2. **Greeks & scenarios** (`GreeksLab.tsx`) — greeks form → interpretation
   → P&L heatmap with DTE-checkpoint tabs, stress table (editable registry
   library), kill-scenario card.
3. **Pre-trade memo** (`MemoBuilder.tsx`) — thesis form with catalyst
   auto-resolve → five panels + BL density chart + structure comparison →
   persisted history (click a `PTM-…` row to re-render a stored memo).
4. **Regime library** (`RegimeLibrary.tsx`) — VVIX monitor + VVIX/VIX
   chart, analog search with macro filters, event browser + validated YAML
   editor.

### Priya (`pages/PriyaPage.tsx`)
Hypothesis registration + registry table (live trial counts) → data-audit
runner → backtest configurator (sweep toggle) → results: verdict banner,
gate chips, DSR/PBO/haircut table, CPCV path chart, regime-conditional
table, sweep table, collapsible warnings → current Jordan contract → gates
card → run archive with GO/failure-archive filter.

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
**alerts feed with ack** → **scheduler v2 card** (entries + retry policy,
live from OpsParams) → **weekly-review archive** (click to read) →
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

## Themes

Every color in the app flows through CSS custom properties — components
never contain hex values. To re-skin the app you only edit theme blocks;
no component CSS changes.

- **Theme blocks** live at the top of `src/theme.css`, keyed by a
  `data-theme` attribute on `<html>`: `:root, :root[data-theme="dark"]`
  and `:root[data-theme="light"]`. Tokens: surfaces (`--bg`, `--panel`,
  `--panel-2`, `--border`), text (`--text`, `--muted`, `--on-accent`),
  accent, semantic status (`--green/--amber/--orange/--red/--deep-red`),
  and regime data colors (`--regime-*`).
- **Switcher**: theme dropdown in the sidenav footer (pinned via
  `.theme-select`); choice persists in `localStorage["ui-theme"]`.
  `initTheme()` in `main.tsx` applies it before first paint (no flash).
  Logic lives in `src/theme.ts` (`useTheme`, `setTheme`, `cssVar`).
- **Regime colors** (`REGIME_COLORS` / `regimeColor()` in `src/api.ts`)
  are `var(--regime-*)` strings, so regime chips/tables follow the theme.
- **Typography is tokenized too**: font stacks (`--font-sans`,
  `--font-mono`) and the size scale (`--fs-105`…`--fs-24`, anchored at
  `--fs-14`) live in each theme block; every `font-size` in the app —
  including ~85 inline component overrides — resolves to a `--fs-*`
  token. A third stack, `--font-body`, drives reading text + form
  fields (the font-pack "play" role — swap it for a serif without
  touching anything else); charts set `font.family` from `--font-sans`
  via `usePlotTheme()`. No webfonts are loaded; self-host `@font-face`
  if a theme needs a custom family. Conventions + utility contract:
  [04-workflows/creating-a-theme.md](../04-workflows/creating-a-theme.md) §7.
- **Plotly figures** are built server-side with the dark palette baked in;
  `usePlotTheme()` in `src/theme.ts` re-reads the active theme's computed
  values (bg, text, grid, accent) and `PlotlyFig.tsx` overlays them on the
  fetched figure. Locally-built charts (Priya CPCV bar, Sarah density bar)
  use the same hook directly.
- **Adding a theme**: copy a block in `theme.css` as
  `:root[data-theme="<id>"]` with your palette, and register the id+label
  in `THEMES` in `src/theme.ts`. The dropdown and persistence pick it up
  automatically. Full spec — token inventory, contrast rules, verification
  checklist, and a shipped worked example ("terminal") — lives in
  [04-workflows/creating-a-theme.md](../04-workflows/creating-a-theme.md).
