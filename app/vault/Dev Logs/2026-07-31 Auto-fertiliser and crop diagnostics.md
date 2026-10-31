---
tags: [devlog, fix, science, nutrients]
created: 2026-07-31
---
# 2026-07-31 — Auto-fertiliser, and finding what actually limits the crops

Started as "get auto-fertilisation working" and ended by identifying the real constraint on every yield in the model.

## 1 · Auto-fertiliser was never attached

Runs reported **0 kg N applied** because `management_service` never referenced any fertiliser operation — `management.sch` listed the rotation table and auto-irrigation only. The template's `fert_stess_test` table existed but was orphaned.

Fixed by generating a per-field auto-fertiliser table and referencing it as a third auto operation. Full mechanism in [[Auto-Fertilisation]].

## 2 · AUTO_EFF doesn't exist in rev-62 — so it was implemented

Confirmed from the engine source that SWAT2012's harvest-removal auto-fertiliser has no rev-62 equivalent (`fertilize` applies a fixed amount; `fert_future` only sets a day; no `auto_fert` source file). It is now scheduled explicitly from `frac_n_yld` × yield × AUTO_EFF, split into AUTO_NAPP increments.

First attempt sized it from **achieved** yield and produced ~2 kg N/ha — a self-referential loop. Switched to **target yield**, giving 212 kg N/ha on corn years.

## 3 · Root crops were harvested as grain `#fix`

`CROP_CAL` gave potato and sugar beet `harv_op = "grain"`. Root crops have no seed pool, so both returned **exactly zero** yield. Switched to `tuber`:

| crop | before | after | harvest index |
|---|---:|---:|---:|
| potato | 3 kg/ha | **1,888** | 0.569 |
| sugar beet | 0 kg/ha | **686** | 0.528 |

Those harvest indices are now close to their parameter values — the tuber pathway works correctly.

## 4 · A correction I had to make

I initially reported `phuacc = 0` at every harvest as proof the crops never reached maturity. **That was wrong** — `mgt_killop` zeroes `phuacc` *before* the harvest line is written, so the zero is just the post-kill reset. Checked the source and retracted it.

## 5 · The controlled experiment

Nitrogen supply was raised from ~2 to 212 kg N/ha per crop year, everything else unchanged:

| | Rotation 1 | Rotation 2 |
|---|---|---|
| N applied (kg/ha/yr) | 5.7 → **124.6** | 0.9 → **203.2** |
| **N uptake** | 7.2 → **7.2** | 7.4 → **7.4** |
| N leached | 2.9 → 23.4 | 1.3 → 14.2 |

**A 22–226× increase in nitrogen produced exactly zero change in uptake.** Every extra kilogram leached or accumulated.

## 6 · What is actually limiting the crops

The daily stress factors settle it — averaged over days with a standing crop:

| Stress | R1 mean | % days >0.5 | R2 mean | % days >0.5 |
|---|---:|---:|---:|---:|
| **Temperature** | **0.333** | **27%** | **0.395** | **35%** |
| Water | 0.213 | 20% | 0.213 | 20% |
| **Nitrogen** | **0.000** | **0%** | **0.000** | **0%** |
| Aeration | 0.000 | 0% | 0.000 | 0% |

**Nitrogen stress is exactly zero on every growing day**, independently confirming the experiment. **Temperature stress is the binding constraint**, governed by `tmp_opt` / `tmp_base` in `plants.plt` — a crop-parameter question.

Supporting indicators: peak LAI 4.87 against corn's potential 6.0; ET/PET 0.53–0.60; nitrogen use efficiency 3.6–5.8%.

Grain crops (corn HI 0.018, wheat 0.001) fail while root crops on the same field succeed — so the defect is confined to **grain fill**, not growth in general.

## 7 · Both reports upgraded

The in-app [[Run Snapshots and Compare|Compare view]] gained the stress table, canopy/efficiency panel and mass-balance panel — previously these diagnostics existed only in a standalone PDF, which meant the app lagged behind the analysis. A standalone 8-page study PDF is in `report/`.

## Related
[[Auto-Fertilisation]] · [[Rotation Comparison Study]] · [[Crop Management and Rotations]] · [[Run Snapshots and Compare]]
