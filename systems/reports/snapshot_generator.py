"""
Snapshot Generator
Standalone module — no Dash dependency. Callable from dashboard button,
nightly scheduler, or command line.
"""
import os
import sys
import tempfile
import logging
from datetime import datetime

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..'))

import plotly.graph_objects as go
from reportlab.lib.pagesizes import A4, landscape
from reportlab.platypus import SimpleDocTemplate, Image, Paragraph, Spacer, Table
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors

logger = logging.getLogger(__name__)


def generate_snapshot(
    output_path: str | None = None,
    return_bytes: bool = False,
) -> str | bytes:
    """
    Generate a macro regime snapshot PDF.

    Args:
        output_path: Save path. Auto-names to data/snapshots/macro_YYYY-MM-DD_HHMMSS.pdf
        return_bytes: If True, return PDF as bytes (for dcc.Download).

    Returns:
        output_path string, or PDF bytes if return_bytes=True.
    """
    from systems.signals.regime_classifier import RegimeClassifier
    from systems.dashboard.macro_dashboard import (
        build_component_scores_chart,
        build_regime_history_chart,
        get_regime_history_df,
        get_regime_persistence_stats,
        get_days_in_current_regime,
        render_chart_png,
    )
    from systems.utils.db import get_connection

    conn = get_connection()

    # ── Gather data with explicit None guards ───────────────────────────────
    result = RegimeClassifier().classify(persist=False)

    try:
        current_days = get_days_in_current_regime()
    except Exception as e:
        logger.warning(f"Snapshot: could not get days_in_current_regime: {e}")
        current_days = None

    try:
        persistence = get_regime_persistence_stats(result.regime)
    except Exception as e:
        logger.warning(f"Snapshot: could not get persistence stats: {e}")
        persistence = {"n_episodes": 0, "median_days": None}

    try:
        calendar_df = conn.execute("""
            SELECT event_name, event_date, component
            FROM macro_calendar
            WHERE event_date >= current_date
            ORDER BY event_date
            LIMIT 5
        """).df()
    except Exception as e:
        logger.warning(f"Snapshot: could not load calendar: {e}")
        calendar_df = None

    try:
        attr = result.attribution()
    except Exception as e:
        logger.warning(f"Snapshot: attribution() failed: {e}")
        attr = {}

    conn.close()

    # ── Render charts to temp PNGs ──────────────────────────────────────────
    tmpdir = tempfile.mkdtemp()
    chart_paths = {}

    history_df = get_regime_history_df()

    for name, fig in [
        ("components", build_component_scores_chart(result, history_df)),
        ("history",    build_regime_history_chart()),
    ]:
        path = os.path.join(tmpdir, f"{name}.png")
        try:
            render_chart_png(fig, path, width=600, height=280)
            chart_paths[name] = path
        except Exception as e:
            logger.warning(f"Snapshot: chart render failed for {name}: {e}")

    # ── Build PDF ───────────────────────────────────────────────────────────
    if output_path is None:
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        os.makedirs("data/snapshots", exist_ok=True)
        output_path = f"data/snapshots/macro_{ts}.pdf"

    _build_pdf(output_path, result, calendar_df, persistence, current_days,
               attr, chart_paths)

    # ── Cleanup ─────────────────────────────────────────────────────────────
    for p in chart_paths.values():
        try:
            os.remove(p)
        except Exception:
            pass
    try:
        os.rmdir(tmpdir)
    except Exception:
        pass

    if return_bytes:
        with open(output_path, "rb") as f:
            return f.read()

    return output_path


def _build_pdf(output_path, result, calendar_df, persistence,
               current_days, attr, chart_paths):
    """Assemble reportlab PDF. Each section degrades gracefully if its data is None."""
    from config import REGIME_COLORS

    doc = SimpleDocTemplate(output_path, pagesize=landscape(A4),
                            leftMargin=1.5*cm, rightMargin=1.5*cm,
                            topMargin=1.5*cm, bottomMargin=1.5*cm)

    styles = getSampleStyleSheet()

    regime_hex = REGIME_COLORS.get(result.regime, "#999999")
    regime_color_rl = colors.HexColor(regime_hex)

    story = []

    # ── Header ────────────────────────────────────────────────────────────────
    header_style = ParagraphStyle(
        "header", fontSize=22, fontName="Helvetica-Bold",
        textColor=regime_color_rl, spaceAfter=4
    )
    story.append(Paragraph(result.regime, header_style))
    story.append(Paragraph(
        f"Score: {result.composite_score:+.2f}  |  "
        f"Confidence: {result.confidence}  |  "
        f"As of: {result.as_of}  |  "
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        styles["Normal"]
    ))
    story.append(Spacer(1, 0.4*cm))

    # ── Component scores chart ────────────────────────────────────────────────
    if "components" in chart_paths:
        story.append(Image(chart_paths["components"], width=24*cm, height=7*cm))
    else:
        story.append(Paragraph("[Component scores chart unavailable]", styles["Normal"]))
    story.append(Spacer(1, 0.3*cm))

    # ── Regime history chart ──────────────────────────────────────────────────
    if "history" in chart_paths:
        story.append(Image(chart_paths["history"], width=24*cm, height=7*cm))
    else:
        story.append(Paragraph("[Regime history chart unavailable]", styles["Normal"]))
    story.append(Spacer(1, 0.3*cm))

    # ── Persistence + Calendar (side by side) ─────────────────────────────────
    left_content = []

    if persistence.get("median_days") and current_days is not None:
        left_content.append(Paragraph(
            f"<b>Regime Persistence</b>: Day {current_days} of current regime",
            styles["Normal"]
        ))
        left_content.append(Paragraph(
            f"Median: {persistence['median_days']}d | "
            f"Range: {persistence['min_days']}-{persistence['max_days']}d | "
            f"N={persistence['n_episodes']} episodes",
            styles["Normal"]
        ))
    else:
        left_content.append(Paragraph("Persistence data unavailable", styles["Normal"]))

    right_content = []
    if calendar_df is not None and not calendar_df.empty:
        right_content.append(Paragraph("<b>Upcoming Catalysts</b>", styles["Normal"]))
        for _, ev in calendar_df.iterrows():
            days_away = (ev["event_date"] - datetime.now().date()).days
            comp = ev["component"] if ev["component"] else "multi-component"
            right_content.append(Paragraph(
                f"{ev['event_name']}  +{days_away}d  [{comp}]",
                styles["Normal"]
            ))
    else:
        right_content.append(Paragraph("Calendar data unavailable", styles["Normal"]))

    table_data = [[left_content, right_content]]
    t = Table(table_data, colWidths=[12*cm, 12*cm])
    story.append(t)

    # ── Attribution summary ───────────────────────────────────────────────────
    if attr and isinstance(attr, dict):
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("<b>Attribution</b>", styles["Normal"]))

        drivers = attr.get("drivers", {})
        contradictors = attr.get("contradictors", {})
        nearest = attr.get("nearest_regime", "")

        if drivers:
            story.append(Paragraph("Drivers:", styles["Normal"]))
            for name, data in list(drivers.items())[:4]:
                story.append(Paragraph(
                    f"  {name}:  score {data['score']:+.2f}  weight {data['weight']:.0%}  "
                    f"contrib {data['contribution']:+.4f}",
                    styles["Normal"]
                ))

        if contradictors:
            story.append(Paragraph("Contradictors:", styles["Normal"]))
            for name, data in list(contradictors.items())[:3]:
                story.append(Paragraph(
                    f"  {name}:  score {data['score']:+.2f}  weight {data['weight']:.0%}  "
                    f"contrib {data['contribution']:+.4f}",
                    styles["Normal"]
                ))

        if nearest:
            story.append(Paragraph(f"Nearest regime: {nearest.replace('_', ' ')}",
                                   styles["Normal"]))

    # ── Footer ────────────────────────────────────────────────────────────────
    story.append(Spacer(1, 0.3*cm))
    story.append(Paragraph(
        "Internal use only  .  Macro Regime Dashboard  .  Phase 4 Snapshot",
        ParagraphStyle("footer", fontSize=7, textColor=colors.HexColor("#555555"))
    ))

    doc.build(story)
