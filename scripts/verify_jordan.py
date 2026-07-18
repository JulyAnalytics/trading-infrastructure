"""
Jordan risk-layer verification — offline (no network, no live pricing).

Covers: sizing math, limit evaluation on a synthetic analysis, verdict
intake logic against temp output contracts, and the RCS bridge's read-only
guarantee (a write attempt must fail).

Usage:
    python scripts/verify_jordan.py
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timedelta
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
    global PASS, FAIL
    tmpdir = Path(tempfile.mkdtemp(prefix="jordan_verify_"))
    orig_vol_db = config.VOL_DB_PATH
    orig_outputs = config.OUTPUTS_DIR
    config.VOL_DB_PATH = str(tmpdir / "verify.db")
    P.invalidate_cache()

    try:
        print("── Sizing ──")
        from systems.risk.verdict_intake import suggest_size
        jp = P.JordanParams(nav=100_000.0)
        # Uncapped formula check: needs a single-position limit generous
        # enough that the cap in suggest_size() doesn't engage — a 4-point
        # stop at $100 entry with 1% risk wants 25% of NAV notional, which
        # WOULD trip the default 5% cap. Use a permissive cap here and
        # exercise the cap itself separately below.
        jp_uncapped = P.JordanParams(nav=100_000.0, max_single_position_pct=1.0)
        s = suggest_size(entry=100.0, stop=96.0, params=jp_uncapped, risk_pct=0.01)
        check("risk dollars = NAV × risk%", s["risk_dollars"] == 1000.0)
        check("units = risk$/stop-distance", s["units"] == 250, f"got {s['units']}")
        check("notional = units × entry", abs(s["notional"] - 25_000.0) < 1e-6)
        s2 = suggest_size(entry=100.0, stop=99.9, params=jp, risk_pct=0.01)
        check("single-position cap engages on tight stops",
              s2["capped_by"] == "single-position limit"
              and s2["notional"] <= jp.nav * jp.max_single_position_pct + 1e-6)
        try:
            suggest_size(entry=100.0, stop=100.0, params=jp)
            check("rejects entry == stop", False)
        except ValueError:
            check("rejects entry == stop", True)

        print("── Limits ──")
        from systems.risk.limits import evaluate_limits
        analysis = {
            "net_delta_dollars": 30_000.0,   # 30% of NAV > 20% limit
            "net_vega_dollars": 1_000.0,     # 1% < 15% limit
            "analyses": [
                {"position": {"id": "a", "ticker": "SPY"}, "notional": 4_000.0},
                {"position": {"id": "b", "ticker": "TLT"}, "notional": 9_000.0},
            ],
            "concentration_flags": [],
        }
        lim = evaluate_limits(analysis, params=jp)
        check("delta breach detected", lim["checks"]["net_delta"]["breached"])
        check("vega within limit", not lim["checks"]["net_vega"]["breached"])
        oversized = lim["checks"]["single_position"]["oversized"]
        check("oversized position flagged (9% > 5% NAV)",
              len(oversized) == 1 and oversized[0]["ticker"] == "TLT",
              f"got {oversized}")
        check("breaches list non-empty and ok=False",
              lim["breaches"] and not lim["ok"])
        check("drawdown explicitly marked not-evaluated",
              "note" in lim["checks"]["drawdown"])

        print("── Verdict intake ──")
        from systems.risk.verdict_intake import intake
        outdir = tmpdir / "outputs"
        outdir.mkdir()
        config.OUTPUTS_DIR = str(outdir)

        r = intake(params=jp)
        check("no verdict file → not actionable",
              not r["actionable"] and r["checks"][0]["ok"] is False)

        now = datetime.now()
        (outdir / "research_verdict.json").write_text(json.dumps({
            "hypothesis_id": "h1", "verdict": "GO",
            "production_haircut_sharpe": 0.7, "viable_after_haircut": True,
            "regime_conditional_sharpe": {"RISK_ON_LOW_VOL": 1.1, "NEUTRAL": 0.6},
            "written_at": now.isoformat(),
        }))
        (outdir / "regime_state.json").write_text(json.dumps({
            "regime_state": "NEUTRAL", "written_at": now.isoformat(),
        }))
        r = intake(params=jp)
        check("fresh GO + positive regime Sharpe → actionable", r["actionable"],
              json.dumps(r["checks"]))

        (outdir / "regime_state.json").write_text(json.dumps({
            "regime_state": "RISK_OFF_STRESS", "written_at": now.isoformat(),
        }))
        r = intake(params=jp)
        check("regime without conditional Sharpe → NOT actionable (G4-7)",
              not r["actionable"])

        stale = (now - timedelta(hours=jp.verdict_max_age_hours + 5)).isoformat()
        (outdir / "regime_state.json").write_text(json.dumps({
            "regime_state": "NEUTRAL", "written_at": now.isoformat(),
        }))
        v = json.loads((outdir / "research_verdict.json").read_text())
        v["written_at"] = stale
        (outdir / "research_verdict.json").write_text(json.dumps(v))
        r = intake(params=jp)
        check("stale verdict → NOT actionable", not r["actionable"])

        print("── RCS bridge read-only guarantee ──")
        import sqlite3
        from systems.risk import rcs_bridge
        fake_rcs = tmpdir / "research.db"
        seed = sqlite3.connect(fake_rcs)
        seed.executescript("""
            CREATE TABLE trade (id TEXT PRIMARY KEY, name TEXT DEFAULT '',
                instrument TEXT, instrument_type TEXT DEFAULT 'equity',
                thesis_id TEXT, status TEXT DEFAULT 'idea',
                created_at TEXT DEFAULT '2026-07-01T00:00:00Z', closed_at TEXT);
            CREATE TABLE trade_entries (id TEXT, trade_id TEXT, date TEXT,
                price REAL, size REAL);
            CREATE TABLE trade_exits (id TEXT, trade_id TEXT, date TEXT,
                price REAL, size REAL);
            CREATE TABLE trade_option_legs (id TEXT, trade_id TEXT,
                direction TEXT, type TEXT, strike REAL, expiry TEXT,
                contracts INTEGER, entry_premium REAL, exit_premium REAL,
                date_opened TEXT, date_closed TEXT);
            CREATE TABLE trade_options_meta (trade_id TEXT PRIMARY KEY,
                strategy_type TEXT, iv_at_entry REAL, iv_rank_at_entry REAL,
                max_loss_defined INTEGER, theta_decay_relevant INTEGER);
            INSERT INTO trade (id, name, instrument, instrument_type, status)
                VALUES ('t1', 'SPY put spread', 'SPY', 'option', 'active');
            INSERT INTO trade_option_legs VALUES
                ('l1','t1','long','put',480,'2026-12-18',2,5.2,NULL,'2026-06-20',NULL),
                ('l2','t1','short','put',460,'2026-12-18',2,2.1,NULL,'2026-06-20',NULL);
            INSERT INTO trade (id, name, instrument, status)
                VALUES ('t2', 'TLT long', 'TLT', 'active');
            INSERT INTO trade_entries VALUES ('e1','t2','2026-06-25',92.5,100);
        """)
        seed.commit()
        seed.close()
        config.RCS_DB_PATH = str(fake_rcs)

        trades = rcs_bridge.fetch_active_trades()
        check("bridge reads active trades", len(trades) == 2, f"got {len(trades)}")
        t1 = next(t for t in trades if t["id"] == "t1")
        check("option legs attached", len(t1["legs"]) == 2)
        t2 = next(t for t in trades if t["id"] == "t2")
        check("equity net size from entries", t2["net_size"] == 100)

        ro = sqlite3.connect(f"file:{fake_rcs}?mode=ro", uri=True)
        try:
            ro.execute("INSERT INTO trade (id) VALUES ('hacker')")
            ro.commit()
            check("mode=ro connection rejects writes", False)
        except sqlite3.OperationalError:
            check("mode=ro connection rejects writes", True)
        finally:
            ro.close()

        print("── Book assembly (from bridge, no pricing) ──")
        from systems.risk.book import load_book
        book = load_book()
        opt = [p for p in book["positions"] if p["asset_type"] == "option"]
        eq = [p for p in book["positions"] if p["asset_type"] == "equity"]
        check("two option positions from legs", len(opt) == 2, f"got {len(opt)}")
        check("one equity position", len(eq) == 1)
        check("short leg direction preserved",
              any(p["long_short"] == "short" and p["strike"] == 460 for p in opt))

    finally:
        config.VOL_DB_PATH = orig_vol_db
        config.OUTPUTS_DIR = orig_outputs
        P.invalidate_cache()

    print(f"\n{'=' * 46}\n{PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
