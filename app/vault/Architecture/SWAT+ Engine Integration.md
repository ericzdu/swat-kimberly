---
tags: [architecture, domain]
aliases: [Engine, pySWATPlus, rev-62]
created: 2026-07-27
---
# SWAT+ Engine Integration

The compiled **SWAT+ rev-62** Fortran engine, driven via **pySWATPlus** (`pyswat_facade`, orchestrated by `swat_service`).

## Execution
- Each run stages the field's `TxtInOut` into an **isolated workspace** (`data/outputs/{run_id}/workspace/TxtInOut`) and copies the engine exe in.
- pySWATPlus **requires `warmup ≥ 1`** (warmup == `nyskip`, the # leading years skipped from *output*; there is no separate spin-up). So a build makes the window `(END_YEAR − N … END_YEAR)` (N+1 yrs) and runs warmup=1, reporting N years.

## Stability constraints (hard-won)
> [!bug] The base model SIGFPEs (exit 2) at recurring dates
> Confirmed crash dates **2014-08-04, 2018-11-11, 2022-12-06** — a cumulative model-state instability, **not** weather-driven. A warm-up year that *simulates* a crash date still crashes. No continuous 20-yr window is stable; the longest clean stretch is **pre-2014** (2004–2013 runs clean).
> → The build pins `END_YEAR = 2013` and caps N at 10.

> [!bug] Cold-weather SIGFPE (exit 3)
> On correct freezing weather the curve-number frozen-soil runoff calc raised an FP exception the FPE-trapping Windows gnu build turns into a hard crash. Fixed by switching to **Green-Ampt** infiltration (`codes.bsn gampt=1`). See [[Green-Ampt Infiltration]].

A "failed" long run still writes partial daily output up to the crash date, and [[Run Timeline]] parses it.

## Reading outputs
Read `mgt_out.txt` and the daily files **in the run workspace**, not the farm dir (stale copies mislead). `enable_farmer_outputs` sets daily=True for `hru_wb`, `hru_pw`, `hru_nb`.

## Related
[[Field Setup and Model Build]] · [[Green-Ampt Infiltration]] · [[Run Timeline]] · [[Tech Stack]]
