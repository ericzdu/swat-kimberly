---
tags: [feature, domain]
aliases: [Reliability, Confidence, Honesty]
created: 2026-07-27
---
# Reliability and Confidence

The product's honesty stance. An **uncalibrated single-field SWAT+ run is not trustworthy for absolute** nutrient/nitrate numbers, so the app never presents one as fact.

## Core constraint (from a reliability research pass)
- Uncalibrated SWAT/SWAT+ over-predict soil & P loss and fail Moriasi thresholds; two default runs on the same basin diverged wildly (ET 519 vs 792 mm).
- Reliable evidence is **watershed-scale, monthly streamflow** — a figure that must **not** be cited for a single-field run.

## Product implications
- **Never surface a bare absolute value as fact.** Frame the flagship nitrate feature as an **A-vs-B scenario comparison** on the same field (biases cancel; decision-useful; defensible).
- **Every number carries a confidence badge:**
  - 🟠 *Uncalibrated (directional)*
  - 🔵 *Calibrated to a nearby USGS gauge*
  - 🟢 *Calibrated to your data*
- The [[AI Advisor]] speaks in relative/directional terms, enforced in the system prompt.
- Confidence is **structural**: every numeric widget carries a required `confidence` field ([[Agent and Widget Protocol]]).

## Readiness (gating)
`readiness_service` gates whether a field can be simulated and surfaces plain warnings. A location-grounded build (real gSSURGO + gridMET) is recognised as **verified map data**; template-default layers stay conservative and are never overstated. See [[Confidence and Readiness]] and [[2026-07-27 Readiness grounded-build fix]].

## Technical anchors
- Grade with **Moriasi et al. 2007**: NSE, PBIAS, RSR (+ graphs). Monthly streamflow satisfactory = NSE > 0.50, RSR ≤ 0.70, PBIAS ≤ ±25% (±15% flow, 2015 update). Relax ~1 class for daily.
- Reduce equifinality with a soft-data (baseflow-index) constraint; multi-variable (ET/LAI) calibration cuts uncertainty.

## Related
[[Confidence and Readiness]] · [[Run and Calibrate]] · [[People and Provenance]]
