---
domain: trading-system
stage: wiki
project: v1-workstation
status: active
---

# Workflow — Creating a Theme

*This page is written **to the assistant** (and the human who reviews its
work). A theme is a palette of CSS custom properties that re-skins the
whole React workstation. Every color, font stack, and font size in the
app flows through 32 named tokens — no component, page, or chart config
contains a raw color or font value. So a theme is **a single block of CSS
plus a one-line registration**, and the design work is choosing values
that satisfy the constraints below.*

Themes ship in pairs: **dark** (default, the original `#1a1a2e` look) and
**light**. You can add as many as you like.

## 1. Where a theme lives

| Piece | File | Role |
|---|---|---|
| Theme blocks (the palette) | `frontend/src/theme.css` top | one `:root[data-theme="<id>"] { … }` per theme |
| Registration (the menu) | `frontend/src/theme.ts` | `THEMES` array → dropdown entry; `DEFAULT_THEME` → startup theme |
| Active theme attribute | `<html data-theme="…">` | set by `initTheme()` before first paint; persisted in `localStorage["ui-theme"]` |
| Chart plumbing | `frontend/src/theme.ts` (`usePlotTheme`, `cssVar`) | Plotly needs concrete hex; reads the active theme's computed values |
| Backend-rendered charts | `PlotlyFig.tsx` overlay | server figures get bg/text/grid overlaid from the active theme; **trace colors stay as Python baked them** (see §4.6) |

## 2. The design spec — token inventory

**Every theme must define every token below.** A missing token silently
inherits the `:root` block (the dark palette), producing a broken hybrid
— this is the most common LLM error. **Color tokens** must be **plain
colors** (hex / `rgb()` / `hsl()`): no `var()` references, no
`color-mix()`, no gradients — `cssVar()` passes the computed value
straight to Plotly, and theme.css itself runs `color-mix()` over several
tokens. **Font tokens** are plain stacks
(`--font-sans`/`--font-body`/`--font-mono`) and plain px values
(`--fs-*`); a `--fs-*` token defined with `em`/`rem` would break the
scale's proportionality.

| Token | Dark (reference) | Light (reference) | What it paints |
|---|---|---|---|
| `--bg` | `#12121f` | `#eef0f6` | page background; **input/select/textarea backgrounds**; behind everything |
| `--panel` | `#1a1a2e` | `#ffffff` | cards, sidenav; **Plotly paper & plot background** (every chart) |
| `--panel-2` | `#22223a` | `#e7eaf2` | hover fills (nav links, table rows), chips, inactive tabs, scorebar tracks, selected rows |
| `--border` | `#2e2e4a` | `#d3d7e4` | card/input borders, table row separators; **chart gridlines & zero lines** |
| `--text` | `#e0e0e0` | `#1b1d2a` | primary text; **Plotly axis/font color** |
| `--muted` | `#9a9ab0` | `#5c6074` | secondary text at **11–12.5px** (section labels, table headers, chip labels, hints); Plotly tick labels |
| `--accent` | `#33b5e5` | `#0e77a8` | links, active nav/tab, primary button background, chart trace accents |
| `--on-accent` | `#06202c` | `#ffffff` | **text on primary buttons** (must contrast with `--accent`) |
| `--green` | `#00c851` | `#007a33` | positive/ok: ok chips, `ok-box`, positive scorebars, P&L ≥ 0 |
| `--amber` | `#ffbb33` | `#a06a00` | caution: warn chips, dirty-field labels, `notice-box`, transition probability |
| `--orange` | `#ff8800` | `#b85e00` | fragility `FRAGILE` (CommandDeck); severity between amber and red |
| `--red` | `#ff4444` | `#c62828` | bad/failure: bad chips, error boxes, danger buttons, negative values, `BREAKING` |
| `--deep-red` | `#cc0000` | `#9b0000` | **reserved** for crisis-level emphasis (defined but not yet consumed) |
| `--regime-risk-on-low-vol` | `#00c851` | `#007a33` | regime chips/tables (`RISK_ON_LOW_VOL`) |
| `--regime-risk-on-elevated-vol` | `#ffbb33` | `#9a6700` | (`RISK_ON_ELEVATED_VOL`) |
| `--regime-neutral` | `#33b5e5` | `#0e77a8` | (`NEUTRAL`) |
| `--regime-caution` | `#ff8800` | `#b85e00` | (`CAUTION`) |
| `--regime-risk-off-stress` | `#ff4444` | `#c62828` | (`RISK_OFF_STRESS`) |
| `--regime-crisis` | `#cc0000` | `#9b0000` | (`CRISIS`) |
| `--font-sans` | `-apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif` | same as dark | UI text everywhere (body rule; forms inherit) |
| `--font-mono` | `ui-monospace, SFMono-Regular, Menlo, monospace` | same as dark | data-shaped text: `.mono`, JSON editors, IDs, timestamps, job logs |
| `--font-body` | `-apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif` | same as dark | reading text + form fields: `input/textarea/select`, `p`, `.field .label/.help`, status boxes, `.loading` — the font-pack play role (§7) |
| `--fs-105` | `10.5px` | `10.5px` | micro labels (RCS intake footer) — the floor; nothing smaller |
| `--fs-11` | `11px` | `11px` | sidenav section labels, inline notes, alert/log text |
| `--fs-115` | `11.5px` | `11.5px` | chips, table headers, field help text, error/notice/ok boxes |
| `--fs-12` | `12px` | `12px` | `.mono` text, JSON editor, muted notes, job descriptions |
| `--fs-125` | `12.5px` | `12.5px` | tab buttons, field labels, scorebar names |
| `--fs-13` | `13px` | `13px` | tables, inputs/selects, card headings, GO/NO_GO chips |
| `--fs-14` | `14px` | `14px` | **body base** — the anchor of the scale |
| `--fs-15` | `15px` | `15px` | sidenav app title |
| `--fs-18` | `18px` | `18px` | page headings (`.main h2`), banner score |
| `--fs-24` | `24px` | `24px` | regime banner label |

Consumers beyond the list above: `--green/--amber/--red` also drive the
`color-mix()` translucent fills of `ok-box` / `notice-box` / `error-box`
and the chip text+border combos (`chip.ok`, `chip.warn`, `chip.bad`), so
each status color must read well **as text and as a border on `--panel`
and `--bg`**.

## 3. Design guidance — the rules that make a palette usable

These are the constraints a palette must satisfy (target **WCAG 2.1 AA**;
the app is a dense data terminal, so err toward higher contrast):

1. **Surface layering.** `--panel-2` sits *on* `--panel` (hover/chips) and
   `--panel` sits *on* `--bg` (cards/inputs). Each must be visibly lighter
   (dark themes) or visibly darker (light themes) than the surface under
   it, and `--border` must be distinguishable from both adjacent surfaces.
2. **Body text.** `--text` on `--bg` and on `--panel`: contrast **≥ 4.5:1**.
3. **Muted text.** `--muted` is used at 11–12.5px, so it too must hold
   **≥ 4.5:1** on both surfaces — a common mistake is making "muted" too
   faint.
4. **Accent.** `--accent` is used as text (links, active nav, active tab),
   as a fill (primary buttons, bar charts) and as an outline. It must hold
   **≥ 4.5:1 as text** on `--bg`/`--panel` and **≥ 3:1 against its own
   `--on-accent` fill** (i.e. choose `--on-accent` = near-white for dark
   accents, near-black for bright accents).
5. **Status hierarchy.** `--green < --amber < --orange < --red` is a
   severity ramp — values must stay in that order perceptually (same hue
   family is fine; the ramp must be obvious). Keep status colors
   distinguishable from `--accent` so "actionable" is never confused with
   "good".
6. **Regime colors.** Six regimes on a risk spectrum (low-vol risk-on →
   crisis). They appear as **text and borders on `--panel`/`--bg`** (chips,
   table cells, banners). Requirements:
   - hold **≥ 3:1** on both surfaces (4.5:1 for the risk-on end, which
     reads as text most often);
   - be **mutually distinguishable** — an LLM's safest move is to derive
     them from the same hue ramp as the status colors, darkened/lightened
     for the active background;
   - the first and last regime may equal `--green` and `--red` values
     (they are the same semantic endpoints), but the middle four must
     differ from each other.
7. **Charts inherit panel + text.** Plotly figures use `--panel` as the
   chart background and `--text`/`--muted`/`--border` for fonts and
   gridlines. **Trace colors are baked server-side (dark palette)** — see
   §4.6. A theme whose `--panel`/`--text` pair is sane will look sane on
   every chart; trace-color restyling is a separate backend task.
8. **Typography.** The type scale is a token ramp (`--fs-105` → `--fs-24`,
   anchored at `--fs-14` for body text). Keep the ramp **proportional**:
   a theme that enlarges body text should scale the whole ramp up; never
   go below `--fs-105`. Use `--font-mono` for anything data-shaped (IDs,
   timestamps, JSON, log tails, table numbers) and `--font-sans`
   everywhere else. The app currently loads **no webfonts** — if a theme
   wants a custom family, self-host it (`@font-face` in `theme.css`);
   system stacks keep the app offline-friendly and fast. Three font
   roles — chrome (`--font-sans`), reading/forms (`--font-body`), data
   (`--font-mono`) — and the swap conventions are specified in §7.

## 4. Implementation — exact steps

### 4.1 Add the theme block (`frontend/src/theme.css`)

Copy the most similar existing block (dark → copy the dark block; light →
copy the light block) and retitle it:

```css
:root[data-theme="terminal"] {
  --bg: #0a0f0a;
  --panel: #101810;
  --panel-2: #1c2c1c;
  --border: #2a3a2a;
  --text: #c8f7c8;
  --muted: #7fae7f;
  --accent: #4ade80;
  --on-accent: #041404;
  --green: #22c55e;
  --amber: #eab308;
  --orange: #f97316;
  --red: #ef4444;
  --deep-red: #dc2626;
  --regime-risk-on-low-vol: #22c55e;
  --regime-risk-on-elevated-vol: #eab308;
  --regime-neutral: #4ade80;
  --regime-caution: #f97316;
  --regime-risk-off-stress: #ef4444;
  --regime-crisis: #dc2626;
  /* type — the default stacks/scale; change per theme as needed */
  --font-sans: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
  --font-body: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
  --fs-105: 10.5px; --fs-11: 11px; --fs-115: 11.5px; --fs-12: 12px;
  --fs-125: 12.5px; --fs-13: 13px; --fs-14: 14px; --fs-15: 15px;
  --fs-18: 18px; --fs-24: 24px;
}
```

(Values above are a worked example — the full "terminal" theme is verified
in §6. Replace `terminal` with your theme id: **lowercase, hyphenated,
≤ 32 chars, unique**.)

### 4.2 Register it (`frontend/src/theme.ts`)

Add an entry to `THEMES` — order = dropdown order:

```ts
export const THEMES = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" },
  { id: "terminal", label: "Terminal" },
] as const;
```

To make your theme the startup default instead of dark, change
`DEFAULT_THEME`. (Users who already have a saved theme keep theirs —
`localStorage["ui-theme"]` wins.)

### 4.3 Build

```bash
cd frontend && npm run build        # tsc -b && vite build — must be clean
```

### 4.4 Verify no raw colors leaked into components

```bash
grep -rn "#[0-9a-fA-F]\{3,8\}\|rgba(" frontend/src --include="*.tsx" --include="*.ts"
```

Must print **nothing** (all hex/rgba lives in `theme.css` theme blocks).
If a component needs a concrete color at runtime (Plotly), use
`cssVar("--token")` or `usePlotTheme()` from `src/theme.ts` — never a hex.

### 4.5 Verify in the browser (Playwright)

With the dev stack up (API :8100, frontend :5173 — see
[running-and-operating.md](running-and-operating.md)), run this and assert
every line:

```js
import { chromium } from "../frontend/node_modules/playwright/index.mjs";
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1600, height: 1100 } });
await page.goto("http://localhost:5173/", { waitUntil: "networkidle" }).catch(() => {});
await page.waitForSelector(".sidenav select");
await page.selectOption(".sidenav select", "terminal");
await page.waitForTimeout(800);
console.log(await page.evaluate(() => {
  const cs = getComputedStyle(document.body);
  const card = document.querySelector(".card");
  const chip = document.querySelector(".chip");
  return {
    theme: document.documentElement.dataset.theme,      // "terminal"
    bodyBg: cs.backgroundColor,                          // = your --bg
    bodyText: cs.color,                                  // = your --text
    cardBg: card && getComputedStyle(card).backgroundColor,   // = --panel
    chipColor: chip && getComputedStyle(chip).color,          // = --muted
    stored: localStorage.getItem("ui-theme"),            // "terminal"
  };
}));
// Then: reload → theme must persist; visit /marcus and assert a
// .js-plotly-plot exists and its _fullLayout.paper_bgcolor = your --panel.
await browser.close();
```

### 4.6 Trace colors (the one thing themes don't reach)

Server-built figures (Marcus series, Sarah heatmaps, …) carry trace colors
baked by Python (`systems/dashboard/macro_dashboard.py`, `#33b5e5` lines
etc.). The client overlays background/font/grid only. If your theme needs
different **series** colors, the task is backend: thread a theme selector
through the chart endpoints (`?theme=`) and swap a Python palette — out of
scope for a CSS theme; note it in the PR and leave traces as-is.

## 5. Acceptance checklist (run before calling a theme done)

- [ ] All 32 tokens defined (13 color + 6 regime + 3 font stacks + 10
      type scale); no `var()`/`color-mix()` inside token values
- [ ] `--text` ≥ 4.5:1 on `--bg` and `--panel`; `--muted` ≥ 4.5:1 on both
- [ ] `--accent` ≥ 4.5:1 as text; ≥ 3:1 vs `--on-accent` fill
- [ ] Status ramp green < amber < orange < red perceptually ordered
- [ ] Regime colors mutually distinguishable, ≥ 3:1 on `--panel`/`--bg`
- [ ] `--panel-2` vs `--panel` vs `--bg` and `--border` all distinguishable
- [ ] Type ramp proportional, anchored at `--fs-14`; nothing below `--fs-105`
- [ ] `npm run build` clean; §4.4 grep clean
- [ ] Quantitative §3/§5 checks pass — run
      `python3 .agents/skills/trading-theme-design/scripts/verify_theme.py <id>`
      (computes WCAG ratios from the values as shipped in `theme.css`; exit 0
      = every contrast/ordering/distinguishability rule passes). This covers
      all the numeric bars above; it does **not** replace the two checks below.
- [ ] Playwright §4.5 passes incl. reload persistence + chart paper color
- [ ] Screenshot the Command Deck in the new theme (dark + any page with a
      chart) and eyeball it — contrast checks are necessary, not sufficient

## 6. Worked example — "terminal" (verified 2026-08-03)

Shipped in the app — the block from §4.1 plus this registration:

```ts
// theme.ts
export const THEMES = [
  { id: "dark", label: "Dark" },
  { id: "light", label: "Light" },
  { id: "terminal", label: "Terminal" },
  { id: "spring", label: "Spring" },
  { id: "spring-shade", label: "Spring Shade" },
] as const;
```

```css
/* theme.css — :root[data-theme="terminal"] { … }  (block in §4.1) */
```

Design notes: phosphor-green `--text` on near-black green-tinted surfaces;
`--accent` is the brightest green (links/buttons pop, `--on-accent` is
near-black at 10.9:1); the status ramp is the amber→red warm side;
regime colors reuse the ramp per §3.6 (risk-on = `--green`, crisis =
`--deep-red`). Typography keeps the default stacks and scale. Result:
chips, tables, banners, and all charts (paper `--panel`, text `--text`)
follow the theme; series traces remain the server's dark-palette blues,
which read acceptably on `#101810`.

The `spring` / `spring-shade` themes (also shipped) are a richer reference:
a poetic brief decoded into a two-system palette (warm-earth chrome + cool
counterweight) with a font-pack rationale — see
`docs/plans/spring-watercolour-theme-proposal.md`. To swap typefaces on any
theme (chrome/reading/data stacks), continue to §7.

## 7. Font packs — swapping typefaces without breaking the UI

A **font pack** is a named set of values for the three stack tokens
(`--font-sans`, `--font-body`, `--font-mono`), optionally plus a
proportional adjustment of the `--fs-*` scale. A pack is **not a new
theme** — it layers onto any theme block. Guarantee: any pack that
follows the contract in §7.2 changes *look*, not *function*.

### 7.1 The three font roles

| Role | Token | Consumers | Utility it protects |
|---|---|---|---|
| Chrome | `--font-sans` | body default; sidenav, nav links, `h1`–`h3`, chips, tabs, buttons, table headers | density and scanability; uppercase micro-labels carry 0.4–1px letter-spacing tuned for sans |
| Reading + forms | `--font-body` | `input/textarea/select`, `p`, `.field .label/.help`, `.notice/.error/.ok-box`, `.loading` | prose legibility and form consistency — **the serif/sans play area** |
| Data | `--font-mono` | `.mono`, `textarea.json` — IDs, hashes, ULIDs, timestamps, dates, JSON/YAML, log tails, param hashes | char-count truncations (`slice(0, 34)`), copy/paste integrity, 0/O/1/l distinction |

### 7.2 The utility contract

A pack may change any of the three stacks, subject to these rules — the
"utility of a field is not compromised by a font choice" guarantee:

1. **Data stays mono.** Never give data-shaped text a proportional face.
   `.mono`/`textarea.json` are the only data consumers, and components
   truncate IDs by character count on the assumption of mono advance
   widths. (Two existing exceptions wrap human-reading prose in `.mono` —
   GreeksLab interpretation, the Placeholder path — acceptable, but keep
   new data-shaped text mono.)
2. **Numbers stay tabular.** `table.data` cells and `.scorebar .val`
   (fixed 48px column, right-aligned) rely on
   `font-variant-numeric: tabular-nums`. Swapping the *family* used for
   numbers is allowed only if the face ships tabular figures; otherwise
   numeric text stays on the default stack. Verify with the Marcus
   scorebars and regime-conditional returns table.
3. **Chrome stays sans by default.** Serif on chrome (nav, chips, tabs,
   buttons, table headers) is allowed only with letter-spacing reduced
   (the 0.4–1px tracking is tuned for sans) and the 208px sidenav / chip
   / tab padding re-verified for wraps. Chrome elements nested inside a
   reading container (e.g., status chips inside field labels) inherit
   the container's role font — intentional, so a serif form carries its
   own chips in serif.
4. **Forms + prose are the play area.** Serif goes in `--font-body` —
   form fields, paragraphs, labels/help, status boxes. Sizes stay on the
   `--fs-*` ramp: serif x-heights read ~5–10% smaller, so scale the whole
   ramp proportionally (§3.8), never a single token. `textarea.json`
   stays mono regardless.
5. **Charts follow the pack.** `usePlotTheme()` sets
   `font.family: var(--font-sans)` and `PlotlyFig` overlays it on
   server-built figures — chart text is label-like, so it follows
   chrome, not body.
6. **Every stack ends in a system fallback** (`serif`/`sans-serif`/
   `monospace`) so packs degrade gracefully offline and on missing faces.

### 7.3 Swapping in a pack

1. Self-host custom faces once with `@font-face` at the top of
   `theme.css`, above the theme blocks (system faces need nothing).
2. Change up to three tokens in the target theme block:
   `--font-sans`, `--font-body`, `--font-mono`.
3. Optionally scale the `--fs-*` ramp proportionally (rule 4).
4. Run the §7.5 checklist.

### 7.4 Serif playbook

- **Works well:** prose, notes and status boxes, form fields, long-form
  outputs (weekly review, interpretation cards).
- **Avoids:** micro-labels (chips and table headers at 11.5px), dense
  tables, and all mono data.
- Uppercase + letter-spacing + serif reads as clutter — keep chrome sans
  or drop the tracking when serif must appear there.
- If serif in form fields feels wrong, a humanist-sans body (serif
  prose, sans UI) is a valid middle pack.

### 7.5 Font-pack verification checklist

- [ ] `npm run build` clean; no raw font literals outside theme blocks
- [ ] Data audit: `.mono` sites still data-shaped; truncations still char-count-safe
- [ ] Numeric audit: Marcus scorebars + returns table — right edges align, 48px `.val` column unclipped
- [ ] No wraps: sidenav at 208px, chips, tabs
- [ ] Charts: `_fullLayout.font.family` = the chrome stack (Playwright)
- [ ] Forms show the pack; `textarea.json` still mono
- [ ] Screenshot Command Deck + a form-heavy page (Parameters) and eyeball

### 7.6 Worked example — a "serif reading" pack

A pack is a token diff against any existing theme, not a new theme block:

```css
/* in the target theme's block — the pack swap is one line */
--font-sans: -apple-system, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
--font-body: Georgia, "Times New Roman", serif;   /* ← the pack swap */
--font-mono: ui-monospace, SFMono-Regular, Menlo, monospace;
```

Georgia is a system serif, so no `@font-face` is needed. For a
less-default look, self-host a face (Charter, Bookerly, …) and point
`--font-body` at it. Chrome and data stay exactly as they are; every
paragraph, form field, label, and status box re-sets in serif — and
nothing moves, because the contract holds.

## Where this fits

**This doc is the *contract* a theme must satisfy (the §3 rules + §5 checks).
It is deliberately silent on *how to choose good colors* — that is design
knowledge, sourced separately. Read both:**

- **Design knowledge — the *why* behind palette choices.** The design
  synthesis at `~/Nextcloud/claude/D-design-knowledge/synthesis/design-synthesis.md`
  (and the four distillations it synthesizes: Albers *Interaction of Color*,
  Maeda *Laws of Simplicity*, Brockmann *Grid Systems*, Refactoring UI). Load
  these before designing a palette from a brief — they carry the principles
  (Albers quantity/subtraction, Maeda reduce-organize, the two-system split
  between chrome and semantic colors) that the §3 contract alone does not
  teach. No standalone typography distillation exists; type guidance is in
  the synthesis (Rules T1–T4, §3.4, Conflict 2) + Refactoring UI §2.21–2.28.
- **Efficient pipeline + the §5 verifier.** The `trading-theme-design` skill
  (`.agents/skills/trading-theme-design/SKILL.md`) encodes the end-to-end
  workflow — decoding a brief, generating the palette *under* the §3 contract
  as a generative constraint, running the verifier on candidates *before*
  committing, then implementing per §4. It exists because treating synthesis
  and §3 as two separate phases (design, then discover failures) wastes a
  pass; the skill makes §5 a confirmation gate, not a discovery gate. The
  verifier script is the §5 checklist item above.
- **Worked examples beyond `terminal`.** Proposal/evaluation docs live in
  `docs/plans/` — e.g. `docs/plans/spring-watercolour-theme-proposal.md`
  (a poetic brief → two-system decode → full palette + font pack, with the
  equinox warm/cool reasoning). These are richer reference examples than the
  compact `terminal` block in §6.

**Architecture references:**

- Frontend architecture: [02-platform/frontend.md](../02-platform/frontend.md) → "Themes"
- The component CSS that consumes these tokens: `frontend/src/theme.css`
  (below the theme blocks — never edit component CSS per theme; if a new
  token is genuinely needed, add it to **every** theme block and update
  the table in §2)
