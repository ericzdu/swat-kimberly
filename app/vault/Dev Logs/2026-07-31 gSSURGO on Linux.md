---
tags: [devlog, data, portability]
created: 2026-07-31
---
# 2026-07-31 — gSSURGO on Linux (SQLite conversion)

Real, location-specific soil was the last Windows-only dependency. Now it works everywhere.

## Problem

`soil_service._dominant_component` read the USDA **"SWAT US SSURGO Soils" `.mdb`** through `pyodbc` + the *Microsoft Access Driver* — Windows only. In a Linux container the import fails, so every field fell back to the generic template soil:

```
Soil database read failed: No module named 'pyodbc'
```

Fields still built and ran (the failure is caught), but the soil under the field was not the soil in the model.

## Fix — convert once to SQLite

`tools/convert_ssurgo.sh` runs **mdbtools inside a throwaway Docker container**, so nothing needs installing locally:

```bash
./tools/convert_ssurgo.sh /path/to/SWAT_US_SSURGO_Soils.mdb
```

`mdb-schema … sqlite -T SSURGO_Soils` for the DDL, `mdb-export -I sqlite` piped into `sqlite3` (wrapped in `PRAGMA synchronous=OFF; journal_mode=MEMORY; BEGIN/COMMIT` for speed), then an index on `MUID` and `VACUUM`.

**453 MB `.mdb` → 168 MB `ssurgo.sqlite`, 346,416 records**, ~7 minutes.

## Code

`soil_service` now has two backends behind one dispatcher:

```python
def _dominant_component(mukey):
    if config.SSURGO_SQLITE and Path(config.SSURGO_SQLITE).is_file():
        return _dominant_component_sqlite(mukey)   # portable
    return _dominant_component_mdb(mukey)          # Windows/pyodbc
```

The SQLite path opens read-only (`file:…?mode=ro`) and uses `sqlite3.Row` → `dict`, so the keys match the pyodbc path exactly and the downstream `soils.sol` writer is untouched. `config.SSURGO_SQLITE` = env override, else the first existing of the local path or `/opt/ai-swat/soils_db/ssurgo.sqlite`.

`docker-compose.yml` mounts `./soils_db` read-only. **Optional** — an empty folder just falls back to template soil.

## Verified

mukey `80295` → **Portneuf**, 95 % component, 2 layers, hydrologic group C, `dp_tot` 1520 mm — matching the a10 reference field-for-field, both standalone and inside the container, followed by a completed model run on that soil.

> [!tip] Bonus
> The Windows app now uses the SQLite copy too, so it no longer needs the Access driver at all.

## Related
[[gSSURGO Soil]] · [[Docker Deployment]] · [[2026-07-31 Docker packaging]]
