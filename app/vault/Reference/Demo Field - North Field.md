---
tags: [reference]
aliases: [North Field, Demo Field]
created: 2026-07-27
---
# Demo Field — North Field

The reference field used in the [[2026-07-27 Technical report and PDF|technical report]] screenshots and walkthrough.

## Identity
- **Name:** North Field — winter wheat / alfalfa
- **id:** `5360a8f5-ca56-41b4-a645-482362255683`
- **data_source:** `gssurgo_rev62` (grounded: real gSSURGO soil + gridMET weather)
- Location: Snake River Plain, Idaho (≈ 42.55, −114.35)

## Model
- Rotation: **winter wheat ↔ alfalfa** (a `jday+year_rot` decision table, [[Crop Management and Rotations]]).
- Soil: gSSURGO `80162`, 2 layers to 165 cm, hydrologic group B ([[gSSURGO Soil]]).
- It was the field that surfaced — and then validated the fix for — the [[2026-07-27 Crop rotation overlap fix|rotation overlap]].

## Reference run (2009–2013, 5 reported years)
| Metric | Value |
|---|---|
| Yield (rotation) | 2,978 kg/ha (≈ 3.0 t/ha) |
| Precipitation | 2,391 mm |
| Irrigation | 692 mm |
| Actual ET | 3,127 mm (of 5,490 potential) |
| Percolation | 66 mm |
| Surface runoff | 0 mm |
| N uptake | 15.4 kg/ha |
| N leached | 20.8 kg/ha |
| Growing / temp-stress / water-stress days | 764 / 423 / 4 |

> [!info] Read as directional
> These are uncalibrated single-field outputs — a self-consistent picture, most useful for scenario comparison. See [[Reliability and Confidence]].

## Related
[[2026-07-27 Crop rotation overlap fix]] · [[Run Timeline]] · [[2026-07-27 Technical report and PDF]]
