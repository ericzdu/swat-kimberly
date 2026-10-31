---
tags: [feature]
aliases: [Timeline]
created: 2026-07-27
---
# Run Timeline

A scrollable, multi-year picture of **what the model actually did**, at the top of the results canvas.

## What it shows
- **Crop rotation bands** — each crop's growing window with its per-crop biomass (kg/ha). Winter crops and following crops now sit in sequence after the [[2026-07-27 Crop rotation overlap fix|overlap fix]].
- **Events** — irrigation and fertiliser applications as discrete markers.
- **Six stat cards** — yield, rainfall, irrigation, crop water use (ET), N applied, N leached.
- **Lens toggle** — re-plots the daily series under **Water / Growth / Nitrogen**.
- **Aggregation** — Weekly / Monthly / Yearly, chosen automatically by run length (Weekly ≤3 yr, Monthly ≤8 yr, else Yearly).
- **Verdict line** — a one-sentence plain-language summary; a "Scientific details" expander for the raw series.

## Data pipeline
`run_timeline_service.build_timeline(run_id)`:
1. Parses `mgt_out.txt` → crop plant/harvest bands + irrigation/fertiliser events.
2. Merges daily HRU outputs (`hru_wb_day`, `hru_pw_day`, `hru_nb_day`) → per-day series.
3. Clips to the reported window (the daily-file date range, which excludes the skipped spin-up year).
4. Returns `crops[] events[] series[] totals{} stress{}`.

Served via `GET /api/swat/runs/{run_id}/timeline` → `RunTimeline.tsx`.

> [!note] It shows exactly what the engine simulated
> In one test the timeline revealed a real scheduling flaw — a winter-wheat → alfalfa rotation growing both crops at once — which was traced to the rotation table and fixed. See [[2026-07-27 Crop rotation overlap fix]].

## Frontend notes
- `RunTimeline.tsx` scales its scrollable width with the reported span (~300 px/yr) + a year axis.
- Recharts gotcha: `ReferenceLine`/`ReferenceDot` need a matching `yAxisId` and a resolvable `x`, or they throw and unmount the tree.

## Related
[[Generative Canvas]] · [[Crop Management and Rotations]] · [[Run and Calibrate]]
