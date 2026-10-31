---
tags: [reference, overview]
aliases: [Terms, Glossary]
created: 2026-07-27
---
# Glossary

## Model & files
- **SWAT+** — Soil & Water Assessment Tool (plus); a peer-reviewed USDA-ARS / Texas A&M watershed hydrology model. See [[People and Provenance]].
- **TxtInOut** — the folder of ~69 plain-text input files that constitute one SWAT+ project. See [[SWAT+ File Model]].
- **`file.cio`** — the master watershed file; its section order defines the [[Editor File Map]].
- **HRU** — Hydrologic Response Unit; the modelling unit for a field.
- **`rev-62`** — the SWAT+ engine build used ([[SWAT+ Engine Integration]]).
- **`mgt_out.txt`** — the management operations log a run writes; parsed by [[Run Timeline]].

## Hydrology / agronomy
- **ET / PET** — actual / potential evapotranspiration.
- **Green-Ampt** — a physically-based infiltration method; used instead of curve-number to avoid a cold-weather crash ([[Green-Ampt Infiltration]]).
- **Curve number (CN)** — the alternative runoff/infiltration method.
- **gSSURGO** — USDA gridded soil survey ([[gSSURGO Soil]]).
- **gridMET** — gridded daily meteorology (~4 km) ([[gridMET Weather]]).
- **Hydrologic group (A/B/C/D)** — a soil's runoff-potential class.
- **NO₃ / nitrate** — the nitrogen-leaching watch-item; the app's flagship concern.
- **NSE / PBIAS / KGE / R²** — goodness-of-fit indicators for calibration ([[Run and Calibrate]]).

## App concepts
- **Canvas** — the AI-summoned right-hand pane that materialises the UI a question needs ([[Generative Canvas]]).
- **Widget** — a typed unit of canvas UI (card, chart, table, timeline) ([[Agent and Widget Protocol]]).
- **Confidence badge** — the honesty marker on every result ([[Reliability and Confidence]]).
- **Readiness** — per-check gating of whether a field can be simulated ([[Confidence and Readiness]]).
- **Rotation decision table** — a `jday + year_rot` table in `lum.dtl` driving a crop rotation ([[Crop Management and Rotations]]).

## Related
[[AI-SWAT+ Overview]] · [[SWAT+ File Model]]
