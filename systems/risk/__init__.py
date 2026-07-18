"""
Jordan — risk layer (v1.0 Phase 5).

Positions come from the Research Capture System (read-only bridge) plus
manual entries in trading.db; greeks aggregate through Sarah's GreeksTool;
limits live in the parameter registry (JordanParams); stress reuses the
scenario engine; verdict intake enforces freshness + regime checks on
Priya's research_verdict.json (closes audit gap G4-7 on the consumer side).
"""
