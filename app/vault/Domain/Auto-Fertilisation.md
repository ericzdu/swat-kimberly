---
tags: [domain, nutrients, fertiliser]
aliases: [Auto-Fertiliser, AUTO_EFF, AUTO_NAPP, Fertilizer]
created: 2026-07-31
---
# Auto-Fertilisation

How AI-SWAT+ decides how much nitrogen and phosphorus to apply, and why it had to be built rather than configured.

## The problem: rev-62 has no auto-fertiliser

SWAT2012 had a genuine auto-fertiliser driven by two parameters the PI uses:

| Parameter | Meaning | Project setting |
|---|---|---|
| **AUTO_EFF** | Apply enough to replace N *removed at harvest*, times this efficiency. >1 covers runoff/leaching losses. | **1.1** |
| **AUTO_NAPP** | Maximum mineral N in any one application (kg N/ha). | **10** |

**Neither exists in SWAT+ rev-62.** Verified against the engine source: the decision-table action list contains `fertilize` and `fert_future` (which only sets a future day) but **no harvest-removal action**, and there is no `auto_fert` source file anywhere in the tree.

What rev-62 *does* offer is a stress-triggered table (`fert_stess_test` in the template) that applies a **fixed amount** whenever the crop is stressed:

```fortran
! actions.f90 — the "fertilize" action
if (pcom(j)%dtbl(idtbl)%num_actions(iac) <= Int(d_tbl%act(iac)%const2)) then
  frt_kg = d_tbl%act(iac)%const        ! kg/ha per application
```

* `const` = kg/ha **per application** → the AUTO_NAPP analogue
* `const2` = **maximum number of applications**

> [!bug] Why every early run reported 0 kg N applied
> The template ships that table, but `management_service` **never attached it** — a field's `management.sch` listed only the rotation table and auto-irrigation (`numb_auto 2`). No fertiliser operation existed at all beyond optional manure.

## How it works now

`management_service` schedules AUTO_EFF explicitly, because the engine can't:

1. `read_plant_yield_fracs()` reads **`frac_n_yld` / `frac_p_yld`** from the field's own `plants.plt` — SWAT's own definition of nutrient contained in yield.
2. Nutrient removed at harvest = `yield × frac_n_yld`.
3. Target applied = `removal × AUTO_EFF`.
4. That total is split into **AUTO_NAPP-sized applications** spread across the crop's growing window (from ~10 days after planting to ~25 days before harvest), written as `fertilize` alternatives in the rotation decision table.

Legumes (alfalfa, soybean) receive **P only** — they fix their own nitrogen.

## Target yield, not achieved yield

Basing removal on the yield the model *last produced* is **self-referential**: a depressed yield gives a depressed rate, which can never lift the yield. The loop pins itself near zero.

So removal is computed against an **attainable target yield** (`TARGET_YIELD`) — what the grower is fertilising *for*:

| Crop | Target yield (kg/ha DM) | N applied in its year |
|---|---:|---:|
| Corn (grain) | 11,000 | 212 |
| Potato | 10,000 | 194 |
| Sugar beet | 12,000 | 172 |
| Winter wheat | 5,500 | 151 |
| Alfalfa | 13,000 | 0 (fixes its own) |

Rotation averages work out at ~123 kg N/ha/yr for corn/alfalfa (only 11 years in 19 are fertilised) and ~198 for the all-annual rotation.

> [!warning] No soil-test credit
> Like SWAT2012's AUTO_EFF, this does not subtract residual soil nitrate. With 77–93 kg/ha sitting in the profile on this field, a soil-test-based recommendation would be roughly 60 kg/ha lower. Worth adding if rates are ever used as advice.

`apply_management(..., expected_yield={crop: kg/ha})` overrides the targets with measured yields — use once crop growth is trustworthy.

## Related
[[Crop Management and Rotations]] · [[Rotation Comparison Study]] · [[2026-07-31 Auto-fertiliser and crop diagnostics]] · [[Reliability and Confidence]]
