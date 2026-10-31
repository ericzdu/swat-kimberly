---
tags: [domain]
aliases: [Green-Ampt, gampt, Cold crash]
created: 2026-07-27
---
# Green-Ampt Infiltration

The infiltration method the build sets on every project (`codes.bsn gampt=1`), via `build_project_service._set_gampt_infiltration`.

## Why (the cold-weather crash)
After fixing the [[gridMET Weather|gridMET tmin bug]], both rev-61 and rev-62 engine builds crashed (exit 3, SIGFPE) a few days into the first sub-freezing spell (~Jan 4–6), after a full year had run fine — i.e. sustained below-freezing air temperature, cumulative state, **not** snow/stress/PET/output/single-day (all bisected out).

**Root cause:** the **curve-number frozen-soil runoff** adjustment raises a floating-point exception that the FPE-trapping (`-ffpe-trap`) Windows gnu builds turn into a hard crash.

**Fix:** switch to **Green-Ampt (Mein-Larson)** infiltration — a valid, physically-based method — which **completes on correct freezing weather**. The Galen field re-ran 2003–2013 on correct temps + gampt → completed, all totals finite.

> [!note]
> Green-Ampt uses daily precip here (fine). If curve-number is ever needed for cold climates, the engine must be rebuilt **without** `-ffpe-trap`.

## Related
[[SWAT+ Engine Integration]] · [[gridMET Weather]] · [[2026-07-24 gridMET temp offset and Green-Ampt]]
