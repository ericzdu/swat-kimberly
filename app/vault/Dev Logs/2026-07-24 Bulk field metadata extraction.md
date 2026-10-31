---
tags: [devlog, editor]
created: 2026-07-24
---
# 2026-07-24 — Bulk field metadata extraction

Gave every tabular input file labelled forms by mining the official SWAT+ Editor.

## Method
A **22-agent Workflow** (11 category groups × extract + verify) mined the official SWAT+ Editor's **303 Vue views** for per-column labels, units, descriptions and dropdown codes, then **adversarially verified each column against the real file headers** and SWAT+ code values.

## Result
- Output validated column-by-column (only genuine special-list files dropped columns).
- Bundled as `backend/services/field_metadata.json` — **43 files · 453 columns · 18 dropdowns** — loaded and merged into `_FIELD_META` at import (hand-authored 12 win on collision).
- **55 of 69** input files now have metadata; all 38 tabular files render labelled forms with units + coded dropdowns.
- Dropdown codes are real SWAT+ values (obj_typ hru/cha/aqu/…, hyd_grp A/B/C/D, management op_typ plnt/harv/kill/…).

Regenerate the JSON with `scratchpad/gen_meta.py` against a workflow result.

## Related
[[Structured Record Forms]] · [[SWAT+ Editor]] · [[2026-07-24 SWAT+ Editor structured forms]]
