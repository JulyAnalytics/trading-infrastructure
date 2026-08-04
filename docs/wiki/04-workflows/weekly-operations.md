---
domain: trading-system
stage: wiki
project: v1-workstation
persona: alex
status: active
---

# Workflow — Weekly Operations (the Friday review)

*Compress the week into twenty minutes: what did the environment do, what
did the system produce, what did you actually do, and what needs attention
next week. This is the desk's weekly risk meeting — with yourself.*

## The automated half

Friday at `ops.weekly_review_time` (17:00 default) the scheduler runs the
`weekly_review` job → `reports/weekly/weekly_review_<date>.md` + `.pdf`,
browsable on **Jobs & Health → Weekly reviews**. Sunday evening the
`fred_full` job re-pulls full FRED history (catching data revisions) and
refreshes the macro calendar.

Every review stamps the parameter hashes it was generated under — a review
is reproducible evidence, not a vibe.

## Reading the review, section by section

| Section | Ask yourself |
|---|---|
| **Regime week** | Did the label move? Did *divergences* persist or resolve? A week of `BROAD_COMPONENT_DIVERGENCE` with a stable label = the label is less trustworthy than it looks. |
| **Vol summary** | Which tickers' VRP signal changed category this week? Is the VVIX/VIX ratio drifting toward 6? |
| **Research runs** | GO vs failure-archive count. A week of only NO_GOs is *fine* — it means the gates worked. Zero runs for weeks = the research muscle is idle. |
| **Risk flags** | Every alert in the window: was each one acted on and acked, or did it just scroll by? Repeated approaches to the same limit = calibration conversation. |
| **Journal activity** | Trades opened/closed vs reviews completed. **Open trades with no reviews after closes is the discipline leak** the RCS exists to prevent. |

## The manual half (after reading)

1. **Ack** any un-acked alerts (Jobs & Health) after acting on them.
2. **Journal hygiene** (RCS): complete overdue reviews; sweep stale theses
   — did this week's data fire any kill conditions?
3. **Event library**: if the week contained a genuine vol episode, add it to
   the regime-events YAML (Sarah → Regime library → Edit library YAML) while
   it's fresh — pre-event surface state, what worked, what failed, lessons.
4. **Parameter review** (monthly-ish, not weekly): Parameters → history —
   any edits this month still make sense? Any `guarded` gate changes whose
   justification you'd still defend?
5. **Next week**: Marcus calendar — FOMC/CPI inside your typical holding
   period? Pre-read the [regime context](regime-context.md) if fragility
   ended the week elevated.

## When the review shows a "not available" section

That's the review being honest — the source produced nothing (empty journal,
no research runs) or a component failed. An empty section is information;
a failing component will also have alerted during the week.

## Files & retention

`reports/weekly/` accumulates one md+pdf pair per Friday. They are plain
files — grep-able, and (via the
[Knowledge Library integration](../06-knowledge/ashurbanipal-integration.md))
first-class candidates for the library's corpus, where each week becomes a
citable document.
