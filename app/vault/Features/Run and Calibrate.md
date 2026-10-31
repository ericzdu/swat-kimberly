---
tags: [feature]
aliases: [Run Panel, Calibration]
created: 2026-07-27
---
# Run and Calibrate

The [[SWAT+ Editor]]'s **Run** panel (`components/swateditor/RunPanel.tsx`) configures a simulation and scores it against observations. Parameter overrides here apply to a **single run only** and are not written back to the model files.

## Tabs
| Tab | Purpose |
|---|---|
| **Run** | Simulation period (begin/end), warm-up years, scenario name → *Run SWAT+* |
| **Parameters** | Override calibratable parameters for this run |
| **Print output** | Choose which output objects/frequency to print |
| **Crop** | Crop settings |
| **Calibration** | Compare simulated vs observed; compute goodness-of-fit |

## Triggering a run
`POST /api/swat/run` (`SwatRunRequest`: `farm_id`, `begin_date`, `end_date`, `warmup_years`, `parameters`, `scenario`) → runs in an isolated workspace under `data/outputs/{run_id}/workspace/TxtInOut`. Poll `GET /api/swat/runs/{id}`; read results with `GET /api/swat/runs/{id}/timeline` ([[Run Timeline]]).

## Calibration
Compare a **simulated column** (e.g. `flo_out` from `channel_sd_mon.txt`) against an **observed record** and compute **NSE, PBIAS, KGE, R²** (Moriasi indicators). This is the path from *uncalibrated / directional* to *calibrated* — see [[Reliability and Confidence]] and [[Confidence and Readiness]].

## Related
[[SWAT+ Editor]] · [[Run Timeline]] · [[Reliability and Confidence]] · [[SWAT+ Engine Integration]]
