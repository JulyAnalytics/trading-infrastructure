---
domain: trading-system
stage: plan
project: v1-workstation
status: proposal
---

# Design Proposal — "Spring Watercolour" theme

*A new visual theme **+ font pack** for the trading workstation, grounded in the
design synthesis (Albers · Maeda · Brockmann · Refactoring UI) and built against
the [`creating-a-theme.md`](../wiki/04-workflows/creating-a-theme.md) contract
(color §2–§6, fonts §7). Palette values below are **proposals for evaluation** —
contrast is reasoned analytically against the §5 acceptance checklist; final
verification happens via the doc's Playwright §4.5 step at implementation time.*

> **Revision 2 (2026-08-03).** Two additions: (1) the palette leans **cooler**
> — spring is the *transitionary balance between hot and cold*, so the warm
> earth notes are now balanced by a cool sky/sage counterweight rather than
> reading as purely warm; (2) a **font system** (§4) is proposed alongside the
> color system, satisfying the brief's "a little bit of whimsy, not purely
> utilitarian, elegant and efficient." The font system follows the doc's §7
> font-pack contract (three roles, chrome-stays-sans, data-stays-mono).

---

## 1. The brief

> *Sitting under a tree watching spring bloom while doing watercolours. Pastels,
> flowery notes, earthiness, anchored by the consistent dark green of lush
> rolling hills; cinnamon sticks, sweet citrus.*

### Image-to-design decoding

Spring is the **transitionary balance between hot and cold** — the brief is not
a purely warm palette; it is the *equinox*. The translations below carry the
brief from mood to concrete tokens, with the warm and cool notes held in
tension:

| Brief image | Design translation | Role | Temperature |
|---|---|---|---|
| **Watercolour paper / pastels** | The dominant *background surface* — cream paper, not screen-grey. | Albers' **quantity principle**: the spring character owns the 80–90% of the screen that is background, so small semantic marks (chips, status) stay saturated and still read as calm. | Warm-neutral (cream) |
| **Dark green of lush rolling hills** | The *earth anchor*. | In **light** this is an accent/earth border and the green status endpoint; in **dark** it becomes the near-black green-black background — "under the tree, in the shade." | Cool-warm balance (green sits at the fulcrum of the spectrum — which is *why* it anchors a spring palette) |
| **Cinnamon sticks + sweet citrus** | The *warm secondary palette*. | Cinnamon = warm-earth amber/caution family; sweet citrus = the warm golden-amber of the status ramp and the terracotta of caution→red. | Warm |
| **Cool spring sky / distant rain** *(added — the cool counterweight)* | The *cool counterweight* without which the warm notes read as autumn, not spring. | The **accent** shifts cooler (periwinkle/sky lilac), and `--regime-neutral` is a cool slate-blue. Frost-morning surfaces in the dark companion. | Cool |
| **Flowery notes** | A single muted *lilac/lavender accent*. | Links, active nav, primary action — one disciplined accent (Refactoring UI §2.5: choose a personality, stay consistent). The lilac carries both the floral image *and* the cool counterweight. | Cool |

**The equinox principle.** Pure warm earth = autumn. Pure cool sky = winter.
Spring is the two in balance: warm paper and cinnamon *held against* a cool sky
accent and frost dark-mode. Per Albers' relativity thesis (Ch. IV), the warm
background *makes* the cool accent read cooler and more vivid than it would on a
neutral ground — so the cool notes punch above their quantity, which is exactly
the lively, "blooming" quality the brief asks for. The palette below is tuned so
neither side dominates.

---

## 2. The central design problem, and how the sources resolve it

**The problem.** A "pastel watercolour" terminal is in direct tension with the
[`creating-a-theme.md`](../wiki/04-workflows/creating-a-theme.md) §3 contract:
≥4.5:1 body text, a perceptually-ordered green→red status ramp, and six
mutually-distinguishable regime colors. Naive pastels produce **vanishing
boundaries** (Albers, *Interaction of Color*, Ch. XXIII) — pastel text on
pastel paper — and wash out the status ramp (Weber-Fechner: lightness
compression at the pale end).

**The resolution, by source:**

1. **Albers — quantity over harmony (Ch. XVI).** Keep the pastels *dominant by
   area* (backgrounds, borders, surfaces) but keep **text and semantic colors
   dark/saturated**. Any color works with any other if quantities are right;
   here the spring palette owns area, the semantic palette owns marks. This is
   why the brief and the contract are *not* in conflict — they operate on
   different layers.
2. **Albers — context / subtraction (Ch. VII).** Every semantic color must be
   **hand-tuned to the cream/green surfaces**, not lifted from the existing dark
   theme. The cream `--bg` subtracts warmth, so greens shift cooler and ambers
   shift darker than they'd need to be on pure white. Dark mode is *not* a
   palette inversion (synthesis Rule D3).
3. **Maeda — Law 9 (failure / irreducible complexity).** The status ramp and
   regime colors are *irreducible* — they carry the system's meaning. Do not
   "soften" them pastel. A spring theme that renders `CRISIS` as a peach tone is
   a failure of the system's content. Restraint (Maeda Law 1) applies to the
   **chrome only**.
4. **Refactoring UI — flip contrast (synthesis Rule C3).** Status chips and
   boxes already read as **dark saturated marks on pale tinted fills** via the
   `color-mix()` translucent fills in `theme.css`. This is *exactly* the
   watercolour aesthetic (thin saturated strokes on pale washes) and it is what
   makes pastel backgrounds safe for data — the marks carry the contrast, the
   wash carries the mood.
5. **Brockmann — credibility through order.** A disciplined, narrow surface
   ladder (3 tints + 1 border, geometrically stepped) is what stops "pastel"
   reading as "decorative toy." The grid ethos carries the professionalism that
   a trading desk requires. Order is a trust signal (synthesis §1, Layout).

**One-line summary:** the spring lives in the chrome (Maeda reduces there);
the meaning lives in the marks (Albers tunes them to context); Brockmann's
discipline holds the two together.

---

## 3. The palette (19 tokens)

Token inventory matches the
[`creating-a-theme.md`](../wiki/04-workflows/creating-a-theme.md) §2 table
exactly — a theme is **one CSS block per variant + one `THEMES` registration
line each**. Every value is a plain color (hex), as required (no `var()` /
`color-mix()` inside token values — `cssVar()` passes these straight to Plotly).

### 3.1 Light — "Spring Watercolour" (the primary proposal)

| Token | Value | Role in the brief / design |
|---|---|---|
| `--bg` | `#f1ede1` | **Watercolour paper**, warm cream. Dominant area (~80%). The warm floor the cool accent plays against. |
| `--panel` | `#fbfaf4` | Card / sidenav — paper-white lifted above the cream page. |
| `--panel-2` | `#e9e3d2` | Hover / chips / tracks — a third warm tint, between bg and paper. |
| `--border` | `#ccc0a8` | **Cinnamon earth** border; warm, distinguishable from all three surfaces. |
| `--text` | `#332a20` | Deep walnut ink — warm near-black. |
| `--muted` | `#6f6453` | Earth taupe; dark enough to hold contrast at 11px (the §3.3 trap). |
| `--accent` | `#5b7caa` | **Cool spring-sky / lilac accent** — the cool counterweight. Shifted cooler from the earlier violet toward a slate-periwinkle, so it reads as *frosty morning* against the warm paper. Single disciplined accent. |
| `--on-accent` | `#fbfaf4` | Paper-white on the sky accent. |
| `--green` | `#2e7d3a` | **Lush rolling hills**, darkened to read as text on cream. The warm-cool fulcrum. |
| `--amber` | `#a87100` | **Cinnamon** caution. |
| `--orange` | `#bd5a1e` | Warm terracotta — earthy severity step. |
| `--red` | `#c0392b` | **Sweet citrus → warm red**; saturated, not pastel. |
| `--deep-red` | `#9b2d20` | Crisis emphasis (reserved). |
| `--regime-risk-on-low-vol` | `#2e7d3a` | = `--green` endpoint (§3.6 permits endpoints to coincide). |
| `--regime-risk-on-elevated-vol` | `#b07d10` | Cinnamon-gold, distinct from `--amber`. |
| `--regime-neutral` | `#5a7a9a` | **Cool slate-blue** — the cool regime step, maximally distinct from the green and red families. Reinforces the equinox balance. |
| `--regime-caution` | `#bd5a1e` | = `--orange`. |
| `--regime-risk-off-stress` | `#c0392b` | = `--red`. |
| `--regime-crisis` | `#9b2d20` | = `--deep-red`. |

**Status ramp perceptual order:** green `#2e7d3a` → amber `#a87100` → orange
`#bd5a1e` → red `#c0392b` → deep-red `#9b2d20`. Held in the warm-earth family;
monotonic in perceived severity; every member dark enough to read as text and
border on cream. Per the synthesis Rule C4, chips still pair color + text label,
so the ramp is never color-only (accessibility + Albers' "poor visual memory").

### 3.2 Dark — "Spring Shade" (the under-the-tree companion)

A theme this soft benefits from a paired dark variant for evening sessions;
themes ship in pairs per the doc. This is "under the tree, in the shade":

| Token | Value | Role |
|---|---|---|
| `--bg` | `#16241c` | **Deep lush-green near-black** — the shade under the tree. |
| `--panel` | `#1f3026` | Green-black raised card. |
| `--panel-2` | `#2c3328` | Olive-tinted hover (subtle warmth, not flat grey). |
| `--border` | `#3a4536` | Sage-olive border. |
| `--text` | `#ece9df` | Warm cream text on green-black. |
| `--muted` | `#9aa896` | Sage muted. |
| `--accent` | `#8fb4d8` | Cool sky-periwinkle, brightened for the dark green ground (Albers subtraction — a dark background subtracts darkness, so the cool accent must lighten to hold its frosty read). |
| `--on-accent` | `#1a1320` | Near-black grape on the lavender. |
| `--green` | `#5fbf6a` | Hills green, lightened for dark ground. |
| `--amber` | `#e0a83a` | Cinnamon gold. |
| `--orange` | `#e07b3a` | Terracotta. |
| `--red` | `#e85d52` | Warm coral-red. |
| `--deep-red` | `#c9423a` | Crisis. |
| `--regime-risk-on-low-vol` | `#5fbf6a` | = `--green`. |
| `--regime-risk-on-elevated-vol` | `#d9a233` | Cinnamon-gold. |
| `--regime-neutral` | `#7fa6c4` | Periwinkle (the cool outlier). |
| `--regime-caution` | `#e07b3a` | = `--orange`. |
| `--regime-risk-off-stress` | `#e85d52` | = `--red`. |
| `--regime-crisis` | `#c9423a` | = `--deep-red`. |

---

## 4. Font system — "a little bit of whimsy, not purely utilitarian"

### 4.1 What the design knowledge says about type here

There is **no standalone typography distillation** in the knowledge base —
Bringhurst (the primary typography authority) was marked *pending* in the
[synthesis](https://github.com/...) and never completed. Typography guidance is
therefore drawn from four places, and they converge on a clear mandate for this
theme:

- **Refactoring UI §2.22 (font selection)** — the operative heuristics: a
  *neutral sans-serif* with **≥5 weights** and a high x-height for UI chrome;
  "trust the wisdom of the crowd"; never go below weight 400 for UI text. The
  synthesis §3.4 solo-dev tradeoff distils it: *"Pick one good sans-serif
  (Inter, system fonts)."*
- **Synthesis Conflict 2 (type-scale derivation)** — resolves the one real
  tension: for **data-heavy UI, hand-crafted scales beat modular/classical
  scales** (Bringhurst loses to Refactoring UI here). Practical pixel-constraints
  override mathematical beauty. **Mandate: keep the existing `--fs-*` ramp; do
  not chase a "beautiful" modular scale.**
- **Brockmann (leading + column width + type size as one system)** — these three
  are interdependent and must be tuned together (synthesis T2). The existing
  ramp + the line-height rules in `theme.css` already honour this; a font pack
  must not break it.
- **Synthesis Rules T1–T4** — hand-crafted scale of 8–12 sizes (have it),
  line-height proportional to size *and* measure (have it), baseline alignment,
  links de-emphasised not coloured.

Sources: the design synthesis lives at
`~/Nextcloud/claude/D-design-knowledge/synthesis/design-synthesis.md` (Typography
§1, Rules T1–T4 §2, codebase-analysis §4, Conflict 2 §6); Refactoring UI
distillation `…/Distillations/refactoring-ui-distillation.md` §2.21–2.28, §3.4;
Brockmann distillation §2 (typographic grid, leading/column-width). There is no
dedicated typography distillation — Bringhurst was marked pending in the
synthesis and never completed, so the type guidance is the synthesis's
distributed treatment plus Refactoring UI as the primary practitioner source.

**The synthesis-level permission structure for whimsy:** both the synthesis
(§3.4) and the workflow doc §7.4 reserve **serif for the reading/forms "play
area"** (`--font-body`) while chrome stays neutral sans and data stays mono.
The whimsy lives in *one* role — the prose/forms role — not across the whole UI.
That is exactly the brief: "a little bit of whimsy," not "whimsical everywhere."

### 4.2 The three-role proposal (per workflow doc §7.1)

| Role | Token | Proposed family | Why this face |
|---|---|---|---|
| **Chrome** | `--font-sans` | **Inter** (self-hosted, variable, 4 weights: 400/500/600/700) | Synthesis §3.4's named default. Neutral, high x-height, ≥5 weights (Refactoring UI §2.22), tabular-figure variant available for numerics (satisfies §7.2 rule 2). The disciplined workhorse — keeps density, scanability, and the uppercase micro-label tracking intact. |
| **Reading + forms** | `--font-body` | **Newsreader** (self-hosted, variable, weights 400/500 + italic) | The "play area" face. Newsreader is an open-source serif **commissioned by Google Fonts specifically for on-screen long-form reading** — editorial, charming, readable, with a restrained whimsy in its italics. Elegant without being precious; efficient because it was engineered for screens. Carries form fields, status boxes, labels/help, interpretation cards, weekly review prose. |
| **Data** | `--font-mono` | **JetBrains Mono** (self-hosted, weights 400/500) | Replaces the system mono stack with a face designed for code/data: unambiguous `0/O/1/l`, true monospace advance widths (protects the char-count truncations §7.2 rule 1), ligatures off for data. A small, intentional upgrade that reads as "considered instrument" without changing any layout. |

**The whimsy budget, stated plainly:** one characterful serif (`--font-body`) +
one considered mono. Chrome stays Inter. That ratio — disciplined chrome,
expressive prose, precise data — *is* the brief's "elegant and efficient, with a
little whimsy." Putting a whimsical face in chrome would violate §7.2 rule 3 and
the synthesis's "chrome stays sans" mandate; putting it in data would violate
rule 1.

### 4.3 Why these three faces (and the alternatives considered)

- **Inter over the system stack / Satoshi / Albert Sans.** The system stack is
  the status quo and works, but a self-hosted Inter gives metric consistency
  across OSes (important for the tabular-numerics audit, §7.5) and the variable
  axis lets one file serve 4 weights. Satoshi/Albert Sans have more geometric
  "personality" but lean toward chrome display use; for a *data terminal*,
  Inter's neutrality is the feature — it lets the semantic colors and the serif
  body carry all the character (Albers quantity principle, applied to type).
- **Newsreader over Fraunces / Lora / Source Serif 4.** Fraunces is the
  maximal-whimsy option ("wonky", display-friendly) but its personality is
  *too* loud for form fields and status boxes read at 11–13px — it would fight
  the calm the palette establishes. Lora is elegant but generic. Source Serif 4
  is "workmanlike, quietly elegant" — safe but undistinctive; it doesn't earn
  the "whimsy" word in the brief. **Newsreader is the goldilocks choice**:
  engineered for screen reading (efficiency), editorial charm (elegance), and a
  touch of life in the italics (whimsy) — without ever being precious.
- **JetBrains Mono over keeping `ui-monospace` / IBM Plex Mono.** The system mono
  is fine but OS-variable; self-hosting removes that variability. JetBrains Mono
  was purpose-built for reading dense code/data on screen and has best-in-class
  glyph disambiguation — directly serving §7.2 rule 1's truncation-safety
  guarantee. IBM Plex Mono is a valid alternative (slightly warmer, pairs well
  with editorial serifs) if JetBrains feels too "code-editor."

### 4.4 Implementation — conforms to workflow doc §7.3

```css
/* top of theme.css — self-host once, above the theme blocks (§7.3 step 1) */
@font-face { /* Inter variable — woff2 at /frontend/public/fonts/ */ … }
@font-face { /* Newsreader variable — woff2 */ … }
@font-face { /* JetBrains Mono — woff2, 400 + 500 */ … }

:root[data-theme="spring"] {
  /* …19 color tokens from §3.1… */
  --font-sans: Inter, -apple-system, "Segoe UI", Roboto, sans-serif;       /* system fallback (§7.2 rule 6) */
  --font-body: Newsreader, Georgia, "Times New Roman", serif;              /* ← the pack swap */
  --font-mono: "JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, monospace;
  /* --fs-* ramp unchanged (synthesis Conflict 2: hand-crafted wins; don't modular-rescale) */
}
```

- **No `--fs-*` rescale on swap.** Synthesis Conflict 2 mandates hand-crafted
  scales for data UI; the existing ramp is already that. Newsreader's x-height
  reads ~5–8% smaller than Inter, so per §7.2 rule 4 the *proportional*
  adjustment is available if the serif reads too small in forms — but try the
  unscaled swap first and verify via §7.5 before adjusting.
- **Charts follow chrome** (§7.2 rule 5): `usePlotTheme()` already sets
  `font.family: var(--font-sans)`, so all Plotly text becomes Inter
  automatically — no chart changes.
- **The pack is a token diff, not a new theme** (§7.6): the same three
  `--font-*` lines could layer onto `spring-shade`, `dark`, or any future theme.

### 4.5 Font-pack verification — the §7.5 checklist (run at implementation)

- [ ] `npm run build` clean; no raw font literals outside `theme.css`
- [ ] Data audit: `.mono` sites (IDs, hashes, timestamps, `textarea.json`) still
      data-shaped; `slice(0, 34)` truncations still char-count-safe under
      JetBrains Mono
- [ ] Numeric audit: Marcus scorebars + regime-conditional returns table —
      right edges align, 48px `.val` column unclipped (Inter tabular-nums)
- [ ] No wraps: 208px sidenav, chips, tabs (Inter ≈ system metrics, so low risk)
- [ ] Charts: `_fullLayout.font.family` resolves to the Inter stack (Playwright)
- [ ] Forms show Newsreader; `textarea.json` stays JetBrains Mono
- [ ] Screenshot Command Deck (chrome-dense) **and** Parameters page
      (form-dense) and eyeball the serif/sans/mono balance

### 4.6 What this font system deliberately does **not** do

- **No whimsy in chrome.** Nav, chips, tabs, buttons, table headers stay Inter.
  Serif on chrome needs letter-spacing re-tuning and risks wraps (§7.2 rule 3);
  the calm-authority goal is served by neutrality there.
- **No modular/classical type scale.** Synthesis Conflict 2 is explicit: for
  data UI, hand-crafted beats Bringhurst-style proportional scales. The existing
  `--fs-*` ramp stays.
- **No proportional face in data.** `.mono` / `textarea.json` stay monospace
  (§7.2 rule 1) — non-negotiable for the char-count truncations.
- **No webfont CDN.** Self-hosted `@font-face` only (§7.3); keeps the app
  offline-friendly and fast per the doc's stated principle.

---

## 5. How it satisfies the §3 contract (reasoned analytically)

Final numeric verification is the §4.5 Playwright step at build time; the
ratios below are reasoned from relative luminance to show the palette is
feasible *before* implementation.

- **§3.1 Surface layering.**
  - *Light:* cream `#f1ede1` (page) < paper `#fbfaf4` (cards lighter than page —
    correct light-theme direction), with `--panel-2` `#e9e3d2` *between* them for
    hover, and cinnamon border `#ccc0a8` distinct from all three.
  - *Dark:* green-black `#16241c` < green panel `#1f3026` < olive hover
    `#2c3328`, sage border `#3a4536` distinguishable throughout.
- **§3.2 Body text.** `--text` `#332a20` (relative luminance ≈ 0.03) on `--bg`
  `#f1ede1` (≈ 0.83) ≈ **12:1**; on `--panel` ≈ 15:1. Comfortably ≥ 4.5:1.
- **§3.3 Muted text (the 11px trap).** `--muted` `#6f6453` (≈ 0.15) ≈ **5.3:1**
  on both surfaces — clears the 4.5:1 bar that "muted" so often fails.
- **§3.4 Accent.** Cool sky-periwinkle `#5b7caa` (≈ 0.20) ≈ **4.6:1** as text on
  cream and ≈ 4.8:1 on paper — clears the 4.5:1 bar; ≈ 4.6:1 vs paper-white
  `--on-accent`, clearing the 3:1 fill bar. Deliberately *not* green/amber/red,
  so "actionable" ≠ "good" (§3.5). *Note: this is the tightest token in the
  palette — if §4.5 verification shows it dipping under 4.5:1 on either surface,
  darken toward `#52719a` (≈ 0.16, ≈ 5.4:1) as the first response.*
- **§3.5 Status hierarchy.** green → amber → orange → red → deep-red, all
  warm-earth, perceptually monotonic; every member ≥ 4.5:1 as text on cream.
- **§3.6 Regime colors.** All ≥ 3:1 on cream/paper (the darker regime members
  clear 4.5:1). The six are mutually distinct because `--regime-neutral` is the
  **one cool outlier** (periwinkle) set against an otherwise warm ramp — maximum
  separation by hue family, which the doc calls "an LLM's safest move." Risk-on
  and crisis endpoints coincide with `--green` / `--deep-red` as §3.6 permits;
  the four middle regimes each differ.
- **§3.7 Charts.** Plotly inherits `--panel` (paper / green-black) + `--text`;
  sane pair → sane charts on every figure. Server-baked trace colors are
  unchanged (§4.6 — out of scope for a CSS theme).

---

## 6. How it meets the three drivers

- **Aesthetic / identity.** The spring/watercolour character is real and present
  — cream paper, cinnamon borders, lilac accent, hills green, warm-earth ramp —
  but expressed through the *dominant surfaces*, not applied as decoration. It
  reads as a considered, humane desk rather than a novelty skin. (Maeda's
  *aichaku* — a tool you sit at for hours and feel attached to.)
- **Functional / readability.** Contrast cleared analytically above; the §5
  Playwright check confirms at build time. This is a **recolor, not a layout
  change**, so the Command Deck's deliberate scan-density (the Refactoring UI
  dashboard-density exception, applied per Maeda's rhythm principle) is
  preserved.
- **Consistency / system gaps.** The new theme is **one CSS block + one
  registration line** — zero component changes. Verified: the only concrete
  color reference in any `.tsx`/`.ts` is a harmless `var(--accent, #33b5e5)`
  fallback in `RcsIntakePanel.tsx` that never fires when the token is defined.
  It conforms to the existing 19-token contract exactly, so it inherits every
  existing interaction and introduces no new gaps.

---

## 7. Implementation scope (small, per the contract)

**Color (per §4 of the workflow doc):**
1. Add `:root[data-theme="spring"] { … }` (light) — and optionally
   `:root[data-theme="spring-shade"] { … }` (dark) — to
   `frontend/src/theme.css`.
2. Register the id(s) in `THEMES` in `frontend/src/theme.ts`.
3. `cd frontend && npm run build` — must be clean.
4. Run the §4.4 grep — must print nothing (all hex lives in `theme.css`).
5. Run the §4.5 Playwright check — assert contrast + the `data-theme` attribute
   + reload-persistence + a chart page's `paper_bgcolor` = `--panel`.

**Font pack (per §7 of the workflow doc, layered onto the same theme block):**
6. Self-host Inter (variable), Newsreader (variable), JetBrains Mono (400/500)
   as `@font-face` at the top of `theme.css`; drop woff2 files in
   `frontend/public/fonts/`.
7. Set `--font-sans` / `--font-body` / `--font-mono` in the `spring` block (and
   `spring-shade`).
8. Run the §7.5 font-pack checklist — data audit, numeric audit (scorebars +
   returns table right-edges), no wraps at 208px sidenav, chart font.family
   resolves to Inter, `textarea.json` stays mono.

**Both:**
9. Screenshot the Command Deck (chrome-dense: regime banner, chips, jobs) **and**
   the Parameters page (form-dense: where the serif body lives); eyeball the
   warm/cool balance, the serif/sans/mono balance, and the §5 acceptance
   checklist.

---

## 8. Explicit non-goals

- Does **not** touch the existing dark / light / terminal themes — additive only.
- Does **not** restyle server-baked Plotly trace colors (§4.6 backend task, out
  of scope for a CSS theme).
- Does **not** change layout, spacing, type scale, or add new tokens. (Those are
  separate synthesis-grounded improvements; this is a *theme* in the doc's
  strict sense.)
- Does **not** soften the semantic ramp. `CRISIS` stays a real red. **The spring
  is in the chrome, never the meaning.**

---

## 9. Open questions for evaluation

- **Accent — how cool?** The accent moved from violet `#6d4d8a` (Rev 1) to a
  cooler sky-periwinkle `#5b7caa` (Rev 2) to carry the equinox brief. It's the
  tightest-contrast token (≈4.6:1, just over the bar). Options if it reads too
  cold or too faint: (a) keep `#5b7caa`; (b) deepen to `#52719a` for safety
  margin; (c) split the difference back toward lilac `#6a6aa0` (warmer-cool,
  more "flower," still clearly not green/amber/red). The choice is a
  warm-vs-cool *weight* decision, not a pass/fail one.
- **Serif face — how much whimsy?** Newsreader is the goldilocks pick (editorial
  charm, screen-engineered). If the brief wants *more* whimsy, Fraunces is the
  louder option (worth mocking up the Parameters form in both and comparing).
  If it wants *less*, Source Serif 4 is the quieter workhorse.
- **Dark companion.** Ship `spring-shade` together with `spring`, or land the
  light theme alone first? The doc says themes ship in pairs, but a single
  additive theme is valid.
- **Neutral regime color.** Slate-blue `#5a7a9a` is the cool outlier that
  reinforces the equinox. If it reads too "cold" against the warm earth palette,
  a muted sage-teal `#4a7d74` keeps it cool-but-earthy while preserving the
  green↔neutral distinction.
