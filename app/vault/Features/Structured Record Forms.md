---
tags: [feature]
aliases: [Record Forms, Field Metadata]
created: 2026-07-27
---
# Structured Record Forms

The core per-file editing UX of the [[SWAT+ Editor]]: every editable record renders as a **grid of labelled fields** — each with a label, unit, description tooltip, and (for coded fields) a **dropdown** rather than a raw integer.

## The list ↔ form pattern
`components/FileTableEditor.tsx` shows a file as a list; a per-row **Edit** (pencil) opens `components/swateditor/RecordForm.tsx`, the labelled-field grid. "Back to list" returns.

Example — `codes.bsn`:
- *PET method* → dropdown (Penman-Monteith / Priestley-Taylor / Hargreaves)
- *Infiltration* → dropdown (curve number / **Green-Ampt**)
- *Channel routing*, *Plant stress*, *Daily curve number*, *Carbon model*, *Tile drainage* → dropdowns

## Where the metadata comes from
`swat_editor_service.py` `_FIELD_META` (hand-authored) merged with a bundled `field_metadata.json`:
- **55 files** carry metadata (**453 columns, 18 dropdowns**).
- The bulk of it was **mined from the official SWAT+ Editor's source** by a multi-agent workflow and **verified column-by-column against each field's real header** — see [[2026-07-24 Bulk field metadata extraction]].
- `read_file` returns `columns = _column_meta(name, header)`; files without metadata fall back to header-derived labels + numeric-type detection.

## Two parser fixes that ship with it
- **Free-text trailing column** — a trailing `description`/`text` column is treated as rest-of-line, so rows with a blank or spaced description parse as a table instead of bailing to raw. Byte-identical save round-trip.
- **No-store fetch** — API GETs send `cache: 'no-store'`; GET file responses were being HTTP-cached and shown stale after an edit/restart.

## Related
[[SWAT+ Editor]] · [[Layered Soil Editor]] · [[2026-07-24 SWAT+ Editor structured forms]] · [[2026-07-24 Bulk field metadata extraction]]
