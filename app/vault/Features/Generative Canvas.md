---
tags: [feature]
aliases: [Canvas, Workspace]
created: 2026-07-27
---
# Generative Canvas

The right-hand pane of the advisor. It is **AI-summoned**: it materialises exactly the UI a question needs — a result card, a chart, a table, a soil profile, or the [[Run Timeline]].

## Widget types
Driven by the [[Agent and Widget Protocol]]: the model emits a *thin* marker, the backend fills a **typed widget envelope**, and the canvas renders it. Kinds include:
- **result card** — a headline number with context
- **chart** — interactive, editable (line / bar / area, series toggles)
- **table** — sortable, titled
- **soil profile** — the field's actual layers ([[Layered Soil Editor]] shows the same data)
- **timeline** — the full [[Run Timeline]]

## Interactivity
Charts and tables are interactive and editable. A widget submission is a two-way loop: it becomes a synthetic message posted to `POST /api/interact`, which re-runs the agent (see [[Agent and Widget Protocol]]).

## Confidence
Every numeric widget carries a required `confidence` field, so honesty is structural rather than a matter of prompting. See [[Reliability and Confidence]].

## Implementation notes
- Frontend: `components/widgets/*` (ChartWidget, TableWidget, …), `Chat.tsx` canvas rendering.
- Backend: `insights_service.build_widgets` fills the envelope from a field catalog; validated with Pydantic (server) + Zod (client).
- A plain chat reply must not wipe an open widget (a fixed persistence bug).

## Related
[[AI Advisor]] · [[Agent and Widget Protocol]] · [[Run Timeline]]
