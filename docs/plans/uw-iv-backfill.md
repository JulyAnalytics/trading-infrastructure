# UW Historical IV Backfill — Reworked Plan (Trial + Month)

Status: **plan v2** (not implemented) — supersedes `uw-iv-backfill.md` v1
Date: 2026-08-02
Scope: `trading-infrastructure` only — no RCS changes, no research.db writes.
Companion: `docs/plans/uw-refresh-capabilities.md` (what the live refresh enables).

## 1. Goal

Capture historical implied-volatility data from the Unusual Whales API into
`vol_signals` / `vol_surface` (DuckDB `trading.db`) across **two consecutive
windows**, with maximum durable value and minimal redundant spend:

| Window | Duration | Quota | Total | Lookback |
|---|---|---|---|---|
| Free trial | 6 days × 30K/day | **180K** | 90 days | |
| Paid month | 30 days × 30K/day | **900K** | 2 years | |
| **Combined** | | **1.08M** | | |

Planned spend ≈ **815–925K** — headroom ~160–270K for retries, watchlist growth,
and research endpoints.

## 2. Key design principle

The trial's 90-day data is **almost entirely re-captured** by the month's 2-year
backfill (the 2y window contains the trial days). Therefore:

- **If the month is likely**: the trial's job is *validation + calibration*, not
  capture. Its spend is insurance.
- **If the month is uncertain**: the trial must still end with a durable 90-day
  dataset.
- Resolution: the trial spends only ~150K on capture + refresh — cheap enough to
  be worth it either way, and the 4 live refresh days are the only way to validate
  the daily job before committing.

## 3. Tiered universe (applies to both windows)

| Tier | Members | History depth | Per-ticker calls (90d / 2y) |
|---|---|---|---|
| **Wide** — all US optionable (~7K) | screener universe, cached `data/processed/market_tickers.csv` | ATM IV + IVR/IVP + RV/VRP + spot | 1–2 / 2–3 |
| **Skew-wide** — same 7K | RR series at 2–4 expiries × Δ25/Δ10 (per-day nearest-45-DTE pick) | `skew_25d_rr` (sign-flipped) | 3 / 6–8 |
| **Medium** — S&P 500 + watchlist | per-day term-structure | TS columns, slopes, `ts_shape`, `term_structure_json` | 63 / 504 |
| **Deep** — 5 ETFs + 11 sectors + AAOI + non-SP500 watchlist | medium + surface (month only) | `vol_surface` history, `skew_by_delta_json`, `pc_oi_ratio_json` | 63 / 504 (+surface 2–6K) |

- Skew is a *cheap series call* (full per-day history per call) — market-wide skew
  is nearly free.
- TS is the expensive one (per-day calls) — it is the only component that doesn't
  scale, so it stops at S&P 500 + watchlist breadth.
- Weekly TS sampling (13 calls/90d, 101/2y) is a documented fallback if quota gets
  tight; caveat: sampled rows leave ~80% of `ts_*` NULL, fine for screens, not for
  the analog feature vector.
- The probe checks for a bulk TS-history endpoint (`variance-risk-premium` is
  documented as returning "history" arrays, shape unspecified) — if found, the
  whole TS cost picture improves.

## 4. Trial phase (days 1–6, 180K, 90-day lookback)

**Precondition**: all code (client, scripts, jobs) and the Phase-A screens
(IVR league table, zone crossings, event screen, IVR breadth, RCS intake
enrichment) are **built and tested before day 1** — trial days are calibration
days, not development days.

| Day | Activity | Calls |
|---|---|---|
| 1 | Probe (5 live checks) + dry-run SPY + calibration; full-market ATM (~7K × 1–2) | ~30K |
| 2 | Full-market skew (~7K × 3) | ~21K |
| 3 | SP500 TS (500 × 63) + deep TS (19 × 63) + first full-market refresh | ~30K |
| 4–6 | Full-market refresh (~21K/day) — 4 daily snapshots; screen calibration | ~63K |
| | **Total** | **~148K** (buffer 32K) |

**Trial deliverables**:
1. Pipeline validated end-to-end (probe → backfill → refresh → verification).
2. Durable 90-day dataset if you stop here: 7K names ATM+skew, 500 names TS,
   19 names deep, 4 live snapshots.
3. Decision evidence: screens calibrated, thresholds set, daily workflow proven.

**Gate 1 (end of day 6)**: subscribe for the month (2y) or stop. If stop, you own
the 90-day dataset + validated pipeline; screens run on local data (relevance
~3–4 months before vol-regime drift).

### Trial-only gaps (if you never subscribe)

| Capability | Trial (90d) | Impact |
|---|---|---|
| Analog search (120d gate) | 63d < 120d — dormant | flagship Stage 5 feature off |
| IVR/IVP confidence | `medium` (60–119d) | panels keep the "don't fully trust" flag |
| Stress scenarios (Volmageddon, COVID…) | out of reach | Stage 3 stays endpoint approximations |
| Vol cones / matched-maturity VRP | 90d partial / ~30–60 samples | first look, not a distribution |
| Term-structure & skew percentiles | 63d windows | noisier context |

## 5. Month phase (days 7–36, 900K, 2-year lookback)

| Line item | Calls | Days (at ~30K/day) |
|---|---|---|
| Full-market ATM (7K × 2–3) | ~20K | |
| Full-market skew (7K × 6–8) | ~42K | |
| SP500 TS (500 × 504) | 252K | |
| Deep TS (19 × 504) | ~10K | |
| Surface — deep set (optional, capped) | 40–100K | |
| **Backfill subtotal** | **~364–424K** | **~12–14** |
| Full-market refresh (21K × ~12–21 trading days) | 252–441K | 12–21 |
| **Month total** | **~616–865K** | |

Sequencing: backfill days 1–14 (ATM+skew+deep TS first, SP500 TS across ~9 days,
surface last), then daily refresh days 15–36. Headroom (~35–285K) options: extend
refresh breadth to ~10K names/day (full quota), extra watchlist additions, or
research endpoints (VRP history, VIX term-structure history).

**Month deliverables**:
1. 2-year dataset: 7K names ATM+skew, 500 names TS, 19 names deep with surface.
2. IVR/IVP `standard` confidence everywhere; analog search fully unlocked
   (≥120d candidates; the route warning disappears).
3. Matched-maturity VRP machinery live (~470 samples per ticker).
4. Daily market-wide IVR breadth + screens running through the window
   (≈12–21 snapshots).

**Gate 2 (end of month)**: renewal decision — steady-state need is ~2–3K/day
(core-only tier) *unless* you keep market-wide refresh (~21K/day), which justifies
staying at the current tier. The 2-year local dataset is a permanent asset either
way.

## 6. Delta vs plan v1

- Trial window (6d/180K/90d) added as an explicit first phase with Gate 1.
- Tiered universe replaces two-tier: **skew now market-wide** (cheap series
  calls), **TS for S&P 500 + watchlist** (medium tier), surface stays deep-only.
- SP500 TS becomes the largest single line item (252K) — the price of term
  structure at market breadth; acceptable because everything else got cheap.
- Refresh sequencing fixed so backfill and full-breadth refresh never contend for
  the same day's quota.
- Phase 2 surface moved entirely into the month (trial surface = worst
  cost-per-value; superseded at 2y anyway).

## 7. Files

**New**: `systems/data_feeds/uw_feed.py` (Bearer auth, `UW-CLIENT-API-ID`,
retry/backoff, pacing ~120 rpm, string→float parsing, `probe()`, iv-rank /
term-structure / RR-series / realized / screener / contract lookup),
`scripts/backfill_iv_history.py` (Phase 1, flags `--deep-only --medium-only
--skew-wide --wide-only --dry-run --force --watchlist-file`, tickers via argv or
`JOB_ARGS_JSON`, resumable per ticker), `scripts/backfill_vol_surface_history.py`
(month phase), `scripts/uw_daily_refresh.py`, `scripts/trade_context_report.py`
(read-only bonus), `data/inputs/watchlist.csv`, `data/processed/market_tickers.csv`
(generated), `docs/plans/uw-iv-backfill.md` (this file),
`docs/plans/uw-refresh-capabilities.md` (companion).

**Modified**: `systems/sarah/vol_db.py` (+`insert_vol_signals_history`,
`insert_vol_surface_history`, `refresh_latest_ivr` — all `ON CONFLICT DO NOTHING`
never-overwrite semantics), `config.py` (`UNUSUAL_WHALES_API_KEY`), `.env` (key
placeholder), `systems/orchestration/jobs.py` (3 `JOB_SPECS` entries),
`systems/orchestration/run_job.py` (3 runners, runpy pattern),
`systems/params/models.py` (`OpsParams.uw_refresh_time: str = "18:30"` +
FIELD_SPECS), `systems/orchestration/scheduler_v2.py` (weekday refresh block),
docs (`data-feeds.md`, `build-status.md`, `jobs-and-scheduling.md`).

## 8. Execution sequence (with gates)

1. Build client + probe; spec-grep for bulk TS-history / contract-lookup
   endpoints; build the Phase-A screens. (No token needed.)
2. Buy/start trial; add token to `.env`; paste watchlist into
   `data/inputs/watchlist.csv`.
3. **Trial day 1**: probe + dry-run SPY → calibration report, zero writes.
4. **Trial days 2–6**: capture + refresh per §4; calibrate screens.
5. **Gate 1** → subscribe month (or stop with the 90-day dataset).
6. **Month days 1–14**: 2-year backfill per §5 (ATM+skew+deep TS → SP500 TS →
   surface). **Days 15–36**: daily market-wide refresh + screens.
7. Verify each phase: row counts (63/504 per ticker), coverage, analog ≥120
   candidates, confidence `standard` (month), `/api/context/vol-signals` and
   pre-trade panels unchanged in shape, idempotence on re-run.
8. **Gate 2** → renewal tier decision.

## 9. Guardrails (unchanged from v1)

- Existing rows never overwritten (`ON CONFLICT DO NOTHING`); today's core rows
  stay yfinance-authoritative; latest-row IVR/IVP refreshed in place.
- Daily vol run unchanged (yfinance remains the live source; UW drift handled by
  overlap-day calibration, additive offset when |drift| > 2.0 vol pts).
- No scheduler changes beyond the new refresh block; no new Python deps; no
  research.db writes (trade-context report read-only); token only in `.env`.
- Resumable per ticker; 429/5xx retry/backoff; if a tier serves less than its
  nominal lookback, capture what's available and report.

## 10. Budget summary

| Phase | Calls | Result |
|---|---|---|
| Trial (6d × 30K) | ~148K | 90d dataset + validated pipeline + calibrated screens |
| Month (30d × 30K) | ~616–865K | 2y dataset (7K ATM+skew, 500 TS, 19 deep+surface) + refresh |
| **Total of 1.08M** | **~765K–1.01M** | ~160–270K headroom (retries, growth, research) |
