---
tags: [domain]
aliases: [gSSURGO, Soil]
created: 2026-07-27
---
# gSSURGO Soil

The **USDA gridded Soil Survey Geographic** database — the real soil map layer used per field, applied by `soil_service.apply_gssurgo_soil(tio, lat, lon)`.

## What it does
- Looks up the **dominant soil** by MUKEY at the field centroid (via `swatplus_soils.sqlite`, USDA Geospatial Data Gateway).
- Writes real layers, textures and the hydrologic group into `soils.sol` — the layered file edited by the [[Layered Soil Editor]].

## `soils.sol` shape
A soil record (7 cols: `name nly hyd_grp dp_tot anion_excl perc_crk texture`) followed by `nly` layer rows (14 cols: `dp bd awc soil_k carbon clay silt sand rock alb usle_k ec caco3 ph`). See [[SWAT+ File Model]].

## Grounding
gSSURGO soil + [[gridMET Weather]] is what makes a build **location-grounded**; readiness recognises it as verified map data (the elevation/topography layer stays template-default and is *not* overstated). See [[2026-07-27 Readiness grounded-build fix]] and [[Confidence and Readiness]].

## Two database backends (portability)
The USDA dataset ships as a Microsoft **Access `.mdb`**, readable only through `pyodbc` + the Windows-only Access driver — so soil silently fell back to the template inside Linux containers. It is now converted **once** to SQLite and works everywhere:

```bash
./tools/convert_ssurgo.sh /path/to/SWAT_US_SSURGO_Soils.mdb   # -> soils_db/ssurgo.sqlite
```

`soil_service._dominant_component` prefers `config.SSURGO_SQLITE` when that file exists and falls back to the `.mdb` otherwise, so Windows and Linux share one code path. 453 MB → 168 MB, 346,416 records, indexed on `MUID`. The database is **not redistributed** — obtain it from USDA/SWAT and convert. Full detail: [[2026-07-31 gSSURGO on Linux]].

## Related
[[Layered Soil Editor]] · [[Field Setup and Model Build]] · [[gridMET Weather]] · [[Docker Deployment]]
