---
tags: [devlog, docs]
created: 2026-07-27
---
# 2026-07-27 — Technical report & PDF

Produced a full technical report + walkthrough and a PDF export.

## Deliverables (in `report/`)
- `index.html` + `img/` — editable source
- `AI-SWAT+_Technical_Report.html` — self-contained interactive version (base64 screenshots, light/dark, click-to-zoom, scroll-spy TOC, tabs, accordions)
- `AI-SWAT+_Technical_Report.pdf` — 25-page print export

## Contents
Overview · system architecture (+ diagram, request lifecycle) · **Technical detail** (backend services, API surface, agent & widget protocol, data model, key algorithms) · a **7-step annotated UX walkthrough** (numbered pins overlaid on real screenshots) · feature reference · a real 5-year results table · reliability · engineering hardening · editor file map · stack.

## How
- Screenshots captured with **puppeteer-core** driving system Chrome (no browser download) at 2× on the demo field [[Demo Field - North Field]].
- PDF generated via headless Chrome `page.pdf()`; a permanent `@media print` stylesheet flows content to fill pages, keeps images/captions/legends whole, flows tables row-by-row, and labels the stacked architecture tabs.

## Related
[[Demo Field - North Field]] · [[AI-SWAT+ Overview]]
