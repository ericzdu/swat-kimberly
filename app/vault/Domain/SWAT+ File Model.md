---
tags: [domain, reference]
aliases: [TxtInOut, File Model]
created: 2026-07-27
---
# SWAT+ File Model

A SWAT+ project is a folder (`TxtInOut`) of ~**69 plain-text input files**. Understanding their shapes drives the [[SWAT+ Editor]].

## Common shapes
| Shape | Example | Editor |
|---|---|---|
| Title + header + whitespace rows (tabular) | `codes.bsn`, `hydrology.hyd`, `plants.plt` | [[Structured Record Forms]] |
| Trailing free-text `description` column | `nutrients.sol`, `fertilizer.frt` | tabular (free-tail parse) |
| Nested (record + N sub-rows) | `soils.sol` (soil → `nly` layers) | [[Layered Soil Editor]] |
| Decision table | `lum.dtl` (`jday + year_rot`) | raw / generated ([[Crop Management and Rotations]]) |
| Multi-section | `print.prt` | raw |
| Master list | `file.cio` | defines the [[Editor File Map]] |

## Parsing rules (in `swat_editor_service`)
- Line 0 = title, line 1 = header, line 2+ = whitespace-delimited rows.
- A trailing `description`/`text` column is **free-text rest-of-line** (`free_tail`) — so blank/spaced descriptions still parse tabular.
- `soils.sol` is `nly`-driven (see [[Layered Soil Editor]]).
- Writes are **column-aligned free-format** with byte-token-identical round-trips; the engine reads free-format so exact spacing is cosmetic.

## Outputs (a run writes)
`mgt_out.txt` (management log) + daily HRU files `hru_wb_day`, `hru_pw_day`, `hru_nb_day` — parsed by [[Run Timeline]].

## Related
[[Editor File Map]] · [[SWAT+ Editor]] · [[Layered Soil Editor]] · [[Crop Management and Rotations]]
