---
tags: [domain]
aliases: [gridMET, Weather]
created: 2026-07-27
---
# gridMET Weather

Daily meteorology for the field's coordinates, applied by `weather_service.apply_gridmet_weather`.

## Fetch
- NCSS point CSV over **HTTP port 8080**: `http://thredds.northwestknowledge.net:8080/thredds/ncss/agg_met_{pr,tmmx,tmmn}_1979_CurrentYear_CONUS.nc?...&accept=csv`
- The HTTPS:8443 host times out; `urllib` can't reach the HTTPS elevation host either → **use `requests`**.
- Elevation from **USGS EPQS** (`epqs.nationalmap.gov/v1/json`).
- Slow for long ranges (~141 s for a 21-yr point request) and the server **refuses concurrent connections** → `_fetch_all` fetches short **sequential** 3-year chunks (`_CHUNK_YEARS`).
- Falls back to template weather if the fetch fails.

## Decoding (packed shorts)
NCSS returns **packed shorts** (scale not applied):
- precip mm = `raw × 0.1`
- °C = `raw × 0.1 + add_offset − 273.15`

> [!danger] The per-variable offset bug
> The temperature `add_offset` **differs by variable**: `tmmx` (max) = **220.0 K** but `tmmn` (min) = **210.0 K** (both scale 0.1, precip offset 0). Using 220 for both inflates every **min** temp by exactly **10 °C** → ~26% of days get `tmin > tmax`, the diurnal range collapses, and PET/ET, heat units, stress, crop growth & the N balance are all corrupted.
> Fix: `_degC(raw, offset)` takes the per-variable offset. See [[2026-07-24 gridMET temp offset and Green-Ampt]].

## Output
Writes `tfccpcp.pcp` / `tfcctmp.tem` (free-format: title, `nbyr tstep lat lon elev`, then `yr jday value[s]`).

## Related
[[Field Setup and Model Build]] · [[Green-Ampt Infiltration]] · [[SWAT+ Engine Integration]]
