---
tags: [devlog, editor]
created: 2026-07-24
---
# 2026-07-24 — Layered soils editor

Built a purpose-built editor for the nested `soils.sol` file (the PI cares about soil layers).

## What shipped
- Backend `swat_editor_service.read_soil / write_soil`:
  - `nly`-driven parse — a soil record (7 cols) + `nly` layer rows (14 cols).
  - Column-aligned free-format writer with a **byte-token-identical** round-trip (verified vs a re-parse and by re-running the engine).
  - Routes `GET/POST /api/swat/editor/{farm}/soil`; `.bak` backup before every save.
- Frontend `components/swateditor/SoilEditor.tsx`: soil selector + soil-property form (reuses `RecordForm`, hides derived `nly`) + editable per-layer grid (14 cols with labels/units/tooltips) + a **derived depth column** (`0–20 cm`) + add/remove layer + Save.
- Wired in `SwatEditor.tsx`: `leaf.file === 'soils.sol' ? <SoilEditor> : <FileTableEditor>`.

**Verified:** read → edit → save → `.bak` → persist, tokens identical.

## Related
[[Layered Soil Editor]] · [[SWAT+ File Model]] · [[gSSURGO Soil]]
