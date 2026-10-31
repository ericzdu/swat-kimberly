---
tags: [feature]
aliases: [Soil Editor, soils.sol]
created: 2026-07-27
---
# Layered Soil Editor

`soils.sol` is **nested** — one soil with several layers — so it gets a purpose-built editor rather than a flat table.

## UX (`components/swateditor/SoilEditor.tsx`)
- **Soil selector** with layer count and total depth.
- **Soil properties** — name, hydrologic group (dropdown A/B/C/D), max rooting depth, texture, anion exclusion, crack volume.
- **Layer grid** — one row per layer: a *derived depth range* (e.g. `0–20 cm`) plus depth-to-bottom, bulk density, available water capacity, saturated hydraulic conductivity, organic carbon, clay/silt/sand, etc.
- **Add / remove layer**; layer count (`nly`) and total depth update automatically on save; a `.bak` backup is written before every save.

## Backend (`swat_editor_service.py`)
- `read_soil(farm_id)` — `nly`-driven parse: a soil record (7 columns) followed by `nly` layer rows (14 columns). Returns `{soils[], soil_cols, layer_cols}` with per-column metadata.
- `write_soil(farm_id, soils)` — a **column-aligned free-format** writer with a **byte-token-identical** round-trip (verified against a re-parse and the engine).
- Routes: `GET/POST /api/swat/editor/{farm}/soil`.

See [[SWAT+ File Model]] for the file format and [[gSSURGO Soil]] for where the data comes from.

## Related
[[SWAT+ Editor]] · [[Structured Record Forms]] · [[gSSURGO Soil]] · [[2026-07-24 Layered soils editor]]
