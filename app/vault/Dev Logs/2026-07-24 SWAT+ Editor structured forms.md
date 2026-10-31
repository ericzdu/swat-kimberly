---
tags: [devlog, editor]
created: 2026-07-24
---
# 2026-07-24 — SWAT+ Editor structured forms

Rebuilt the editor's per-file editing to match the official SWAT+ Editor's UX.

## What shipped
- **Nav** rewritten to **19 sections in `file.cio` order** (`swatEditorNav.ts`) — see [[Editor File Map]].
- **List ↔ form** pattern (`FileTableEditor.tsx`): a per-row Edit opens `RecordForm.tsx`, a labelled-field grid with units, description tooltips, and **coded dropdowns**.
- Backend `swat_editor_service._FIELD_META` + `_column_meta(name, header)`; `read_file` returns `columns`. Initially 5 files (codes.bsn, hydrology.hyd, topography.hyd, snow.sno, irr.ops), then 12 hand-authored.

## Two fixes found along the way
- **Stale cache** — the form showed header-fallback labels because the GET file response was HTTP-cached from before a backend restart. Fixed with `cache: 'no-store'` on API GETs (`api.ts`).
- **Free-text trailing column** — `read_file` bailed to raw whenever a row's token count ≠ header length; a trailing `description` column (blank or spaced) broke it. Now treated as rest-of-line (`free_tail`). Byte-identical save round-trip. Fixed `nutrients.sol`, `landuse.lum`.

Coverage was later expanded massively — see [[2026-07-24 Bulk field metadata extraction]].

## Related
[[Structured Record Forms]] · [[SWAT+ Editor]] · [[Editor File Map]]
