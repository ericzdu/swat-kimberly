---
tags: [devlog, fix]
created: 2026-07-27
---
# 2026-07-27 — Crop rotation overlap fix

Winter wheat and alfalfa were growing **at the same time** in a rotation.

## Symptom
On a wheat+alfalfa field, the [[Run Timeline]] drew the two crops overlapping. Confirmed real in `mgt_out.txt`:
```
2009-09-20  wwht PLANT
2010-04-15  alfa PLANT      ← planted while wheat still standing
2010-07-15  wwht HARV/KILL  ← wheat harvested 3 months later
```

## Root cause
Winter wheat is fall-planted and harvested the *next* July, so it occupies the field Sep→Jul. The rotation table planted the next crop (alfalfa) on its normal spring date (Apr 15) — mid-wheat-season. Real overlap in the model, not a viz bug.

## Fix (`management_service._build_rotation_dtl`)
Precompute each slot's `(pj, hj, is_fall = hj < pj)`. If the **previous** slot (cyclic) is a fall crop harvesting in this crop's plant year and `pj < prev_hj + _PLANT_GAP(=10) < hj`, delay planting to `prev_hj + 10`. Also switched the harvest-wrap test to the precomputed `is_fall`.

## Verified end-to-end
Re-ran rev-62 (2008–2013): `wwht HARV 07-15` then `alfa PLANT 07-25` — no overlap, every cycle. Patched the demo field's `lum.dtl` in place (`.bak` saved) and re-ran so its stored timeline shows the fix. See [[Crop Management and Rotations]] and [[Demo Field - North Field]].

> [!note] Tradeoff
> A late-July alfalfa seeding gives a short first cut (low biomass); multi-cut perennial alfalfa isn't modelled (still harvest_kill each cycle).

## Related
[[Crop Management and Rotations]] · [[Run Timeline]] · [[Demo Field - North Field]]
