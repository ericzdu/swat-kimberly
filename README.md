# swat-kimberly

SWAT+ field model of the USDA-ARS Kimberly, ID GRACEnet site, wrapped as a reinforcement-learning
environment (`swat_gym`) for irrigation and nitrogen management. Question: can a learned policy
raise farm profit without costing water and nitrate?

- Profit is the reward. Sustainability (nitrate leaching) is the second objective, handled by a
  swept-λ profit–leaching frontier and dominance claims, never a single price.
- Leaching is unvalidated on site. N₂O is IPCC Tier 1 accounting, reported, never priced.
- Scope: Exp 1 irrigation, Exp 2 nitrogen. Rotation is fixed.
- Rules and current status: `CLAUDE.md`. Runbook: `EXPERIMENTS.md`. Inputs: `PROVENANCE.md`.
  Open items: `OPEN_ITEMS.md`. Paper: `PAPER.md`, `paper/`.

## Model

- One HRU = one 1 ha field; corn–barley–alfalfa rotation; simulated 2012–2019 (2012 spin-up,
  `nyskip=1`, then seven measured years).
- Built from input files only: the SWAT+ `a10_single_hru` demo `TxtInOut`, edited by
  `scripts/port_*.py`. Engine rev **62.0.0** (Mac Mach-O + Linux ELF vendored in
  `model/TxtInOut/`).
- Sources: GRACEnet measurements (`~/Documents/Kimberly, Idaho/`, extracted to `data/`) win over
  the calibrated ArcSWAT reference model (HRU 119, `data/reference_hru119.csv`), which fills
  unmeasured inputs. Crop params are the collaborator's workbook values (not fitted).
- Weather: measured AgriMet TWFI 1995–2025; an episode samples an 8-year window via `time.sim`.
- `pet_co` = 0.964, fitted to AgriMet grass-reference ETos (PET +0.0 %).
- Yield bias vs measured (workbook params): alfalfa +49.2 %, corn −12.1 % (PROVENANCE §6).
- Read `basin_crop_yld_yr.txt` via `yld(t)` / HRU area; the per-ha column is per cut for alfalfa.

## Layout

- `model/TxtInOut/` — SWAT+ model and engines.
- `src/swat_kimberly/runner.py` — pySWATPlus wrapper (slow reference path).
- `src/swat_gym/` — environment: `fastrunner.py` (fast runs, ~0.17 s), `schedule.py` (actions →
  `management.sch`), `constrainers.py` (repair), `rewarders.py` (profit), `env.py` /
  `monthly_env.py` (gyms), `experiments/`, `tests/` (`fixtures/baseline.json` = regression gate).
- `scripts/` — `build_model.sh`, `port_*.py`, calibration (`calibrate/`, `calibrate_petco.py`),
  checks (`check_param_state.py`, `check_source_data.py`, `compare_reference.py`,
  `calib_report.py`, `percolation_check.py`, `et_*.py`), tables (`paper_tables.py`,
  `exp1_strategy_table.py`), `rerun_exp1.sh`.
- `data/` — extracted measurements and reference-model outputs.
- `runs/` — outputs (gitignored except `calibration.json`, `exp1b_price_ratio.json`,
  `exp1c_cadence_e500.json`).

## Setup and run

```bash
uv sync --extra dev --extra rl
uv run pytest               # add -m slow for parity vs runner.py and nesting gates
uv run python -m swat_kimberly.runner
```

## Build

`bash scripts/build_model.sh` resets `TxtInOut` from the a10 template
(`~/Downloads/a10_single_hru/Scenarios/Default/TxtInOut`) and runs: `extract_primary` →
`port_wgn` → `port_agrimet` → `port_soil` → `port_management` → `port_crops` →
`port_nutrients` → `port_reference_params` → `calibrate_petco --apply`. Idempotent. Extra args
go to `port_nutrients.py` (e.g. `--pet-co X` overrides the calibration). Run
`scripts/check_param_state.py` afterwards.

## macOS notes (handled)

1. The engine links Intel OpenMP; `libiomp5.dylib` is vendored and on the engine's `LC_RPATH`.
2. pySWATPlus 1.3.0 can't detect Mach-O; `runner.py` patches its detector.

## Engine quirks

- A standalone `kill` op is ignored; end crops with `hvkl`.
- `op_data3` on `plnt` is not heat units and crashes the engine; PHU comes from `days_mat`.
- `days_mat`/`yrs_mat` must be written as integers or the `plants.plt` row mis-parses.
- Spring barley must be `warm_annual` (`cold_annual` is fall-sown logic).
- `plants.plt` `harv_idx` is inert here; the harvest index comes from `harv.ops`.
