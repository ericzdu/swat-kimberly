---
tags: [devlog, fix]
created: 2026-07-27
---
# 2026-07-27 — Readiness grounded-build fix

Stopped falsely warning "results may be less accurate" on real, grounded fields.

## Symptom
The chat banner showed **"Farm map layers — results may be less accurate"** on a field built with real gSSURGO soil + gridMET weather.

## Root cause
The `gssurgo_rev62` build applies real soil + weather directly into `TxtInOut` but **never wrote a `data_manifest.json`**, so `readiness_service`'s "Farm map layers" check treated it as unverified.

## Fix (three coordinated changes)
1. `build_project_service.build_field_for_farm` now writes a verified manifest (accurate `sources`) **only when soil.ok AND weather.ok**.
2. `readiness_service._is_grounded_build` treats `data_source ∈ {gssurgo_rev62, online, online_verified}` (+ weather OK) as verified map data, with an honest detail — handles existing farms without a migration.
3. `confidence_service.grounded_gis` matches.

## Guardrail preserved
Per-layer confidence stays gated by `ds_ready()`, so **template-default layers** (elevation/topography — not DEM-derived in the gssurgo build) stay *missing/none* and are **never overstated**. Verified: soil/elevation/landuse = missing; boundary/weather = high; gate is source-specific (`demo`/`upload`/empty still warn).

## Related
[[Confidence and Readiness]] · [[Reliability and Confidence]] · [[Field Setup and Model Build]]
