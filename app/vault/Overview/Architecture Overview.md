---
tags: [architecture, overview]
aliases: [Architecture]
created: 2026-07-27
---
# Architecture Overview

AI-SWAT+ is a **three-tier** system: a TypeScript front end, a FastAPI/LangGraph back end, and the compiled SWAT+ engine driven on isolated per-run workspaces.

```
[ FRONTEND ]            [ BACKEND · :8020 ]           [ ENGINE ]
React · Vite · TS  <-->  FastAPI + LangGraph    <-->   SWAT+ rev-62
Chat + AI canvas         ReAct advisor agent           pySWATPlus driver
SWAT+ Editor             build · weather · soil        isolated run workspace
Recharts                 management · timeline
                         editor · confidence
                         SQLite · farms & runs
                              |
                        [ DATA SOURCES ]
                        gSSURGO · gridMET · USGS
```

## Tiers
- **[[Frontend]]** — a chat-native SPA; the chat panel drives an AI-summoned [[Generative Canvas]]; a separate [[SWAT+ Editor]] route edits files. Also packaged as an Electron desktop app.
- **[[Backend Services]]** — FastAPI on `127.0.0.1:8020`, hosting the LangGraph agent and domain services; SQLite for state. See [[API Reference]] and [[Data Model]].
- **[[SWAT+ Engine Integration]]** — SWAT+ rev-62 via pySWATPlus; every run executes in an isolated copy of the field's `TxtInOut`.

## Request lifecycle (a question → an answer)
1. **UI** — the farmer types a question.
2. **Agent** — the ReAct agent plans and calls data/analysis tools.
3. **Services** — services read the field's inputs and the latest run's outputs.
4. **Widgets** — results become typed widgets (cards, charts, tables, timeline).
5. **UI** — the answer + canvas render together, with a confidence badge.

See [[Agent and Widget Protocol]] for the full round-trip.

## Data grounding
Inputs are real public datasets pulled for the field's coordinates: [[gSSURGO Soil]], [[gridMET Weather]], and USGS gauges/elevation for calibration (see [[People and Provenance]]).

## Related
[[AI-SWAT+ Overview]] · [[Backend Services]] · [[Tech Stack]] · [[Backend Launch]]
