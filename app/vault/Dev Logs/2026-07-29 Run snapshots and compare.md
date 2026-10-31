---
tags: [devlog, feature, runs]
created: 2026-07-29
---
# 2026-07-29 — Run snapshots and compare

Turned the existing run history into named, comparable **scenarios**. Feature reference: [[Run Snapshots and Compare]].

## Why

Every run was already persisted (a `simulations` row + `data/outputs/{run_id}`) but there was no way to name one, repeat it, or put two side by side. Since single-field output is [[Reliability and Confidence|directional rather than absolute]], **comparison is the honest way to use the model** — so this is a core capability, not a nicety.

## Built

**Backend** — `list_for_farm` now returns `label`/`scenario`/`begin_date`/`end_date`; new `set_label()` + `POST /api/swat/runs/{id}/label` (label stored in the run's `parameters` JSON, so no schema change).

**Frontend** — `RunSnapshots.tsx` (list, inline rename, multi-select) and `RunCompare.tsx` (metric table with best-per-row bold and % change, honouring lower-is-better for leaching/irrigation/percolation; bar charts). Mounted in `FieldReport.tsx`.

## Then three enhancements

1. **Re-run a snapshot** — `swat_service.rerun()` + `POST …/rerun` reads the stored parameters and re-launches the identical config, auto-labelling `"<name> (re-run)"`. The button polls to completion with a spinner.
2. **Overlaid time-series** in the compare view — one SVG line chart per run on shared axes, with a metric toggle (soil water / ET / biomass / N leached) aggregated per year.
3. **Save PDF** — `savePdf()` adds `body.print-compare`, and an injected `@media print` block hides everything except `#run-compare-print`, drops the toolbar, and shrinks the metric table so the % column isn't clipped. Result: one clean A4 page, no app chrome.

## Gotchas found
- The print `<style>` and `#run-compare-print` only exist in the **loaded** render, not the `Loading…` early-return — printing mid-fetch would print the whole page. Unreachable from the UI (the button only exists once loaded).
- `POST …/label` rejects non-ASCII (an em dash → *"error parsing the body"*).

## Related
[[Run Snapshots and Compare]] · [[Run Timeline]] · [[Rotation Comparison Study]]
