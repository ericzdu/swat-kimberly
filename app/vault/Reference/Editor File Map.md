---
tags: [reference]
aliases: [File Map, file.cio, 19 sections]
created: 2026-07-27
---
# Editor File Map

The [[SWAT+ Editor]] nav mirrors the section order of `file.cio`. The 19 sections and the input files each edits (`src/pages/swatEditorNav.ts`):

| # | Section | Files |
|---|---|---|
| 01 | Project | dashboard · `file.cio` |
| 02 | Basin | `codes.bsn` · `parameters.bsn` |
| 03 | Climate | `weather-sta.cli` · `weather-wgn.cli` · `pcp.cli` · `tmp.cli` |
| 04 | Connections | `hru.con` · `rout_unit.con` · `chandeg.con` · `aquifer.con` |
| 05 | Channels | `initial.cha` · `channel-lte.cha` · `hyd-sed-lte.cha` · `nutrients.cha` |
| 06 | Routing Units | `rout_unit.rtu` · `.def` · `.ele` |
| 07 | HRUs | `hru-data.hru` |
| 08 | Aquifers | `aquifer.aqu` · `initial.aqu` |
| 09 | Recall / Point Sources | `recall_db.rec` |
| 10 | Regions | `ls_unit.def` · `ls_unit.ele` |
| 11 | Hydrology | `hydrology.hyd` · `topography.hyd` · `field.fld` |
| 12 | Structural | `tiledrain` · `septic` · `filterstrip` · `grassedww` · `bmpuser` (`.str`) |
| 13 | Databases | `plants.plt` · `fertilizer.frt` · `tillage.til` · `pesticide.pes` · `urban.urb` · `snow.sno` |
| 14 | Operations | `harv` · `graze` · `irr` · `chem_app` · `fire` · `sweep` (`.ops`) |
| 15 | Land Use Management | `landuse.lum` · `management.sch` · `cntable.lum` · `cons_practice.lum` |
| 16 | Decision Tables | `lum.dtl` · `res_rel.dtl` |
| 17 | Initialization | `plant.ini` · `soil_plant.ini` · `om_water.ini` |
| 18 | Soils | `soils.sol` · `nutrients.sol` |
| 19 | Change & Run | `cal_parms.cal` · `calibration.cal` · `time.sim` · `print.prt` |

## Related
[[SWAT+ Editor]] · [[SWAT+ File Model]] · [[Structured Record Forms]]
