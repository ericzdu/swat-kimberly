---
tags: [feature]
aliases: [Editor]
created: 2026-07-27
---
# SWAT+ Editor

A faithful, in-app re-creation of the **official SWAT+ Editor's** per-file editing experience, for anyone who wants to inspect or tune the underlying model.

## Navigation
The left nav mirrors the section order of the master watershed file (`file.cio`): **19 sections** — Project, Basin, Climate, Connections, Channels, Routing Units, HRUs, Aquifers, Recall/Point Sources, Regions, Hydrology, Structural, Databases, Operations, Land Use Management, Decision Tables, Initialization, Soils, Change, Run. Full mapping in [[Editor File Map]].

- Frontend nav: `src/pages/swatEditorNav.ts` (`SWAT_NAV`).
- A slim icon rail toggles **Edit inputs** ↔ **Run** modes.

## Editing modes
| File shape | Editor |
|---|---|
| Tabular | list ↔ [[Structured Record Forms]] |
| Nested soil→layers | [[Layered Soil Editor]] |
| Large database | [[Databases Browser]] (search/paginate) |
| Multi-section / raw | raw-text editor (e.g. `print.prt`, decision tables) |

## Backend
`swat_editor_service.py` + `routers/swat_editor.py`:
- `GET /{farm}/files`, `GET /{farm}/file?name=…`, `POST /{farm}/file` (read/write any TxtInOut file)
- `GET /{farm}/soil`, `POST /{farm}/soil` (the nested soils editor)
- Every write makes a `.bak` backup; path-traversal guarded.
- Returns per-column edit metadata (`columns`) — see [[Structured Record Forms]] and [[2026-07-24 Bulk field metadata extraction]].

## Run panel
Tabs: **Run / Parameters / Print output / Crop / Calibration** — see [[Run and Calibrate]].

## Related
[[Structured Record Forms]] · [[Layered Soil Editor]] · [[Databases Browser]] · [[Editor File Map]] · [[Run and Calibrate]]
