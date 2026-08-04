---
domain: trading-system
stage: wiki
project: ashurbanipal-integration
status: active
---

# Knowledge Library Integration — Ashurbanipal II

*How the trading system's knowledge plugs into the personal knowledge
library ("Ashurbanipal", `Knowledge Library/` — the epistemological hub for
every project), and what the library gives back. This page is the
trading-side half of the contract; the library-side specs live in
`Knowledge Library/ashurbanipal-intent.md` (§5 Source Adapter layer),
`technical-companion.md` (T3/T4/T7/T9), and the frontmatter feature brief in
`Knowledge Library/architecture-proposals/`.*

## Why integrate

The trading system continuously *produces* knowledge — weekly reviews,
pre-trade memos, a curated vol-event library, research verdicts, audit
docs, this wiki — and continuously *consumes* it (the Jordan risk layer was
built from five literature distillations; every persona is grounded in
sources). The library is where both directions become durable:

- **Trading → library:** the system's artifacts become cataloged,
  concept-linked, searchable documents — "what did my week-of-July-18
  review say about credit divergence?" becomes a query, and every claim
  stays traceable to its source (the rigor ladder's grounding rule).
- **Library → trading:** a thesis or memo can pull a **grounding pack** —
  distillations + citations + an honest coverage disclosure — so "Sinclair
  says vol cones beat point forecasts" arrives with the page it came from,
  and "the library has nothing on dispersion" is said out loud instead of
  papered over.

Both systems already share the same constitutional rule: **foreign stores
are read-only at the driver level** (the library's connectors mirror this
repo's RCS bridge guarantee — the library plan cites it explicitly).

## Library state (so this page stays honest)

As of **2026-07-19** (`Knowledge Library/Wiki/05-status/build-status.md` is the
living truth): librarian API + faceted hybrid search + React GUI (now with
Concepts + Cytoscape graph) **live** on the Mini at `:8454`; the **Source
Adapter layer is a real layer** (Protocol + registry + a generic mapping DSL);
a **deterministic concept graph + typed cross-app links** exist without the
rig; and a **grounding MCP MVP** (`search_library` / `get_document`) works over
the tailnet.

**The trading integration is now live in two forms** (both landed 2026-07-19):
- **Files** — `filesystem_trading_system` indexes `Claude/B-trading-system`
  (69 docs), lifting this wiki's `domain/stage/project/persona/status`
  frontmatter into query axes. (This *repo's* `docs/`+`reports/` are not yet
  added as a source — that's still a config+ACL decision, see 1a.)
- **Databases** — the `trading` source is built against the **`:8100` API**
  (not a DuckDB connector — see 1b for why the design changed), mapping memos,
  hypotheses, regime transitions, the research verdict, and backtest runs. It
  currently reports **`offline`** because the MacBook API isn't exposed on the
  tailnet yet (one command — see the checklist).

**Still rig-gated:** LLM enrichment, distillation/synthesis (Phase 4), and the
flagship `grounding_pack`. Everything else below is live or one command away.

## Direction 1 — trading artifacts into the corpus

### 1a. Files (ride the filesystem adapter + frontmatter)

Every page in this wiki now carries the cross-surface frontmatter from the
feature brief (`domain` / `stage` / `project` / `persona` / `status`), so
the filesystem adapter can lift them into the catalog with persona and
project as query axes ("everything Sarah-persona-owned, still active").
The other file-shaped artifacts:

| Artifact | Path | Suggested shelf treatment |
|---|---|---|
| This wiki (28 pages) | `docs/wiki/**.md` | one document per page; frontmatter carries persona/project |
| Audit docs (capability maps + output literacy) | `docs/audit/0[1-5]_*.md` | high-value: these are the system's own "distillations" of itself |
| Weekly reviews | `reports/weekly/weekly_review_*.md` | **one document per week** — the trading system's episodic memory; each stamps its parameter hashes |
| ADRs + architecture docs | `docs/design_decisions/`, `docs/architecture/` | decision provenance |
| Vol event library | `data/events/regime_events.yaml` | one **entity** per event (already structured: dates, surface state, lessons) |

*Scope note for the library side:* the corpus root currently indexes the
`Literature/Documents/Resources` shelves. Adding
`Trading/trading-infrastructure/{docs,reports}` as shelves is a
config + ACL decision on the Mini, not new code.

### 1b. Databases (the `trading` source — via the `:8100` API)

**Design change (2026-07-19):** the library reads trading data through the
**FastAPI service layer (`:8100`)**, not a DuckDB connector over the synced
files. Two reasons: the API is the locked, versioned contract (raw DuckDB
schema is internal and can churn), and a Nextcloud-sync-replicated `.duckdb`
can be caught mid-write. Cost: the source only ingests while the MacBook API
is up — which is fine, because the library treats an unreachable source as a
normal **`offline`** state (it keeps its watermark and moves on), not a failure.

It's wired through the library's **generic adapter + mapping DSL** — no bespoke
`adapters/trading.py`. The live mapping (`mini:~/knowledge-library/mappings/trading.yaml`):

```yaml
connector: {kind: http, base_url: "http://100.65.227.83:8100", health_path: /health}
collections:
  memo:                    # /api/sarah/memos  → one entity per PTM memo
    grain: entity
    id: "{memo_id}"; native_ref: "trading://memo/{memo_id}"
    detail_path: /api/sarah/memos/{memo_id}     # full memo_json as the body
    updated_at: "{created_at}"
  hypothesis:              # /api/priya/hypotheses
    grain: entity; native_ref: "trading://hypothesis/{hypothesis_id}"
  regime_transition:       # /api/marcus/transitions → one entity per regime change
    grain: entity; native_ref: "trading://transition/{date}"
  research_verdict:        # /api/priya/verdict (single object)
    grain: entity; native_ref: "trading://verdict/current"
  backtest_run:            # /api/priya/runs → one entity per run
    grain: entity; native_ref: "trading://run/{run_id}"
  backtest_runs:           # same endpoint, grain: dataset → the run archive as one asset
    grain: dataset
```

Grain choices follow the plan's guardrail (entities + datasets; **no row grain
for market time-series** — `vol_surface`/`macro_series` values are never
ingested, only cataloged as *assets*). Watermarks come from `created_at` /
`registered_at` / `logged_at`; `regime_transition` keys off the transition date.

**This closes the two RCS↔trading link gaps at the library layer** (see the
cross-app note below): PTM memo ids have no field in the RCS schema, and
Priya's `hypothesis_registry` has no thesis-ULID column — so those links only
existed as free text. The library's link builders now scan every document's
body for `PTM-…` ids and `rcs://`/ULID references and mint typed
`document_links` (`mentions_memo`, `mentions_rcs`) with offset evidence,
regardless of which app authored the text.

### 1c. Provenance convention (already in place on this side)

Stable citable IDs exist today: `PTM-…` memo ids, `hypothesis_id`s, weekly
review filenames, wiki page paths. The rule mirrors the RCS
`canvas_source_documents` pattern the library adopted: **record the link at
the moment of use** (a journal note citing its memo; a memo citing a
distillation) — semantic search is for discovery, explicit links are for
provenance.

### 1d. To strengthen the cross-app links (a small convention)

The link builders find whatever is *written down*. To make the thesis→backtest
and memo→journal chains structural rather than incidental, cite the other side
explicitly at authoring time:
- In a Priya hypothesis `rationale`, cite the originating RCS thesis as
  `rcs://thesis/<ULID>`.
- In an RCS note or a memo comment, paste the `PTM-YYYYMMDD-TICKER-NNN` id.

Each such reference becomes a typed, evidenced `document_links` row on the next
`--signals` pass — no schema change in either app.

## Direction 2 — the library grounding trading work

**Available now (deterministic):** the grounding MCP MVP is registered on the
MacBook — any Claude session can `search_library("vol risk premium",
domain="trading-system")` and `get_document(id)` (which returns the doc's
concepts and its typed cross-app links). That already lets an assistant pull
*your* prior memos, hypotheses, and persona docs with provenance, short of
prose distillation.

**Arrives with the rig:** the flagship `grounding_pack(topic, objective)` →
curated distillations + citations + **coverage disclosure**:

| Trading moment | Grounding call | What it changes |
|---|---|---|
| Writing a thesis / memo rationale | `grounding_pack("vol risk premium", objective=trading)` | the rationale cites shelf→page sources instead of vibes |
| Registering a hypothesis | ditto, on the hypothesis mechanism | the *rationale* field becomes literature-grounded |
| Reviewing a drawdown / episode | `get_distillations(topic)` for the relevant persona sources | the review argues with the literature, not just the P&L |
| An LLM assistant guiding you | see the [LLM guide](../00-system/llm-assistant-guide.md) | the assistant cites library doc ids and **discloses coverage gaps** rather than fabricating support |

The five Jordan distillations and the persona files under
`Claude/B-trading-system/` are the manual grounding set today — and they're now
also *cataloged and concept-linked* via `filesystem_trading_system`, so
`search_library` surfaces them alongside everything else.

## What stays out (both directions, by design)

- Market **rows** (vol_surface strikes, macro series values) — the library
  catalogs *that you hold the data*, never the ticks.
- The RCS journal — it has its own live adapter; the trading system doesn't
  re-export it.
- Sentiment/ambient sources — the library's anchor-bias guardrail keeps
  them downstream of your own theses; nothing here changes that.
- Writes, in either direction, ever.

## Activation checklist (what's left)

1. ✅ ~~DuckDB connector + `adapters/trading.py`~~ — **done differently**:
   generic adapter + `mappings/trading.yaml` over the `:8100` API (1b).
2. ✅ ~~filesystem adapter lifts this wiki's frontmatter~~ — live
   (`filesystem_trading_system`, 69 docs).
3. **Bring the `trading` source online:** expose `:8100` on the tailnet from
   the MacBook — `tailscale serve --tcp 8100` — then
   `ssh mini 'cd ~/knowledge-library && .venv/bin/python run_ingestion.py --source trading'`
   (or wait for the nightly sweep). Until then it's `offline` by design.
4. *(Optional)* add this repo's `docs/` + `reports/` as filesystem sources or
   shelves if you want the audit docs and weekly reviews cataloged as
   documents (config + ACL on the Mini — no code).
5. Keep this page's *Library state* section honest as things change — it's the
   anchor. Library-side truth: `Knowledge Library/Wiki/05-status/build-status.md`.
