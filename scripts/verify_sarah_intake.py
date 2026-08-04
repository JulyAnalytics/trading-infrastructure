"""
Sarah ← RCS trade intake verification (spec §10).

Offline by default: the schema, watermark, derivation, merge and validation
logic all run against a throwaway trading.db. The RCS-side checks run only if
the journal is present, and are strictly read-only either way.

What it deliberately does NOT do: fetch an options chain or build a memo.
Those are network paths, covered by running the job for real.

Usage:
    python scripts/verify_sarah_intake.py
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config  # noqa: E402
from systems import params as P  # noqa: E402

PASS = FAIL = 0


def check(label: str, condition: bool, detail: str = ""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✓ {label}")
    else:
        FAIL += 1
        print(f"  ✗ {label}  {detail}")


def main() -> int:
    tmpdir = Path(tempfile.mkdtemp(prefix="sarah_intake_verify_"))
    orig_vol_db = config.VOL_DB_PATH
    # Patch BEFORE importing the intake modules — they bind VOL_DB_PATH at
    # import time, so a throwaway DB has to be in place first.
    config.VOL_DB_PATH = str(tmpdir / "verify.db")
    P.invalidate_cache()

    try:
        # ── Schema (spec §7 item 4) ──────────────────────────────────────────
        print("── Migration ──")
        from systems.sarah.vol_db import initialize_vol_schema
        from systems.utils.db import get_connection
        initialize_vol_schema()
        conn = get_connection(config.VOL_DB_PATH)
        try:
            tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
            cols = lambda t: [r[1] for r in conn.execute(  # noqa: E731
                f"PRAGMA table_info('{t}')").fetchall()]
            check("sarah_trade_inputs created", "sarah_trade_inputs" in tables)
            check("sarah_intake_watermark created",
                  "sarah_intake_watermark" in tables)
            ti = cols("sarah_trade_inputs")
            for c in ("rcs_trade_ulid", "ticker", "expected_move",
                      "expected_move_sign", "thesis_days", "catalyst_type",
                      "max_loss_budget", "flow_json", "source", "created_at",
                      "updated_at", "last_error", "rcs_instrument"):
                check(f"sarah_trade_inputs.{c}", c in ti)
            check("pretrade_memos.rcs_trade_ulid (citation key)",
                  "rcs_trade_ulid" in cols("pretrade_memos"))
            check("initialize_vol_schema is idempotent",
                  initialize_vol_schema() is None)
        finally:
            conn.close()

        # ── expected_move validation (the percent-vs-decimal bug) ────────────
        print("\n── expected_move: unsigned, non-zero decimal fraction ──")
        from systems.sarah.trade_intake import (
            MAX_EXPECTED_MOVE, MIN_EXPECTED_MOVE, validate_expected_move,
        )
        check("0.20 accepted", validate_expected_move(0.20) == 0.20)
        check(f"{MIN_EXPECTED_MOVE} accepted (lower bound)",
              validate_expected_move(MIN_EXPECTED_MOVE) == MIN_EXPECTED_MOVE)
        check(f"{MAX_EXPECTED_MOVE} accepted (upper bound)",
              validate_expected_move(MAX_EXPECTED_MOVE) == MAX_EXPECTED_MOVE)
        for bad, why in ((20, "percent entered as decimal"),
                         (-0.1, "negative"),
                         (1.51, "above bound"),
                         ("abc", "not a number"),
                         (float("nan"), "NaN"),
                         # REGRESSION 2026-08-03: an empty numeric field
                         # arrives from the browser as 0 and used to build a
                         # complete-looking memo on a ±0% forecast, in which
                         # every candidate strike collapsed onto ATM and both
                         # spreads cost exactly 0.
                         (0, "ZERO — degenerate memo"),
                         (0.0, "0.0 — degenerate memo"),
                         (0.0005, "below the degeneracy floor"),
                         ("", "empty string (empty form field)"),
                         (None, "None (field absent)")):
            try:
                validate_expected_move(bad)
                check(f"{bad!r} rejected ({why})", False, "was accepted")
            except ValueError:
                check(f"{bad!r} rejected ({why})", True)

        # ── Watermark ────────────────────────────────────────────────────────
        print("\n── Watermark ──")
        from systems.sarah.trade_intake import (
            EPOCH, get_watermark, set_watermark,
        )
        check("unset watermark reads as epoch", get_watermark() == EPOCH)
        set_watermark("2026-08-03T18:10:26Z")
        check("round-trips in RCS text format, to the second",
              get_watermark() == "2026-08-03T18:10:26Z",
              f"got {get_watermark()}")
        set_watermark("2026-07-01T00:00:00Z")
        check("never moves backwards",
              get_watermark() == "2026-08-03T18:10:26Z")
        set_watermark("2026-08-04T09:00:00Z")
        check("advances forwards", get_watermark() == "2026-08-04T09:00:00Z")

        # ── Underlier map (Class C, reusable) ────────────────────────────────
        print("\n── Underlier map ──")
        from systems.sarah.trade_intake import resolve_ticker
        sarah = P.get_params("sarah")
        check("registry carries underlier_map",
              isinstance(sarah.underlier_map, dict))
        check("intake_poll_minutes present",
              isinstance(sarah.intake_poll_minutes, int))
        check("intake_fire_on_idea present",
              isinstance(sarah.intake_fire_on_idea, bool))
        P.set_params("sarah", {"underlier_map": {"AMDL": "AMD", "gdxu": "GDX"}},
                     note="verify_sarah_intake")
        check("AMDL → AMD", resolve_ticker("AMDL") == "AMD")
        check("case-insensitive both sides", resolve_ticker("gdxu") == "GDX")
        check("unmapped ticker passes through", resolve_ticker("aaoi") == "AAOI")
        try:
            P.set_params("sarah", {"underlier_map": {"AMD": "AMD"}},
                         note="verify: self-map")
            check("self-mapping rejected", False, "was accepted")
        except ValueError:
            check("self-mapping rejected", True)
        try:
            P.set_params("sarah", {"underlier_map": {"AMDL": ""}},
                         note="verify: empty target")
            check("empty target rejected", False, "was accepted")
        except ValueError:
            check("empty target rejected", True)

        # ── Class-A/B derivation (spec §6) ───────────────────────────────────
        print("\n── Derivation (§6) ──")
        from systems.sarah.trade_intake import (
            _dominant_expiry_dte, _max_loss_budget, _sign_from_legs,
        )
        long_call = {"legs": [{"direction": "long", "type": "call",
                               "strike": 150, "contracts": 1,
                               "expiry": "2099-08-07"}],
                     "options_meta": None}
        long_put = {"legs": [{"direction": "long", "type": "put",
                              "contracts": 2, "expiry": "2099-08-07"}],
                    "options_meta": None}
        spread = {"legs": [long_call["legs"][0],
                           {"direction": "short", "type": "call",
                            "contracts": 1, "expiry": "2099-08-07"}],
                  "options_meta": {"strategy_type": "vertical"}}
        check("single long call → +1", _sign_from_legs(long_call) == 1)
        check("single long put → −1", _sign_from_legs(long_put) == -1)
        check("spread → unsigned (Class-C prompt)",
              _sign_from_legs(spread) is None)
        check("no legs → unsigned",
              _sign_from_legs({"legs": [], "options_meta": None}) is None)

        check("budget 1: options_meta.max_loss_dollar ÷ contracts",
              _max_loss_budget({**long_put, "options_meta": {
                  "max_loss_defined": 1, "max_loss_dollar": 500.0}}) == 250.0)
        check("budget 2: thesis.worst_case_dollar ÷ contracts",
              _max_loss_budget({**long_put,
                                "thesis": {"worst_case_dollar": 90.0}}) == 45.0)
        check("budget 3: nothing derivable → Class-C prompt",
              _max_loss_budget(long_call) is None)
        check("max_loss_defined=0 falls through to the thesis",
              _max_loss_budget({**long_call,
                                "options_meta": {"max_loss_defined": 0,
                                                 "max_loss_dollar": 500.0},
                                "thesis": {"worst_case_dollar": 90.0}}) == 90.0)
        # Legs that exist but sum to zero contracts is corrupt data; a
        # fallback divisor of 1 would silently report the WHOLE max loss as
        # the per-contract budget.
        check("legs summing to 0 contracts → prompt, not a wrong number",
              _max_loss_budget({"legs": [{"contracts": 0}],
                                "options_meta": {"max_loss_defined": 1,
                                                 "max_loss_dollar": 500.0}}) is None)
        check("no legs at all still divides by 1 (worst case = position budget)",
              _max_loss_budget({"legs": [], "options_meta": None,
                                "thesis": {"worst_case_dollar": 90.0}}) == 90.0)

        check("single dominant expiry → DTE default",
              _dominant_expiry_dte(long_call) > 0)
        check("mixed expiries → no default",
              _dominant_expiry_dte({"legs": [
                  {"expiry": "2099-08-07"}, {"expiry": "2099-09-07"}]}) is None)

        # ── Row merge: the user's belief survives re-intake ──────────────────
        print("\n── Intake row merge ──")
        from systems.sarah.trade_intake import (
            get_trade_inputs, list_trade_inputs, needs_user, record_error,
            update_user_inputs, upsert_from_rcs,
        )
        ULID = "01TESTTESTTESTTESTTESTTEST"
        prefills = {"expected_move_sign": 1, "thesis_days": 4,
                    "catalyst_type": "event_specific", "max_loss_budget": 90.0}
        row = upsert_from_rcs(ULID, "AAOI", "AAOI", prefills)
        check("row created with pre-fills, expected_move NULL",
              row["expected_move"] is None and row["thesis_days"] == 4
              and row["source"] == "rcs_intake")
        check("needs_user is exactly ['expected_move']",
              needs_user(row) == ["expected_move"], f"got {needs_user(row)}")

        row = update_user_inputs(ULID, {"expected_move": 0.20})
        check("PUT stores the belief and flips provenance to 'user'",
              row["expected_move"] == 0.20 and row["source"] == "user")
        check("nothing blocks the memo now", needs_user(row) == [])
        check("expected_move is NOT recorded as an override (RCS never owns it)",
              "expected_move" not in row["user_overrides"])

        # ── Re-pull semantics: RCS owns the position, you own the belief ──
        print("\n── Re-pull ──")
        row = upsert_from_rcs(ULID, "AAOI", "AAOI",
                              {**prefills, "thesis_days": 9,
                               "max_loss_budget": 135.0})
        check("re-pull NEVER touches expected_move", row["expected_move"] == 0.20)
        check("re-pull REFRESHES a stale Class-B field (90 → 135)",
              row["max_loss_budget"] == 135.0, f"got {row['max_loss_budget']}")
        check("re-pull refreshes a stale derived horizon (4 → 9)",
              row["thesis_days"] == 9, f"got {row['thesis_days']}")
        check("re-pull keeps a user-owned row labelled 'user'",
              row["source"] == "user")
        check("re-pull stamps rcs_synced_at", row["rcs_synced_at"] is not None)

        row = update_user_inputs(ULID, {"thesis_days": 21})
        check("an explicit PUT records the field as YOUR override",
              row["user_overrides"] == ["thesis_days"], f"got {row['user_overrides']}")
        row = upsert_from_rcs(ULID, "AAOI", "AAOI",
                              {**prefills, "thesis_days": 9})
        check("re-pull does NOT revert a field you overrode",
              row["thesis_days"] == 21, f"got {row['thesis_days']}")
        check("…while still refreshing the fields you did not",
              row["max_loss_budget"] == prefills["max_loss_budget"])

        row = update_user_inputs(ULID, {"thesis_days": None})
        check("nulling a field releases the override back to RCS",
              row["user_overrides"] == [], f"got {row['user_overrides']}")
        row = upsert_from_rcs(ULID, "AAOI", "AAOI",
                              {**prefills, "thesis_days": 9})
        check("…and the next re-pull owns it again", row["thesis_days"] == 9)

        row = upsert_from_rcs(ULID, "AAOI", "AAOI",
                              {"expected_move_sign": None, "thesis_days": None,
                               "catalyst_type": None, "max_loss_budget": None})
        check("a derivation that comes back empty never BLANKS stored values",
              row["thesis_days"] == 9 and row["catalyst_type"] == "event_specific",
              f"got days={row['thesis_days']} cat={row['catalyst_type']}")

        row = upsert_from_rcs(ULID, "AMD", "AMDL", prefills)
        check("ticker/rcs_instrument always refreshed (map may have changed)",
              row["ticker"] == "AMD" and row["rcs_instrument"] == "AMDL")

        record_error(ULID, "no vol data for AMD — chain pull failed")
        row = get_trade_inputs(ULID)
        check("a failed vol pull surfaces 'underlier' as the blocking item",
              needs_user(row)[0] == "underlier", f"got {needs_user(row)}")
        record_error(ULID, None)
        check("clearing the error clears the block",
              needs_user(get_trade_inputs(ULID)) == [])
        check("list_trade_inputs returns the row",
              any(r["rcs_trade_ulid"] == ULID for r in list_trade_inputs()))
        try:
            update_user_inputs("NO_SUCH_TRADE", {"expected_move": 0.1})
            check("PUT on an unknown trade raises", False, "no raise")
        except KeyError:
            check("PUT on an unknown trade raises", True)

        # ── Job args plumbing (spec §7 items 2–3) ────────────────────────────
        print("\n── Job args ──")
        import json

        from systems.orchestration.jobs import JOB_SPECS
        from systems.orchestration.run_job import _job_args
        check("sarah_daily_vol timeout raised to 3600s for batches",
              JOB_SPECS["sarah_daily_vol"]["timeout_s"] == 3600)
        os.environ["JOB_ARGS_JSON"] = json.dumps(
            {"tickers": ["AAOI"], "source": "rcs_intake"})
        check("JOB_ARGS_JSON parsed", _job_args()["tickers"] == ["AAOI"])
        os.environ["JOB_ARGS_JSON"] = "{not json"
        check("malformed JOB_ARGS_JSON degrades to {}", _job_args() == {})
        os.environ.pop("JOB_ARGS_JSON")
        check("absent JOB_ARGS_JSON → daily mode", _job_args() == {})

        from systems.sarah.daily_vol_run import run_daily_vol
        try:
            run_daily_vol(tickers=[])
            check("empty ticker batch refused", False, "no raise")
        except AssertionError:
            check("empty ticker batch refused", True)

        # ── BL density: the reliability band must be TWO-SIDED ───────────────
        print("\n── BL density quality gate ──")
        import numpy as np
        import pandas as pd

        from systems.sarah.pretrade_dashboard import (
            BL_MASS_MAX, BL_MASS_MIN, bl_mass_quality,
            breeden_litzenberger_density,
        )
        check("band has an upper bound at all", BL_MASS_MAX is not None)
        check("band brackets 1.0", BL_MASS_MIN < 1.0 < BL_MASS_MAX)
        check("a clean density (mass 1.0) is reliable",
              bl_mass_quality(1.0) == (True, None))
        for mass in (0.5, 0.84):
            ok, note = bl_mass_quality(mass)
            check(f"mass {mass} flagged unreliable (too sparse)",
                  ok is False and note is not None and "UNDERSTATE" in note)
        # REGRESSION 2026-08-03: the gate was one-sided (`>= 0.85`), so AAOI's
        # 4-DTE density integrating to 13.71 was reported `reliable: true`.
        for mass in (1.16, 13.7058, 100.0):
            ok, note = bl_mass_quality(mass)
            check(f"mass {mass} flagged unreliable (noise-amplified)",
                  ok is False and note is not None and "not a probability" in note)
        check("13.71 — the exact AAOI failure — is now caught",
              bl_mass_quality(13.7058)[0] is False)

        # Integration check: a clean Black-Scholes chain must recover a mass
        # inside the band and be reported reliable.
        from systems.utils.pricing import bs_price
        fwd, sigma, dte = 110.0, 0.35, 30
        strikes = np.arange(70.0, 151.0, 1.0)
        # bs_price(flag, S, K, t, r, q, sigma); q=r makes S the forward.
        prices = [bs_price("c", fwd, float(k), dte / 365.0, 0.045, 0.045, sigma)
                  for k in strikes]
        clean = breeden_litzenberger_density(
            pd.DataFrame({"strike": strikes, "option_type": "calls",
                          "bid": prices, "ask": prices}),
            forward=fwd, rate=0.045, dte=dte, d_strike=1.0)
        mass = clean.get("total_mass")
        check("clean BS chain recovers mass ≈ 1", mass is not None
              and BL_MASS_MIN <= mass <= BL_MASS_MAX, f"mass={mass}")
        check("…and is reported reliable with no note",
              clean.get("reliable") is True and clean.get("quality_note") is None)

        # ── RCS side — read-only, live journal ───────────────────────────────
        print("\n── RCS bridge (read-only) ──")
        from systems.risk import rcs_bridge
        if not rcs_bridge.available():
            print("  – RCS journal not present; skipping live checks")
        else:
            acts = rcs_bridge.fetch_trade_activations("1970-01-01T00:00:00Z")
            check("fetch_trade_activations returns activations",
                  len(acts) > 0, "none found")
            check("only 'active' transitions without include_ideas",
                  all(a["new_status"] == "active" for a in acts))
            with_ideas = rcs_bridge.fetch_trade_activations(
                "1970-01-01T00:00:00Z", include_ideas=True)
            check("include_ideas adds 'created' events",
                  len(with_ideas) >= len(acts))
            check("no discarded/closed transitions ever returned",
                  all(a["new_status"] in ("active", "idea") for a in with_ideas))
            if acts:
                newest = max(a["occurred_at"] for a in acts)
                check("watermark filters processed events out",
                      rcs_bridge.fetch_trade_activations(newest) == [])

            # Search — the "I don't know the ULID" path.
            all_open = rcs_bridge.list_trades()
            check("list_trades returns open trades", len(all_open) > 0)
            check("rows carry leg_count (the position-surface precondition)",
                  all("leg_count" in t for t in all_open))
            check("closed/discarded excluded by default",
                  all(t["status"] in ("idea", "active") for t in all_open))
            if all_open:
                t0 = all_open[0]
                check("search by instrument matches",
                      any(t["id"] == t0["id"]
                          for t in rcs_bridge.list_trades(t0["instrument"])))
                check("search is case-insensitive",
                      any(t["id"] == t0["id"]
                          for t in rcs_bridge.list_trades(
                              str(t0["instrument"]).lower())))
                check("search by ULID matches",
                      any(t["id"] == t0["id"]
                          for t in rcs_bridge.list_trades(t0["id"])))
                check("a nonsense query matches nothing",
                      rcs_bridge.list_trades("ZZZQQQNOPE") == [])
            try:
                rcs_bridge._connect().execute(
                    "UPDATE entity_events SET new_status = 'x'")
                check("ADR-003: research.db is NOT writable", False,
                      "A WRITE SUCCEEDED — investigate immediately")
            except Exception:
                check("ADR-003: research.db is NOT writable (mode=ro)", True)

        print(f"\n{'─' * 46}\n{PASS} passed, {FAIL} failed")
        return 0 if FAIL == 0 else 1
    finally:
        config.VOL_DB_PATH = orig_vol_db
        P.invalidate_cache()


if __name__ == "__main__":
    sys.exit(main())
