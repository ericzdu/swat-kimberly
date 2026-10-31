---
tags: [domain]
aliases: [Management, Rotations, lum.dtl]
created: 2026-07-27
---
# Crop Management and Rotations

How `management_service.apply_management` authors what grows and when.

## Single crop
A flat `management.sch`: `plnt` → optional `fert` (beef manure, kg/ha) → `hvkl`, with `numb_auto=1` (auto-irrigation). SWAT+ replays it annually. This is the proven corn-silage path.

## Rotation (the interesting case)
A **generated `jday + year_rot` decision table** appended to `lum.dtl`, referenced from `management.sch` as `numb_ops=0 numb_auto=2`.
- One alternative per operation; each fires on `jday == day AND year_rot == y`.
- Manure folded in as year-gated `fertilize` alts.
- **Reset** fires on `year_rot > N` (operator `>`, no jday) so the counter rolls back to 1 the year *after* the last crop.

> [!info] Why a decision table
> A flat multi-crop `management.sch` does **not** rotate — SWAT+ resets the schedule to op 1 each year, so only the first crop ever plants. Rotation *requires* `year_rot` decision tables.

## Crop calendar (`CROP_CAL`)
`csil` (plant Jun 1 / harvest Sep 25), `corn` (May 1 / Oct 15), `soyb` (May 20 / Oct 10), `wwht` (Sep 20 / **Jul 15 next year**), `alfa` (Apr 15 / Sep 1), `barl` (Apr 1 / Aug 1).

## The overlap rule
A **fall/winter crop** (`wwht`: harvest jday < plant jday, so it wraps into the next year) occupies the field Sep→Jul. A crop that **follows** a still-standing winter crop is **delayed until just after that crop's harvest** (`plant = prev_harvest + 10 days`), so the model never grows two crops at once. See [[2026-07-27 Crop rotation overlap fix]].

## Related
[[Field Setup and Model Build]] · [[Run Timeline]] · [[Databases Browser]] · [[2026-07-27 Crop rotation overlap fix]]
