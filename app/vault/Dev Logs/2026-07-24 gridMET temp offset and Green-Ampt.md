---
tags: [devlog, fix, crash]
created: 2026-07-24
---
# 2026-07-24 — gridMET temp offset & Green-Ampt

Two coupled fixes that made the engine run on *correct* weather.

## 1. gridMET min-temp inflated by 10 °C `#fix`
**Symptom:** ~26% of days had `tmin > tmax`; diurnal range collapsed; ET/heat-units/N-balance corrupted.
**Root cause:** `_degC` hard-coded add_offset **220 K** for both `tmmx` and `tmmn`, but `tmmn`'s offset is **210 K**.
**Fix:** `weather_service._degC(raw, offset)` takes a per-variable offset; the tem-writer passes `220.0` for max, `210.0` for min.
**Verified:** 0/7670 bad days, 13.8 °C diurnal range. See [[gridMET Weather]].

## 2. Cold-weather engine SIGFPE `#crash`
**Symptom:** after fixing the temps, both rev-61/62 crashed (exit 3) ~Jan 4–6, after a clean first year.
**Bisection:** not snow / stress / PET / output / single-day — a cumulative cold-soil effect.
**Root cause:** the **curve-number frozen-soil runoff** calc raises an FP exception the `-ffpe-trap` build turns into a crash.
**Fix:** `build_project_service._set_gampt_infiltration` sets `codes.bsn gampt=1` (**Green-Ampt**) on every build.
**Verified:** the field re-ran 2003–2013 on correct temps + gampt → completed, all totals finite (yield 7576, ET 812 mm/yr). See [[Green-Ampt Infiltration]].

## Related
[[gridMET Weather]] · [[Green-Ampt Infiltration]] · [[SWAT+ Engine Integration]]
