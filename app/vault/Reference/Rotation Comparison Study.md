---
tags: [reference, study, results]
aliases: [Rotation Study, Crop Rotation Comparison]
created: 2026-07-31
---
# Rotation Comparison Study

A worked, end-to-end comparison of the PI's two candidate rotations on one field — **and the reference example of how to run a scenario comparison honestly** in this app.

Field **test101** · south-central Idaho (≈42.49 N, −114.38 W) · [[gSSURGO Soil|gSSURGO]] soil · [[gridMET Weather|gridMET]] weather · rev-62 engine, run in [[Docker Deployment|Docker]].

## Design

| | Rotation 1 | Rotation 2 |
|---|---|---|
| Sequence | corn ×5 → alfalfa ×4 | corn ×3 → potato → sugar beet → wheat |
| Cycle length | 9 years | 6 years |
| Run window | **1995–2013 (18 yrs)** | **1995–2013 (18 yrs)** |
| Whole cycles | 2 | 3 |
| Fertiliser | auto, AUTO_EFF 1.1 in 10 kg/ha splits — 212 kg N/ha on corn years, none on alfalfa | auto — 212 corn, 194 potato, 172 beet, 151 wheat |
| Irrigation | auto, medium tier (9.1 mm at 0.8 × field capacity) | same |

18 years is the smallest window that contains **whole cycles of both** — the common multiple of 9 and 6. Everything else (soil, weather, irrigation tier, field) is identical, so differences are attributable to the rotation alone.

> [!danger] The trap this study exists to document
> The field was first built with a **3-year** window. Rotation 1's alfalfa doesn't start until year 6, so alfalfa **never occurred** — the model quietly ran corn-only and would have produced a confident, meaningless comparison. Always check the window covers the rotation.

## Results (17 reported years, 1997–2013 after warm-up)

Totals summed over every simulated day; the per-year column divides by the 17 reported years.

| Metric | Rotation 1 | Rotation 2 | Change | R1 /yr | R2 /yr |
|---|---:|---:|---:|---:|---:|
| **Irrigation (mm)** | 9,446 | **7,599** | **−20%** | 556 | 447 |
| Evapotranspiration (mm) | 13,950 | 12,155 | −13% | 821 | 715 |
| **Percolation (mm)** | 116 | **71** | **−39%** | 6.8 | 4.2 |
| **N leached (kg/ha)** | 398 | **241** | **−39%** | 23.4 | 14.2 |
| N applied (kg/ha) | 2,118 | 3,455 | +63% | 125 | 203 |
| N uptake (kg/ha) | 123 | **126** | +2% | 7.2 | 7.4 |
| Precipitation (mm) | 4,545 | 4,545 | 0% ✓ control | 267 | 267 |

Per-crop harvests, with realised **harvest index** against the parameter value:

| Crop | R1 harvests | biomass | yield | HI | R2 harvests | biomass | yield | HI |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Corn *(param 0.55)* | 10 | 6,405 | 117 | **0.018** | 9 | 6,187 | 99 | **0.016** |
| Alfalfa | 8 | 1,275 | 336 | 0.264 | — | — | — | — |
| Potato *(1.05)* | — | — | — | — | 3 | 3,315 | **1,888** | 0.569 |
| Sugar beet | — | — | — | — | 3 | 1,299 | **686** | 0.528 |
| Winter wheat *(0.40)* | — | — | — | — | 3 | 476 | 0 | **0.001** |

## Reading

**Rotation 2 is the lower-impact system on every water and nitrogen measure** — a fifth less irrigation, 39% less deep drainage and 39% less nitrate leached, despite receiving 63% *more* nitrogen (it has no legume year, so every year is fertilised). The mechanism is the alfalfa phase in Rotation 1: a deep-rooted perennial transpiring for the whole frost-free season drives both irrigation demand and drainage. Identical precipitation confirms the weather was a true control.

Note that **leaching tracks percolation, not fertiliser rate** — the effective lever on nitrate loss here is reducing deep drainage, consistent with the irrigation-management focus of the Bazile Creek work.

> [!warning] Directional, not predictive — and yield/N are currently unusable
> Uncalibrated single-field output: the **ranking and direction** are the result, not the absolute
> numbers. The **water balance is the trustworthy part**. Yield and nitrogen uptake are **not
> quotable** — corn realises a harvest index of 0.018 against a parameterised 0.55 — until the crop
> parameters are revised. See the diagnosis below and [[Reliability and Confidence]].

## How it was produced
Entirely through the [[AI Advisor]], which now drives the whole chain from one sentence:
`set_simulation_years` → `apply_crop_rotation` → `start_swat_simulation` → `wait_for_simulation`, then each run labelled and compared in [[Run Snapshots and Compare]]. Getting there required four fixes — see [[2026-07-31 Advisor rotation tools]].

## Growth-limitation diagnosis (the key result)

Daily stress factors averaged over days with a standing crop:

| Stress | Rotation 1 | % days >0.5 | Rotation 2 | % days >0.5 |
|---|---:|---:|---:|---:|
| **Temperature** | **0.333** | **27%** | **0.395** | **35%** |
| Water | 0.213 | 20% | 0.213 | 20% |
| **Nitrogen** | **0.000** | **0%** | **0.000** | **0%** |
| Aeration | 0.000 | 0% | 0.000 | 0% |

**Nitrogen stress is exactly zero on every growing day.** A controlled test confirmed it: raising
supply from ~2 to 212 kg N/ha per crop year (22-226x) changed uptake by **exactly nothing**
(7.2 -> 7.2 and 7.4 -> 7.4 kg/ha/yr) while leaching rose 8-11x. **Temperature is the binding
constraint** - set by `tmp_opt` / `tmp_base` in `plants.plt`, so a crop-parameter question.

Supporting indicators: peak LAI 4.87 vs corn's potential 6.0; ET/PET 0.53-0.60; nitrogen use
efficiency 3.6-5.8%. Grain crops fail (corn HI 0.018, wheat 0.001) while root crops on the same
field succeed (potato 0.569, sugar beet 0.528) - so the defect is confined to **grain fill**.

Full write-up with year-by-year and per-crop tables: `report/Rotation_Comparison.pdf`.

## Related
[[Crop Management and Rotations]] · [[Run Snapshots and Compare]] · [[Reliability and Confidence]] · [[2026-07-31 Advisor rotation tools]]
