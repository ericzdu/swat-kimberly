---
tags: [feature]
aliases: [Field Setup, Model Build, Build Pipeline]
created: 2026-07-27
---
# Field Setup and Model Build

A **deterministic** pipeline that turns a saved field boundary + the farmer's choices into a complete, location-correct SWAT+ rev-62 project. Nothing is a generic placeholder.

## The pipeline (`build_project_service.build_field_for_farm`)
1. **Clone the engine template** — start from a validated rev-62 `TxtInOut`; strip stale outputs.
2. **Apply gSSURGO soil** — dominant soil at the field centroid → `soils.sol` ([[gSSURGO Soil]]).
3. **Fetch gridMET weather** — daily precip + min/max temp for the location & window ([[gridMET Weather]]).
4. **Author crop management** — flat single-crop or a `jday + year_rot` rotation decision table, with per-year manure and an auto-irrigation tier ([[Crop Management and Rotations]]).
5. **Configure & window the run** — set [[Green-Ampt Infiltration|Green-Ampt]] infiltration and the simulation period; hand off to the engine.

On a successful grounded build it writes a **verified data manifest** so [[Confidence and Readiness|readiness]] recognises the real map layers ([[2026-07-27 Readiness grounded-build fix]]).

## Endpoints
- `POST /api/farms/{id}/fetch-and-build` → sets `data_source = "gssurgo_rev62"` on the farm.
- Boundary: `POST /api/farms/{id}/boundary`; also online download and upload paths.

> [!danger] Safety invariant
> Field **creation and deletion are never delegated to the LLM** — an earlier version caused stray farms and data loss. New-field setup is deterministic and user-driven. See [[People and Provenance]].

## Windowing
pySWATPlus requires `warmup ≥ 1`, so a build targets `(END_YEAR − N … END_YEAR)` and skips the leading year, keeping the run inside the engine's stable pre-instability window (pre-2014). See [[SWAT+ Engine Integration]].

## Related
[[gSSURGO Soil]] · [[gridMET Weather]] · [[Crop Management and Rotations]] · [[SWAT+ Engine Integration]]
