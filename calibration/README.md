# calibration

SWAT+ calibration for the **Kimberly, Idaho** field, supporting `Ai-SWAT-Plus`.

Re-homed 2026-09-04 from a copy of the `swat-kimberly` paper repo, and merged back into that
repo as `calibration/` on 2026-10-30. It remains a separate uv project with its own goals:
run its scripts with `uv run --project calibration ...` from the repo root, or `uv run` here.
The paper's LTM model copies its crop parameters from this directory; see `CLAUDE.md`.

## What is calibrated, against what

| Channel | Target | Where | State |
|---|---|---|---|
| **ET** | OpenET eeMetric, 7 crops × 2020/21/22, 21 fields, Jan–Dec monthly (36 pts/crop) | `data/et_reference.csv` | refit 2026-09-24 at `pet_co` 1.0: **5 of 7 crops meet R²>0.8 and \|PBIAS\|<10 %**, mean \|PBIAS\| 8.3 %. Wheat (26.5 %) and sugarbeet (R² 0.78) do not — see `CLAUDE.md` caution 3 |
| **PET** | AgriMet TWFI grass-reference ETos, 2013–2020 | `data/observed_et_agrimet.csv` | fitted, closed form |
| **Yield** | GRACEnet dry matter, 2013–2019, corn/barley/alfalfa | `calib_report.GRACENET` | fitted |
| **Soil NO₃** | GRACEnet April profile, 2013–2019, 4 plots × 5 depths | `data/soil_no3_gracenet.csv` | fitted, down-weighted |
| **Soil P** | GRACEnet April Olsen-P, 2013–2019 | `data/soil_p_gracenet.csv` | **target only — no P term in the objective** |

## Pipeline

```
~/Documents/Kimberly, Idaho/          # collaborator's workbooks, outside the repo
  ET Calibration/*.xlsx  ──► scripts/et_reference.py    ──► data/et_reference.csv
  Crop Parameters and
    Plant Harvest dates  ──► scripts/port_dates.py      ──► data/plant_harvest_dates.csv
  USDA GRACEnet/*.xlsx   ──► scripts/extract_primary.py ──► data/soil_*.csv, irrigation_*.csv
                                                            data/crop_params_swat.csv

data/et_reference.csv    ──► scripts/et_calibrate.py --apply ──► data/et_fitted.json
data/plant_harvest_dates.csv ─► monoculture.CROPS / IRR_SHEET  ──► the irrigation windows
data/et_fitted.json      ──► scripts/monoculture.py          ──► runs/crops_autofert/
model/TxtInOut           ──► scripts/calibrate/optimize.py   ──► yield + soil-NO3 fit
```

`data/et_fitted.json` is the **single source of truth** for the fit: a `shared` block (the
basin-wide `esco` and irrigation trigger, plus the held `epco` / `pet_co`) and a `crops` block
(each crop's canopy parameters). `model/TxtInOut` is never pre-patched with them — `monoculture.prepare_plants()`
applies them into each run copy. Do not add a second writer; that made `--apply`
non-idempotent, because the fit's regularisation anchors to whatever the template holds.

## Why ET and nutrients are calibrated separately

Two independent blockers, both structural:

1. **No shared year.** OpenET is 2020–2022; GRACEnet is 2013–2019. Nothing scores both.
2. **`esco` and `pet_co` are HRU-level.** The ET fit works only because each crop gets its own
   single-HRU monoculture run. A rotation is one HRU, so per-crop values cannot exist there.
   (Since 2026-09-24 `esco` is fitted basin-wide anyway, so it *would* cross; the irrigation
   windows are per-crop decision tables and would not.)

Only the plant parameters cross. Report the two as one scorecard with the incompatibility stated;
never as a single validated model.

## Getting started

```bash
uv sync --extra dev
uv run python scripts/calib_report.py      # tiered scorecard, tier 1 = measured
uv run python scripts/n_trajectory.py      # soil-NO3 trajectory vs mass balance
```

Engine is rev **62.0.0** (`model/TxtInOut/swatplus_rev62.0.0`, arm64; a Linux ELF sits beside
it). One rotation run is ~0.5 s, so sweeps are cheap — prefer measuring to arguing.

`CLAUDE.md` carries the standing cautions. Read them before quoting any number from here.
