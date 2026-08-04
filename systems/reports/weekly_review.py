"""
Alex's weekly review generator (Phase 6, build-sequence template).

Assembles: regime week · vol summary · research runs (MLflow) · risk flags
(limits + alert feed) · RCS journal activity — to markdown + PDF in
reports/weekly/. Every section degrades to a "not available" note rather
than failing the whole review; the review's job is to show the week as it
is, including which parts of the system produced nothing.

Run via the job system:  POST /api/jobs {"name": "weekly_review"}
(scheduled Fridays at OpsParams.weekly_review_time by scheduler v2).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

from loguru import logger

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OUT_DIR = REPO_ROOT / "reports" / "weekly"


# ── Section collectors (each returns (title, lines, table|None)) ────────────

def _regime_week() -> dict:
    from config import DUCKDB_PATH, OUTPUTS_DIR
    from systems.utils.db import get_connection
    out = {"title": "Regime week (Marcus)", "lines": [], "rows": [],
           "header": ["date", "regime", "composite"]}
    try:
        state = json.loads((Path(OUTPUTS_DIR) / "regime_state.json").read_text())
        out["lines"].append(
            f"Current: **{state.get('regime_state')}** "
            f"(composite {state.get('composite_score')}, "
            f"confidence {state.get('confidence')}, as of {state.get('as_of')})")
        if state.get("divergence_type"):
            out["lines"].append(f"Divergence flagged: {state['divergence_type']}")
    except Exception:
        out["lines"].append("regime_state.json unavailable.")
    try:
        conn = get_connection(str(REPO_ROOT / DUCKDB_PATH))
        try:
            rows = conn.execute("""
                SELECT date, regime, round(composite_score, 3)
                FROM regime_history
                WHERE date >= current_date - INTERVAL 7 DAY
                ORDER BY date
            """).fetchall()
        finally:
            conn.close()
        out["rows"] = [[str(r[0])[:10], r[1], r[2]] for r in rows]
        if not rows:
            out["lines"].append("No regime_history rows this week.")
    except Exception as e:
        out["lines"].append(f"regime_history unavailable: {e}")
    return out


def _vol_summary() -> dict:
    from config import VOL_DB_PATH
    from systems.utils.db import get_connection
    out = {"title": "Vol summary (Sarah)", "lines": [], "rows": [],
           "header": ["ticker", "ATM IV 30d", "IV rank", "VRP signal",
                      "TS shape", "25Δ RR"]}
    try:
        conn = get_connection(str(REPO_ROOT / VOL_DB_PATH))
        try:
            rows = conn.execute("""
                SELECT v.ticker, round(v.atm_iv_30d,1), round(v.iv_rank,2),
                       v.vrp_proxy_signal, v.ts_shape, round(v.skew_25d_rr,2)
                FROM vol_signals v
                JOIN (SELECT ticker t, max(date) d FROM vol_signals
                      GROUP BY ticker) m ON v.ticker=m.t AND v.date=m.d
                ORDER BY v.ticker
            """).fetchall()
            vv = conn.execute(
                "SELECT date, vvix, vvix_vix_ratio FROM vvix_daily "
                "ORDER BY date DESC LIMIT 1").fetchone()
        finally:
            conn.close()
        # DuckDB FLOAT (float32) survives SQL round() with repr noise —
        # normalise in Python for the report.
        out["rows"] = [
            [c if not isinstance(c, float) else round(float(c), 2) for c in r]
            for r in rows
        ]
        if vv:
            out["lines"].append(
                f"VVIX {vv[1]:.1f} (VVIX/VIX ratio "
                f"{vv[2]:.1f} — typical 3.5–6.0) as of {str(vv[0])[:10]}.")
        if not rows:
            out["lines"].append("No vol_signals — has the daily run executed?")
    except Exception as e:
        out["lines"].append(f"vol data unavailable: {e}")
    return out


def _research_runs(days: int = 7) -> dict:
    out = {"title": "Research runs (Priya / MLflow)", "lines": [], "rows": [],
           "header": ["run", "verdict", "DSR", "prod SR", "logged"]}
    try:
        from systems.backtest.experiment_tracker import ResearchTracker
        cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
        runs = [r for r in ResearchTracker().list_runs(max_results=100)
                if (r.get("logged_at") or "") >= cutoff]
        out["rows"] = [[r["run_name"], r["verdict"],
                        round(r["dsr_primary"], 3) if r.get("dsr_primary") is not None else "—",
                        round(r["production_sr"], 2) if r.get("production_sr") is not None else "—",
                        str(r.get("logged_at"))[:16]] for r in runs]
        n_go = sum(1 for r in runs if r["verdict"] == "GO")
        out["lines"].append(
            f"{len(runs)} run(s) this week — {n_go} GO, "
            f"{len(runs) - n_go} NO_GO (failure archive).")
    except Exception as e:
        out["lines"].append(f"MLflow unavailable: {e}")
    return out


def _risk_flags(days: int = 7) -> dict:
    out = {"title": "Risk flags (Jordan)", "lines": [], "rows": [],
           "header": ["when", "source", "severity", "message"]}
    try:
        from systems.orchestration.alerts import list_alerts
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        alerts = [a for a in list_alerts(limit=100)
                  if a["created_at"] >= cutoff]
        out["rows"] = [[a["created_at"][:16], a["source"], a["severity"],
                        a["message"][:90]] for a in alerts]
        out["lines"].append(f"{len(alerts)} alert(s) in the window.")
    except Exception as e:
        out["lines"].append(f"alert feed unavailable: {e}")
    try:
        from systems.risk.book import load_book
        book = load_book()
        out["lines"].append(
            f"Book: {book['counts']['rcs']} RCS + "
            f"{book['counts']['manual']} manual position(s); "
            f"RCS bridge available={book['rcs'].get('available')}. "
            "Drawdown check still awaits a NAV history (see audit #5).")
    except Exception as e:
        out["lines"].append(f"book unavailable: {e}")
    return out


def _rcs_activity(days: int = 7) -> dict:
    out = {"title": "Journal activity (RCS)", "lines": [], "rows": [],
           "header": []}
    try:
        from systems.risk.rcs_bridge import weekly_activity
        act = weekly_activity(days=days)
        if not act.get("available"):
            out["lines"].append(f"RCS unavailable: {act.get('reason')}")
        else:
            out["lines"].append(
                f"Trades opened {act.get('trades_opened')}, closed "
                f"{act.get('trades_closed')}, active now "
                f"{act.get('trades_active_now')}. Reviews completed "
                f"{act.get('reviews_completed')}, observations "
                f"{act.get('observations_captured')}, theses updated "
                f"{act.get('theses_updated')}.")
    except Exception as e:
        out["lines"].append(f"RCS bridge failed: {e}")
    return out


# ── Renderers ────────────────────────────────────────────────────────────────

def _to_markdown(sections: list, as_of: str, hashes: dict) -> str:
    md = [f"# Weekly Review — week ending {as_of}",
          f"*Generated {datetime.now().isoformat(timespec='seconds')} · "
          f"parameter hashes: "
          f"{', '.join(f'{k}:{v[:6]}' for k, v in hashes.items()) or 'n/a'}*",
          ""]
    for s in sections:
        md.append(f"## {s['title']}")
        md.extend(s["lines"])
        if s["rows"]:
            md.append("")
            md.append("| " + " | ".join(s["header"]) + " |")
            md.append("|" + "---|" * len(s["header"]))
            for row in s["rows"]:
                md.append("| " + " | ".join(str(c) for c in row) + " |")
        md.append("")
    return "\n".join(md)


def _to_pdf(sections: list, as_of: str, path: Path) -> None:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
    )
    styles = getSampleStyleSheet()
    story = [Paragraph(f"Weekly Review — week ending {as_of}",
                       styles["Title"]), Spacer(1, 8)]
    for s in sections:
        story.append(Paragraph(s["title"], styles["Heading2"]))
        for line in s["lines"]:
            story.append(Paragraph(line.replace("**", ""), styles["BodyText"]))
        if s["rows"]:
            data = [s["header"]] + [[str(c) for c in r] for r in s["rows"]]
            t = Table(data, hAlign="LEFT")
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1a1a2e")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 7.5),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ]))
            story.append(t)
        story.append(Spacer(1, 10))
    SimpleDocTemplate(str(path), pagesize=A4).build(story)


def generate_weekly_review() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    as_of = datetime.now().strftime("%Y-%m-%d")
    try:
        from systems.params import all_active_hashes
        hashes = all_active_hashes()
    except Exception:
        hashes = {}

    sections = [_regime_week(), _vol_summary(), _research_runs(),
                _risk_flags(), _rcs_activity()]

    md_path = OUT_DIR / f"weekly_review_{as_of}.md"
    md_path.write_text(_to_markdown(sections, as_of, hashes))

    pdf_path = OUT_DIR / f"weekly_review_{as_of}.pdf"
    try:
        _to_pdf(sections, as_of, pdf_path)
    except Exception as e:
        logger.warning(f"PDF render failed ({e}) — markdown still written")
        pdf_path = None

    logger.info(f"weekly review written: {md_path}")
    return {"markdown": str(md_path),
            "pdf": str(pdf_path) if pdf_path else None}
