---
tags: [reference]
aliases: [Provenance, Credits, PI]
created: 2026-07-27
---
# People and Provenance

## The model
**SWAT+** (Soil & Water Assessment Tool +) is a peer-reviewed watershed hydrology model developed by **USDA-ARS** and **Texas A&M University (Blackland Research Center)**. AI-SWAT+ runs the **rev-62** engine via **pySWATPlus** (an officially listed Python interface). See [[SWAT+ Engine Integration]].

## Data sources (public)
| Dataset | Provider | Use |
|---|---|---|
| **gSSURGO** | USDA-NRCS (Geospatial Data Gateway) | dominant soil profile ([[gSSURGO Soil]]) |
| **gridMET** | Climatology Lab / Northwest Knowledge Network | daily precip & temperature ([[gridMET Weather]]) |
| **NWIS gauges** | USGS | observed flow for calibration ([[Run and Calibrate]]) |
| **EPQS** | USGS / The National Map | point elevation |

## Project research grounding
- **Principal Investigator:** Galen Richards — agricultural / nitrate-hydrology researcher (UNL → University of Idaho).
- Relevant published work: a 2021 journal paper and a 2020 MS thesis on **Bazile Creek nitrate** — the observed-nitrate context the app's nitrate feature is ultimately meant to be calibrated against.
- The app's reference management (corn-silage; gSSURGO soils; gridMET weather; auto-irrigation) follows the PI's spec.

> [!note]
> The app is a **research / decision-support tool**. Its outputs are model estimates — most reliable as directional, scenario-to-scenario comparisons on the same field — and are not a substitute for professional agronomic or engineering judgement. See [[Reliability and Confidence]].

## Related
[[Reliability and Confidence]] · [[AI-SWAT+ Overview]] · [[SWAT+ Engine Integration]]
