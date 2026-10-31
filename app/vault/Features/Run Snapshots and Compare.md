---
tags: [feature, runs, comparison]
aliases: [Snapshots, Run Compare, Scenario Comparison]
created: 2026-07-31
---
# Run Snapshots and Compare

Every model run is already persisted (a `simulations` row + `data/outputs/{run_id}`). This feature turns that history into **named scenarios you can browse, re-run and compare** — the backbone of "what if I farmed it differently?".

Because single-field output is [[Reliability and Confidence|directional, not absolute]], **comparison is the honest way to use this model**: the same field, same weather, one thing changed.

## What the farmer sees

**Run snapshots** panel (appears once a field has 2+ completed runs):
- every completed run, newest first, with its date and simulated window
- ✏️ **rename** — turn `baseline` into "Rotation 1: corn ×5 / alfalfa ×4"
- ↻ **re-run** — repeat that snapshot's exact setup as a new run
- ☑︎ tick two or more → **Compare**

**Compare view**:
- a metric table (yield, N leached, N uptake, N applied, irrigation, ET, precipitation, percolation) with the **best value per row in bold** — lower-is-better is respected for leaching/irrigation/percolation — plus a % change column
- an **overlaid time-series** chart with a metric toggle (soil water / ET / biomass / N leached), aggregated per year
- bar charts of the headline totals
- **Save PDF** — print-isolated to just the comparison, one clean page

## Implementation

**Backend** (`swat_service`)
- `list_for_farm` returns `label` / `scenario` / `begin_date` / `end_date`
- `set_label(run_id, label)` → `POST /api/swat/runs/{id}/label` (stored in the run's `parameters` JSON)
- `rerun(run_id, label?)` → `POST /api/swat/runs/{id}/rerun` — reads the stored parameters and calls `start_run` with the identical config, auto-labelling `"<name> (re-run)"`

**Frontend**
- `components/RunSnapshots.tsx` — the list, inline rename, re-run (polls to completion), multi-select
- `components/RunCompare.tsx` — table + SVG line chart + bar charts + `savePdf()`
- both mounted in `FieldReport.tsx`; `compareIds.length >= 2` swaps the single [[Run Timeline]] for the compare view

> [!warning] Label gotcha
> `POST …/label` rejects non-ASCII characters (an em dash returns *"There was an error parsing the body"*). Use plain ASCII labels.

## Comparing fairly
The window must cover **whole cycles of everything being compared** — an 18-year run gives 2 cycles of a 9-year rotation and 3 of a 6-year one. A window shorter than the rotation silently compares only its first crop. See [[Rotation Comparison Study]].

## Related
[[Run Timeline]] · [[Crop Management and Rotations]] · [[Rotation Comparison Study]] · [[2026-07-29 Run snapshots and compare]]
