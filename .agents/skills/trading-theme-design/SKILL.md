---
name: trading-theme-design
description: Design and ship a new visual theme (and optional font pack) for the trading workstation. Use whenever the user wants to retheme the app, add a visual theme, design a color palette for the workstation, swap typefaces, or evaluate a theme proposal — even if they don't say "theme" explicitly (e.g. "make it warmer", "spring palette", "add a dark variant", "wire in the colors"). Covers the full pipeline: design-knowledge grounding → palette generation under the §3 contract → implementation per the theme doc → §5 verification.
---

# Trading Theme Design

Designs and ships themes for the React workstation against two coupled
sources: the **design synthesis** (how to choose colors/type well) and
`docs/wiki/04-workflows/creating-a-theme.md` (the contract a theme must
satisfy to ship). The central lesson this skill encodes: **treat those two
as one constraint set, not two phases.** The §3 contract is a *generative*
constraint during design, not just a *verification* gate at the end.

## The two source documents — read both before designing

1. **`docs/wiki/04-workflows/creating-a-theme.md`** — the contract. A theme
   is exactly **one `:root[data-theme="<id>"] { … }` block of 32 tokens +
   one `THEMES` registration line**. §2 lists the token inventory; §3 the
   contrast rules; §4 the implementation steps; §5 the acceptance checklist;
   §7 the font-pack contract. Every shipped theme must satisfy §3 + §5.
2. **The design synthesis** at
   `~/Nextcloud/claude/D-design-knowledge/synthesis/design-synthesis.md`
   (+ the four distillations it synthesizes: Albers color, Maeda simplicity,
   Brockmann grid, Refactoring UI web). This is the *why* behind good palettes.

Read both. Do not design from intuition; do not ship without verification.

## The pipeline (run in this order)

### 1. Decode the brief into the two-system split

Every brief — even a poetic one ("spring watercolours, lush hills") — splits
into two systems that obey **different design rules**. Name them explicitly
before choosing any color:

- **The chrome** (`bg`, `panel`, `panel-2`, `border`, `text`, `muted`,
  `accent`, `on-accent`) — aesthetic/hierarchical function. Here **Maeda +
  Refactoring UI win**: reduce, systematize, pick one disciplined accent,
  get surface layering right. The brief's *mood* lives here, in the dominant
  surfaces (Albers quantity principle — mood owns area).
- **The semantics** (the status ramp `green<amber<orange<red<deep-red` + the
  six `--regime-*` colors) — these carry **irreducible data meaning**. Here
  **Albers wins, not Maeda**: never reduce, never "harmonize," never soften.
  `CRISIS` stays a real red. The job is *context-tuning* — hand-adjusting
  each against the new `--bg`/`--panel` (Albers subtraction principle: a
  background subtracts its own hue from marks on it).

Getting this split wrong is the #1 cause of broken themes. A pastel theme
that renders `CRISIS` peach has violated Maeda Law 9 (don't hide irreducible
meaning).

### 2. Generate the chrome under the §3 contract as a generative constraint

Choose the 8 chrome tokens *while reading §3*, not after. The constraints
that shape the choice:

- **§3.1 surface ladder:** `panel` raised above `bg`, `panel-2` between them
  (hover/chips), `border` distinguishable from all three. In practice every
  pair needs **≥1.1:1 contrast** or the surfaces read as one.
- **§3.2/§3.3:** `--text` and `--muted` ≥4.5:1 on both `--bg` and `--panel`.
  The `--muted` trap: it's used at 11–12.5px, so it must hold 4.5:1 too —
  "muted" ≠ "faint."
- **§3.4:** `--accent` ≥4.5:1 as text on both surfaces AND ≥3:1 vs
  `--on-accent`. Accent is usually the **tightest token** — pick its value
  *by solving for the 4.5:1 bar*, not by taste, then adjust taste within
  that envelope. The accent must also be distinct from green/red (§3.5) so
  "actionable" ≠ "good."

### 3. Generate the semantics by hue-family + lightness stepping

The status ramp and regime colors are an **ordinal perceptual scale** — they
must read as ordered *and* be mutually distinguishable. Two failure modes
to avoid (both hit the spring theme on first pass):

- **Warm-ramp adjacency collapse:** amber/orange/red live within a ~30° hue
  band, so adjacent severity steps can't separate by hue alone. Separate
  them by **lightness** within the family (the ColorBrewer RdYlGn approach).
  Where a hue shift is needed to separate two reds (e.g. stress vs crisis on
  a dark ground), push the worse one toward magenta/rose — never toward
  another warm color.
- **Context washout:** a semantic color that passes on white may fail on a
  tinted background (Albers subtraction). Re-verify every semantic color
  against the *new* `--bg` and `--panel`, not the old theme's.

The regime endpoints may equal `--green`/`--deep-red` (§3.6 permits); the
middle four must each differ.

### 4. Run the verifier BEFORE writing to the file

This is the step that was missing the first time around. **Do not commit
candidate values to `theme.css` and discover failures via §5 after.** Run
`scripts/verify_theme.py` against candidate values first — either by writing
them to the block and checking, or by prototyping the palette in a scratch
check. The script computes WCAG ratios from the values as-shipped and flags
every §3/§5 violation with the exact token and ratio.

```bash
python3 .agents/skills/trading-theme-design/scripts/verify_theme.py <theme_id>
```

Exit 0 = all doc-mandated quantitative checks pass. Iterate the palette
until it does, *then* move on. This turns §5 from a discovery gate into a
confirmation gate.

If you used the design-knowledge grounding in step 1–3, most candidates
pass first try. When a token fails, the script names the failing rule —
fix that token specifically (the fix is usually a small lightness move, not
a re-think).

### 5. Implement per the theme doc §4

Once the palette verifies:

1. Add `:root[data-theme="<id>"] { … }` to `frontend/src/theme.css` —
   **all 32 tokens** (13 color + 6 regime + 3 font stacks + 10 type scale).
   Omitting tokens silently inherits `:root` → broken hybrid (§2's "most
   common LLM error"). Copy the most similar existing block as a template.
2. Register the id in `THEMES` in `frontend/src/theme.ts` (dropdown order).
3. Values must be plain colors — **no `var()`, no `color-mix()`, no
   gradients** inside token values (`cssVar()` passes them to Plotly).
4. `cd frontend && npm run build` — must be clean.
5. `grep -rnE "#[0-9a-fA-F]{3,8}|rgba?\(" frontend/src --include="*.tsx" --include="*.ts"`
   — must be empty except the one known harmless `var()` fallback in
   `RcsIntakePanel.tsx` (§4.4 leak check).

### 6. The two checks that need a live dev stack

The verifier covers every *quantitative* §5 item. Two remain, both requiring
API :8100 + frontend :5173 running (see `docs/wiki/04-workflows/running-and-operating.md`):

- **§4.5 Playwright** — asserts `data-theme` applies, computed colors match
  tokens, `localStorage["ui-theme"]` persists across reload, and a chart
  page's `_fullLayout.paper_bgcolor` = `--panel`.
- **§5 screenshot eyeball** — the doc is explicit that contrast checks are
  "necessary, not sufficient." Screenshot the Command Deck (regime banner +
  chips + jobs — chrome-dense) and a chart page in the new theme, and
  confirm the warm/cool or thematic balance reads as intended. The verifier
  flags any adjacent severity pairs that are numerically close on the ramp —
  in the screenshot, confirm the **chip text labels** (always rendered
  alongside color, per synthesis Rule C4) make those distinctions clear.

## Font packs (optional, layered on top)

If the brief includes type (e.g. "a little whimsy, elegant"), §7 of the
theme doc defines a **font pack** — a swap of the three stack tokens
(`--font-sans` chrome / `--font-body` reading+forms / `--font-mono` data)
layered onto any theme block. It is **not a new theme**.

The typography knowledge lives in the synthesis (Rules T1–T4, §3.4,
Conflict 2) and Refactoring UI §2.21–2.28 — there is no standalone
typography distillation (Bringhurst was pending, never completed). Key
rules from the synthesis:

- **Chrome stays neutral sans** (Inter-class). High x-height, ≥5 weights.
- **The reading/forms role is the play area** — serif lives in
  `--font-body`, never chrome. That's where any whimsy goes.
- **Data stays mono** (protects char-count truncations). Never proportional.
- **No modular/classical type scale** — synthesis Conflict 2: hand-crafted
  wins for data UI. Keep the existing `--fs-*` ramp.
- Self-host via `@font-face` at the top of `theme.css`; every stack ends in
  a system fallback (offline-friendly).

## Design-knowledge grounding — the principles that make a palette good

These are the load-bearing synthesis principles for theme work. Apply them
during step 2–3, not as post-hoc justification:

- **Albers — quantity over harmony:** the brief's mood owns *area*
  (backgrounds); semantic marks stay saturated and small. Any color works
  with any other if quantities are right.
- **Albers — subtraction:** a background subtracts its own hue from marks.
  Hand-tune semantic colors per theme, never formulaically invert. Dark
  mode is not a palette inversion.
- **Albers — context (relativity):** every color must be tested against the
  surface it sits on. The verifier does this for contrast; the eyeball does
  it for perceived hue.
- **Maeda Law 9:** the semantic ramp is irreducible complexity. Don't hide
  it. Restraint applies to chrome only.
- **Refactoring UI C3 (flip contrast):** status chips read as dark saturated
  marks on pale tinted fills — already the `theme.css` pattern via
  `color-mix()`. Lean into it; it's what makes pastel backgrounds safe for data.
- **Brockmann:** a disciplined surface ladder (3 tints + border, geometrically
  stepped) is what stops a themed look reading as decorative. Order = trust.

## Writing a proposal doc (optional, for evaluation)

For a non-trivial theme, write a proposal to `docs/plans/<name>-theme-proposal.md`
*before* implementing, so the user can evaluate direction. Structure:

1. The brief, decoded into the two-system split (chrome vs semantics) with
   temperature notes (warm/cool balance — themes often fail by being
   one-temperature).
2. The central design problem and how the synthesis resolves it.
3. The 19 color tokens (or full 32 incl. fonts) in a table matching the
   theme doc's §2 shape — with a "role in the brief" column.
4. §3 contract satisfaction, reasoned analytically (cite the ratios).
5. Implementation scope + explicit non-goals (additive only; no trace
   restyle; semantic ramp stays real).
6. Open questions (accent hue, serif face, dark companion, etc.).

## Common failure modes (from the first theme built under this skill)

- **Accent fails 4.5:1 as text** — it's the tightest token. Solve for the
  bar first, then taste.
- **`--panel-2` indistinguishable from `--bg` or `--border`** — widen the
  surface ladder; every pair ≥1.1:1.
- **Warm-ramp adjacency collapse** (amber≈orange, stress≈crisis) — separate
  by lightness within the family; hue-shift the worse red toward magenta.
- **Semantic color fails on tinted background** — re-verify against the new
  `--bg`/`--panel`; the value that worked on white probably needs darkening.
- **Token omission → silent `:root` inheritance** — define all 32 every time.
- **Treating synthesis and §3 as two phases** — they're one constraint set.
  The verifier is the bridge; run it on candidates, not just final values.
