# ADR-001 — GUI stack: FastAPI + React (not Dash, not Streamlit)

**Date:** 2026-07-06 · **Status:** accepted (user decision)

## Context
v1.0 is GUI-first with granular parameter control. Candidates: extend the
existing Dash app; a Streamlit workbench (matches the RCS-era journal spec);
or FastAPI + React.

## Decision
FastAPI service layer on :8100 + React (Vite/TS, react-plotly.js) frontend.
Charts are built server-side as Plotly figure JSON so existing Python
figure-building knowledge carries over and the client stays thin.

## Consequences
- A Node/TS toolchain enters a pure-Python repo — isolated under `frontend/`.
- The Dash app at :8050 is retired once the Marcus workspace reaches parity;
  its classify-on-page-refresh DB write disappears with it.
- The API layer becomes the single integration surface for the registry,
  jobs, engines, and (Phase 5) the RCS bridge.
- Request/response bodies are plain dicts (no pydantic request models) to
  stay compatible with whichever pydantic major version mlflow pins.
