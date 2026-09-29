# swat-kimberly

**A SWAT+ field model being calibrated into a reinforcement-learning environment for
irrigation and nutrient management, to ask whether a learned policy can raise farm profit
without paying for it in water and nitrate.**

**Profit is the objective the reward maximises; sustainability is the second objective.** It is
not a caveat, though — because there is no defensible market price for nitrate leaching in
Idaho, it is settled by a **profit–leaching frontier** rather than by a price: nitrate enters
the objective only as a swept λ_n whose whole curve is reported, with the λ_n = 0 profit-only
arm always alongside. The result is a dominance claim — at matched profit, which strategy
leaches less — rather than an optimum at a shadow price nobody could defend.

The deliverables are the **environment**, the **evaluation protocol** that makes a comparison
between a learned policy and a searched schedule mean what it appears to mean, and the
**profit–leaching frontier** they produce (`EXPERIMENTS.md`, `PAPER.md`).

Two limits bound every sustainability claim here and are stated wherever one is made: leaching
is unvalidated on site, and N₂O cannot be simulated by SWAT+ at all — it is IPCC Tier 1
accounting, reported and never priced.

Calibration is stage one of that, not a separate project: a policy optimized inside a biased
simulator inherits the bias, and its recommendations are artefacts of the model rather than
agronomy. So this repo's job is to get the environment's yield, water, and N response right
*first*, and to keep the residual error measured and visible so it is clear what an agent may
currently be trusted to optimize.

The protocol matters as much as the environment, for a reason this repo learned the hard way:
because constraints are enforced by **repair** rather than by reward penalty, a cap applied on
one code path and not another changes what is simulated without changing what is priced. It is
invisible in the reward, and it inverted Exp 1's headline once. Objective parity between
competing methods is therefore a *tested* property here, not an assumed one — see
`tests/test_monthly.py::test_openloop_and_policy_paths_agree_on_identical_plan`.

The field is the USDA-ARS Kimberly, ID GRACEnet site — one HRU ≈ one 1-ha field, corn–barley–
alfalfa rotation, simulated 2012–2019 — driven from Python via **pySWATPlus**. Built entirely
from **input files** (no SWAT+ Editor / QSWAT+ GUI), as a clone of the SWAT+ `a10_single_hru`
demo `TxtInOut` edited into the Kimberly scenario, so every calibrated value is a versioned
edit in a `port_*.py` step rather than GUI state.

Calibration targets the **measured GRACEnet yields**. A calibrated ArcSWAT model of the same
field (below) supplies reference values for the many inputs the measurements do not constrain.
`../RuFaS` and `../aquaswat-gym` are siblings and a cross-check on the result — not the point.

Primary data for the site lives in `~/Documents/Kimberly, Idaho/`, and the ports read it
directly: irrigation, crop parameters, measured humidity/wind and reference ET all come from
there via `scripts/extract_primary.py` and `scripts/port_agrimet.py`.

**Every input is traced to its source file in `PROVENANCE.md`** — 25 of the 65 files SWAT+
reads are modified, 2 are new, 38 are untouched template defaults, and nothing is currently
fitted to an outcome. The calibration is a **hybrid**: operation dates, soil, initial nutrients
and basin N parameters come from the ArcSWAT reference (`TxtInOut-2/0001400xx.*`), while the
crop-growth parameters in `plants.plt` are still RuFaS's calibrated values — including the ones
the sensitivity screen ranks most influential.

## Layout
- `model/TxtInOut/` — the SWAT+ model (text input + output files), including vendored
  **rev 62.0.0** engines (`swatplus_rev62.0.0` Mach-O on macOS; `swatplus_62.0.0.linux` ELF for the cluster).
- `src/swat_kimberly/runner.py` — pySWATPlus wrapper (`KimberlySwat`).
- `src/swat_gym/` — management-optimization layer over this model; see `EXPERIMENTS.md`.
  `fastrunner.py` is the hot path, `tests/fixtures/baseline.json` the regression gate.
- `scripts/` — `build_model.sh` plus the six `port_*.py` steps that build `TxtInOut`, and the
  two calibration-check drivers `compare_reference.py` (vs the ArcSWAT reference + GRACEnet)
  and `compare.py` (vs RuFaS).
- `data/` — inputs and results extracted from the ArcSWAT reference model:
  `reference_hru119.csv` (its annual results), `weather_2020.csv`, `solar_2012_2020.csv`.
- `scripts/calibrate/` — `screen.py` (SALib Morris) and `optimize.py` (differential evolution).
- `runs/` — isolated run dirs (git-ignored); source `TxtInOut` stays pristine.
- `PROVENANCE.md` — where every input came from. `PAPER.md` — the paper draft.

The simulation window is **2012–2019** (8 years): a 2012 barley spin-up year skipped by
`print.prt` `nyskip=1`, plus the 2013–2019 GRACEnet rotation — all seven of which have a
measured yield. The reference model stretches its 8-year rotation over a 9-year window by
repeating 2012's operations in 2020; that fabricated year is not simulated here (`PROVENANCE.md`
§1b).

## `swat-gym` — the environment

The RL layer: an agent controlling irrigation and manure/N, with the calibrated
SWAT+ model supplying the dynamics. Calibration quality is what makes this layer worth
running, which is why most of this README is about the model rather than the agent — and why
the residual per-crop error is reported below in the terms an agent will exploit. Plan,
staging, and the open questions: `EXPERIMENTS.md`.

**Phases 0-3 built (2026-07-29).** `schedule.py` turns an action vector into `management.sch`
and `irr.ops`; `constrainers.py` projects infeasible plans onto feasible ones;
`rewarders.py` prices the outcome from USDA NASS Idaho figures with the leaching term kept
separable; `env.py` exposes both an open-loop `evaluate()` and an annual-replay `SwatEnv` with a
`gymnasium` adapter. `port_agrimet.py` now writes **1995-2025**, so an episode samples an 8-year
weather window by rewriting `time.sim` alone — which is what unblocked Experiment 2. Results and
method: `runs/RL_RUN_REPORT.md`.

**Phase 0 (built).** `swat_gym.FastRunner` runs the full 9 years in **0.17 s** (median of 10;
min 0.16) — ~7× faster than `runner.py`'s 1.11 s, and bit-identical to it — by copying inputs
only (65 files / 0.77 MB, derived from `file.cio`) once at construction and trimming
`print.prt` to the five tables the reward reads. The engine alone, writing the untrimmed
output set, takes 0.54 s, so the trimming is most of the win. (All three got ~3× faster once
the containing objects were resized to 1 ha — the engine had been routing a 1432 ha channel.)
A committed fixture pins yields,
water balance, and N-stress days, so swapping in a different SWAT+ build (e.g. a Linux engine
on WSL) gives an immediate pass/fail on build agreement.

```
uv sync --extra dev --extra rl
uv run pytest            # 45 tests, ~13 s  (add -m slow for parity vs runner.py)
```

## Run
```
uv sync
uv run python -m swat_kimberly.runner
```

## macOS toolchain notes (already handled)
Two things make the stock SWAT+ engine + pySWATPlus work on Apple Silicon/macOS:
1. **libiomp5** — the engine links Intel OpenMP. We vendor `libiomp5.dylib` from the
   SWAT+ Editor bundle and bake its dir into the engine's `LC_RPATH`
   (`install_name_tool -add_rpath`), so it runs with no `DYLD_*` env var.
2. **Mach-O detection** — pySWATPlus 1.3.0 only recognizes ELF/PE binaries when
   locating the engine; `runner.py` monkeypatches its detector to accept Mach-O
   magic numbers.

## Build
`bash scripts/build_model.sh` — resets `TxtInOut` from the a10 template and applies the
ports in order (weather → solar → wgn → soil → management → crops → nutrients). Idempotent.
It expects the template at `~/Downloads/a10_single_hru/Scenarios/Default/TxtInOut`.

Extra args pass through to `port_nutrients.py`, e.g. `bash scripts/build_model.sh --pet-co 2.4`
to use the RuFaS PET coefficient instead of the model-native 1.0.

## Status
- [x] Toolchain: engine runs, pySWATPlus drives it, outputs read into pandas.
- [x] Weather: precipitation, temperature, humidity, wind and solar all from the measured
      AgriMet TWFI record (`port_agrimet.py`). Verified by independent re-derivation from
      `weather.csv` — every series reproduces to floating-point identity across all 3288 days.
- [x] Solar radiation: measured AgriMet `SR` replaces SWAT+'s generated constant. Formerly
      `port_solar.py`, which claimed an ArcSWAT gauge it was not reading and wrote a hard
      0.0 MJ/m² on 2019-04-30; retired.
- [x] Soil: reference Portneuf 4-layer profile; HRU = 1 ha, and the routing unit, landscape
      unit, aquifers and channel resized to match it (`port_soil.py`).
- [x] Weather generator: the a10 gridded cell replaced by the reference's own station
      `IDTWINFALLSWS0` (`port_wgn.py`) — it is what generates humidity and wind.
- [x] Management structure (`port_management.py`): 8-yr GRACEnet rotation
      (plant/harvest/kill), **4 GRACEnet manures with measured composition** (reproduces
      N *and* P *and* the 80/5 organic split exactly), **158 measured daily irrigation
      events** — all accepted; water balance confirms irrigation is applied (irr matches
      the measured 418/616/653… mm).
- [x] **Crop growth working.** Root cause was the harvest op format, not heat units:
      `harv`/`hvkl` `op_data1` must be the **plant name** (op_data2 = the `harv.ops` type),
      not the harvest-op name — so harvests never fired and biomass accumulated forever.
      Fixed → full rotation yields each year. (`op_data3` on `plnt` is NOT PHU; leave 0 —
      SWAT+ auto-computes heat units from `days_mat` + climate.)
- [x] Calibrated crop params in `plants.plt` (`port_crops.py`); PET is **Penman-Monteith**
      (`codes.bsn` `pet=1`), which is also what the reference uses (`IPET=1`); nyskip=1.
- [x] Initial soil nutrients, topography, PET coefficient (`port_nutrients.py`).
- [x] Inputs reconciled against the calibrated ArcSWAT reference model (2026-07-27); see
      the table below for everything that changed.
- [x] Comparison vs RuFaS + GRACEnet: `uv run python scripts/compare.py` (reads `runs/latest`,
      so run `runner.py` first). Comparison vs the ArcSWAT reference:
      `uv run python scripts/compare_reference.py` (drives `FastRunner` itself).
- [ ] Auto-irrigation — a *gym design* requirement for the irrigation lever, not a calibration
      fix: every simulated year now carries its measured events.

### `pet_co` — calibrated to 0.964 against measured ETos
SWAT+ `hydrology.hyd` has a `pet_co` PET multiplier, the structural analogue of the RuFaS
`pet_calibration_coefficient` (2.4). RuFaS's 2.4 is **not transferable** and was never used:
SWAT+ Penman-Monteith already produces PET ≈ 1387 mm/yr here, so `pet_co=2.4` would take PET
to 3328 mm/yr, deep percolation to 0, and drive every crop further from the reference through
severe water stress. It was fitted against a much lower internal PET baseline.

The model shipped at the native 1.0 for most of its life, then briefly at **0.81** as a
provisional restore for the deep-percolation collapse under engine rev 62. Since 2026-07-31 it
is **calibrated**, not chosen: `scripts/calibrate_petco.py` fits it to the AgriMet TWFI
**grass**-reference ET series (`ETOS`), which is the definition SWAT+'s Penman-Monteith PET
matches. PET is exactly linear in `pet_co`, so the fit is closed-form.

| | `pet_co=0.81` (was) | **`pet_co=0.964`** (shipped) | `pet_co=1.0` |
|---|---|---|---|
| PET vs measured ETos | −16.0 % | **+0.0 %** | +3.8 % |
| deep perc | 42.6 mm/yr | **1.1** | 0.3 |
| `no3_rchg` | 1.12 kg/ha/yr | **0.02** | 0.01 |
| yield vs GRACEnet | −6.7 % | **−9.8 %** | −11.6 % |

The percolation row is the honest cost of fitting PET to measurement, and it is read at
*measured practice only* — a single point near crop demand, which is where the threshold keeps
drainage near zero. It is not evidence that the channel is dead: raise applied water and both
percolation and nitrate respond (see the water paragraph below, and `scripts/percolation_check.py`).
`esco`/`epco`/the soil profile already match the reference exactly, so the ET/PET difference
against REF (~0.86 vs ~0.51) is an engine difference, not an input error. PROVENANCE §5h,
`OPEN_ITEMS.md` #11.

```bash
uv run python scripts/calibrate_petco.py           # sweep + solve, writes nothing
uv run python scripts/calibrate_petco.py --apply   # write the optimum
```

### Initial soil nutrients — superseded
This model previously depth-weighted the RuFaS per-layer nitrate / labile-P over the 1500 mm
profile (3.27 / 7.06 ppm). The reference instead starts the profile at **zero** nitrate and
organic N with 5 ppm labile P, and charges it with a **350 kg N/ha elemental application in
the 2012 spin-up year**. `port_nutrients.py` now follows the reference; the RuFaS approach is
in the git history.

## The ArcSWAT reference model — where the calibrated inputs come from

Measured GRACEnet yields exist for only five of the nine years, and constrain almost none of
the inputs that produce them. A **calibrated ArcSWAT (SWAT2012) model of the same field** —
HRU 119 / subbasin 14, station `IDTWINFALLSWS0`, Portneuf soil, the same 8-year GRACEnet
rotation and the same **158 measured irrigation events** — reproduces those yields to **+5.1 %
PBIAS**, so its input choices are a defensible prior for everything the measurements leave
open. Its annual results are committed to `data/reference_hru119.csv`, its 2020 weather to
`data/weather_2020.csv`, and its measured solar series to `data/solar_2012_2020.csv`.

It is therefore the source this model's *inputs* were reconciled against (2026-07-27),
superseding several RuFaS-derived choices. What that reconciliation changed:

| Input | was | now (reference) |
|---|---|---|
| `parameters.bsn` `orgn_min` (SWAT2012 `CMN`) | **0.0** — humus organic N never mineralised | **0.0020** |
| Soil `80295` | RuFaS 6-layer to 1500 mm, hyd grp B | 4-layer to 1220 mm, hyd grp **C** |
| Initial soil nitrate / labile P | 3.27 / 7.06 ppm (depth-weighted RuFaS) | **0** / 5 ppm |
| Manure application date | at planting | **April 10** every manure year |
| Harvest index | generic `silage` 0.90, `hay_cut_high` 0.80 (+3000 kg/ha floor) | corn **0.98**, barl **0.52**, alfa **0.95**, eff 1.0, no floor |
| 2012 / 2020 fertiliser | none | Elem-N 350 + Elem-P 320 kg/ha on 3/15 |
| Solar radiation | *generated* — a flat 17.78 MJ/m² every year | measured, 14.8–17.0 MJ/m² |
| Simulation window | 2012–2019 | **2012–2020** (2020 repeats the rotation) |
| `n_uptake` / `n_perc` / `denit_exp` / `surq_lag` / `can_max` | 20 / 0.10 / 1.40 / 4.0 / 1.0 | 10 / 0.20 / 0.001 / 1.0 / 0.0 |
| `print.prt` `nyskip` | 2 (2013 had no HRU diagnostics) | **1** |
| Weather-generator station | a10 gridded cell `426n1144w`, 1145 m | reference station **`IDTWINFALLSWS0`**, 1207 m |
| Routing unit / aquifer / channel / `object.cnt` area | 1431.72 ha (a10 catchment) | **1.0 ha**, matching the HRU |

**Six of those rows were superseded on 2026-07-28**, when every file in
`~/Documents/Kimberly, Idaho/` was audited against the built model. Where the primary source and
the reference model disagree, the source now wins:

| Input | reference said | primary source says |
|---|---|---|
| `orgn_min` | 0.0020, unexplained | **0.0010** — the value the site's own six-configuration sweep against *measured* buried-bag N mineralisation accepted (+4.7 % vs a target 209.8 kg N/ha/yr; SWAT defaults score −36.2 %) |
| Initial soil nitrate / labile P | **0** / 5 ppm | **9.33** / **8.13** ppm — the measured April-2013 profile, mass-weighted. The reference's own internal state was 10.7 ppm nitrate and 9.45 ppm P, so the zero was an initialisation placeholder, not a claim about the soil |
| 2012 / 2020 fertiliser | Elem-N 350 + Elem-P 320 on 3/15 | **none.** A device to charge a zero-nitrate profile; the record shows the spring-manure plot received nothing in 2012 |
| Barley harvest index | 0.52 | **0.54** — 0.52 was the sheet's `HVSTI` column, not its harvest column |
| Simulation window | 2012–**2020** | **2012–2019.** 2020 was fabricated *and* scored |
| Bulk density | plot 203's profile | the **four-plot measured mean** |
| Manure incorporation | surface broadcast, no tillage | **disked to 15 cm** on each application date, per Bierer et al. 2022 §2.3 |

Two bugs surfaced during the reconciliation:

- **SWAT+ rev 60.5.7 silently ignores a standalone `kill` operation.** It never reaches
  `mgt_out.txt`. The reference terminates crops with `harvonly` + `kill`; transcribing that
  literally left the 2017 alfalfa stand alive into 2018, where the corn planting logged
  `PLANT_ALREADY_GROWING` and "corn" harvested **155 t/ha** of runaway alfalfa. Use `hvkl`.
- **`op_data3` on a `plnt` op is not a PHU override** — setting it makes the engine exit 174.
  SWAT+ derives heat units from `plants.plt` `days_mat`; sweeping that (85→200 days) does not
  reproduce the reference's pinned PHU behaviour in either direction.

## Calibration status (annual dry Mg/ha)

`uv run python scripts/compare_reference.py` — the standing answer to "is this environment
accurate enough to optimize inside yet?"

| yr | crop | SWAT+ | reference | GRACEnet | err vs meas | irr (mm) | ref irr |
|---|---|---|---|---|---|---|---|
| 2013 | corn | 21.5 | 21.81 | 22.10 | −2.9 % | 605.0 | 604.2 |
| 2014 | barl | 7.3 | 6.51 | **5.90** | +23.5 % | 418.3 | 400.8 |
| 2015 | alfa | 8.8 | 9.87 | 9.00 | −1.9 % | 616.2 | 616.3 |
| 2016 | alfa | 15.3 | 15.79 | 14.79 | +3.2 % | 652.5 | 652.8 |
| 2017 | alfa | 16.7 | 16.38 | 16.16 | +3.6 % | 585.5 | 585.5 |
| 2018 | corn | 20.4 | 25.44 | 22.93 | −11.0 % | 558.8 | 558.9 |
| 2019 | barl | 6.7 | 6.93 | **8.78** | −24.1 % | 502.4 | 520.8 |

**RMS per-year error 13.6 %**, PBIAS −3.0 % (2026-07-31, after calibration to measurement —
`scripts/calibrate/optimize.py`, PROVENANCE §6). Per-year is the number that matters here; see
below.

**Irrigation is measured input, not a result.** Both models were given the same events, so this
tests transcription, not behaviour. Two changes since the audit: 2019 now uses the
**pivot-controller export (502.4 mm)** rather than the summary workbook's 520.7, which rounded
every 0.96-in event to 1.00 in; and **2020 is no longer simulated** — it was a fabricated
repeat of the 2012 barley year receiving zero irrigation in a year when 757.7 mm was applied,
and `nyskip` was not excluding it from the scores.

| crop | before calibration | **after** vs GRACEnet | per-year |
|---|---|---|---|
| alfalfa | −12.9 % | **+2.2 %** (n=3) | −1.9 / +3.2 / +3.6 |
| corn | −10.9 % | **−7.0 %** (n=2) | −2.9 / −11.0 |
| barley | +2.3 % | **−4.9 %** (n=2) | **+23.5 / −24.1** |

**Do not read the per-crop figures as uniform improvement — they still cancel within a crop.**
Barley's −4.9 % is 2014 at **+23.5 %** against 2019 at **−24.1 %**; before calibration the same
statistic read **+2.3 %** while the underlying years were +52.5 % and −31.6 %. That
cancellation is why the objective scores per-year error rather than per-crop bias.

**The residual is a structural artefact, not a missing parameter.** `plant.ini` declares a
three-plant community, and alfalfa is a perennial: SWAT+ keeps it resident and competing for
light and nitrogen in **every** year of the simulation, including 2013–14 before it is ever
planted. Removing it from the community entirely takes 2018 corn from 15.09 to **24.32 t/ha**
against a measured 22.93, and its N uptake from 129 to **321 kg/ha** against a measured 270.7 —
but it also silently deletes the alfalfa years, so it is a diagnostic, not a fix. Rev 60.5.7
offers no way to end a perennial's residency: `kill` after `hvkl` is byte-for-byte ignored,
there is no `lu_change` decision-table action (`lum.dtl`'s `grow_init`/`grow_end` are `hlt`-only),
and `file.cio` has no `lum.upd` slot. **±15 % per crop is therefore not reachable on this
engine.**

**All seven rotation years are measured, including both barley years** (2014: 5.90, 2019: 8.78
Mg/ha). Earlier versions of this README said barley had no measurement and was therefore only
checkable against the reference model. That was wrong — the figures were in
`GraceNet crop and manure amounts.xlsx` the whole time. Barley is the model's worst crop
against measurement, not merely against another model.

**This is the blocking calibration issue for the RL work.** The bias is not a level shift an
agent would ignore; it is a *relative price* between the crops the agent chooses among, so the
rotation lever would learn to prefer alfalfa for reasons that are model error. Irrigation and
manure levers are less exposed, since their bias is within-crop. Until the per-crop gap closes,
results stay relative to the model's own baseline (see the guardrail in `EXPERIMENTS.md`).

> **This paragraph is why the rotation lever was cut on 2026-09-09.** The reasoning above
> predates the decision by weeks and was never answered: the crop bias is a *relative price*
> among the crops a rotation lever chooses between, so that lever reads a corrupted ratio.
> Holding the rotation fixed makes the bias **common-mode** across every arm compared instead
> of **differential** between them. Levels still carry it; differences no longer do. Scope is
> now two levers — irrigation (Exp 1) and nitrogen (Exp 2). See `CLAUDE.md`.

**A fitted parameter set is now applied** (`runs/calibration.json`,
`scripts/calibrate/optimize.py`; full accounting in PROVENANCE §6). Two of its sixteen
parameters were deliberately held back at their sourced values — `n_perc` and `fr_hum_act`
were buying ~6 kg/ha on the nitrate term while making yield worse — and the honest caveat is
that **`corn.bm_e` = 64.5 is absorbing the resident-perennial artefact, not measuring
radiation-use efficiency**. Corn's agreement is fitted, not validated.

An earlier version of this paragraph rejected a fit partly because "four of thirteen parameters
optimize to their bounds". That argument was weaker than it read: at least one of those four
(`plants.plt:corn.harv_idx`) is **inert** — the engine takes the harvest index from `harv.ops`
for this rotation — so it was a dead dimension parked at a bound, not a binding constraint
(PROVENANCE §5j).

Water, 2013–2019 mean: ET 836, PET 1157, irrig 563 mm/yr.

**Percolation is threshold-behaved in applied water, not collapsed.** Re-measured 2026-08-06
(`scripts/percolation_check.py`): below crop demand nothing drains; above it, drainage and
nitrate rise together — 9 → 162 mm/yr as applied water goes 3,939 → 5,778 mm, at a physically
plausible **13.6–26.5 mg/L**, above the 10 mg/L drinking-water standard that motivates the
paper. An earlier reading of this section reported a "drainage collapse" and an inert `perco`
from a single point at measured practice; that is superseded (CLAUDE.md rule 10, OPEN_ITEMS
#11). There is nothing here to rescue.

**So the leaching column is usable, with two limits that bound every sustainability claim.**
It ranks strategies *within the model* and can carry the λ_n frontier. But it is **not
validated against measurement** at this site, so magnitudes are not field claims; and at
measured practice the signal is **sparse across windows** — 2.40 kg/ha/yr in the 2013-start
window and ~0 in the other four — so leaching differences carry high between-window variance.
Both limits are load-bearing precisely because sustainability is a real objective here and not
a footnote: optimizing *for* a channel is the regime in which an unvalidated one gets exploited.

**PET is scored against measurement, not against the reference model.** The AgriMet TWFI
station records grass-reference ET; after `pet_co` was calibrated to it, SWAT+ PET is **+0.0 %**
(1157 vs 1164). The ArcSWAT reference model is **+20.8 %** against the same measurement — so on
PET this model is closer to the data than the model it was calibrated toward.

**Reading `basin_crop_yld_yr.txt` correctly:** `harv_area(ha)` accumulates one field-area per
**cut**, so SWAT+'s own `yld(t/ha)` column is a **per-cut** figure for multi-cut alfalfa. GRACEnet
reports annual totals — `compare.py` therefore uses `yld(t)` / true HRU area. Comparing the raw
`yld(t/ha)` column against GRACEnet (as an earlier version of this README did) understates alfalfa
by the number of cuts and produced a spurious "2015 alfalfa matches measured" result.

## Why yields still disagree — N was one cause, and it is fixed

**Resolved: the N-limitation was an unset parameter, not model structure.** This README
previously argued that only ~14 %/yr of organic manure N became plant-available, leaving corn
and barley N-limited (2018 corn ran **41 days** of `strsn`, alfalfa zero) and attributed it to
"a genuine structural difference between SWAT+'s and RuFaS's organic-N release."

That was wrong. The cause was `parameters.bsn` **`orgn_min = 0.0`** in the SWAT+ template — the
humus active organic-N mineralisation rate factor (SWAT2012 `CMN`), which at zero means humus
organic N never mineralises at all. The reference uses 0.0020. Setting it, in isolation:

| `orgn_min` | 2013 corn | 2018 corn | N-stress 2018 | N uptake 2018 |
|---|---|---|---|---|
| 0.0000 (old) | 9.97 | 11.12 | 41.2 d | 118 |
| 0.0020 (reference) | 14.34 | 15.98 | 25.7 d | 178 |

After the full reconciliation, **N stress is zero in every year except 2018 (33 d) and 2019
(3 d)** — so N is no longer the binding constraint, and the remaining yield gap is not an N gap.

**What remains is biomass accumulation, and it is crop-specific.** Peak standing biomass:

| | SWAT+ peak | reference implies |
|---|---|---|
| 2018 corn | 18.5 t/ha | ~25 t/ha |
| 2014 barley | **4.5 t/ha** | ~12.5 t/ha |
| 2016 alfalfa (per cut) | 10.4 t/ha | ~17 t/ha total |

### Barley: found, fixed, and still not closed

The Long-Term Manure study on this site measured whole-plant barley dry matter at **12.8–15.9
Mg/ha in 2013 and 13.5–20.4 in 2017, mean 15.6** — against this model's then-peak of 4.5.
(**Caveat, 2026-07-28:** that study is a *different plot and rotation* — barley/sugarbeet/
wheat/potato, receiving 951.6 kg manure N/ha in 2013 per its own `Summary` sheet — so it is a
plausibility envelope for barley biomass at this site, **not** a calibration target for the
GRACEnet plot, and it is not used as one.) That
established the gap as biomass, not harvest index (measured HI is ≈ 0.36, *below* the model's
0.52) and not a plant-part mismatch (LT grain 6.4 Mg/ha against the GRACEnet plot's 5.90/8.78).

**The cause was the plant type.** The site documents **1800 heat units** for spring barley in
`Plant Harvest Dates` — a column ported nowhere, so SWAT+ was deriving the target from
`plants.plt days_mat`, which the site's crop table does not contain either. But `days_mat` was
a red herring. Barley was typed **`cold_annual`** (from the sheet's `IDC = 5`), and SWAT+ rev
60.5.7 handles cold annuals as fall-sown crops that bank heat units before dormancy. On an
April-sown crop that collapsed the target to ~530 degree-days: barley matured **46 days after
planting**, then stood in the field for another 66–85 days with biomass frozen to the kilogram
and every stress term at exactly 0.000.

Setting `plnt_typ = warm_annual` and changing nothing else restores the growth window to 97 and
110 days and realizes **1517 and 1766** heat units — within 6–16 % of the documented 1800,
untuned. Corn is the control: already `warm_annual`, it already realized 1889/1888 against the
same documented 1800 at its own stock `days_mat`.

Barley moved from **−69.9 % to −56.2 %**, and after the resident-perennial fixes to **−17.9 %**.

**Correction (2026-07-28): the earlier "LAI ceiling" explanation was wrong.** This section used
to say 2014 barley was "limited purely by radiation interception with LAI at its `lai_pot`
ceiling of 4.0". That cannot be the mechanism: with `ext_co` 0.65, LAI 4.0 already intercepts
`1 − exp(−0.65 × 4) = 93 %` of PAR, so raising `lai_pot` to 6.0 buys about 6 %. The actual
constraint was that the canopy spent few days anywhere near that ceiling — and the reason was
that ~2.0 of the reported LAI was **not barley at all** but the resident alfalfa's `lai_min`
floor (see the calibration section above).

Two levers were checked and are *not* the answer:

- **`days_mat`.** Sweeping it under the corrected plant type moves realized PHU 1517 → 1872 but
  moves 2014 yield the *wrong way* (2.42 → 1.77 t/ha), because the LAI curve fractions stretch
  with the PHU target and delay canopy closure. It is left at stock 105, since it has no source
  value and moving it trades heat-unit fidelity against fit.
- **Solar radiation.** Porting the measured series (replacing SWAT+'s generated flat
  17.78 MJ/m²) moved PET *further* from the reference, 1336 → 1265 vs 1407. Porting the
  reference's weather-generator station afterwards brought PET to 1387 (−1.4 %), so the two
  together resolved PET — but barley moved the wrong way, so radiation is not the missing lever.
- **Weather generator.** The station in use (`426n1144w`, 42.619/−114.375, 1145 m) is close to
  the site; its monthly climatology is broadly consistent with the reference wgn. Note the two
  models express humidity differently — SWAT+ `dew_ave` here is relative humidity (0.27–0.85),
  SWAT2012 `DEWPT` is dewpoint °C.

Also tested and rejected earlier: `codes.bsn` `carbon` 0 → 1 (CENTURY) makes things worse, so
the shipped `carbon=0` remains the better of the two available models.

### What the stress and N-budget variables say now

Per-year totals from the reconciled run (`hru_pw_yr.txt`, `basin_nb_yr.txt`; stresses are
days, N in kg/ha):

| yr | crop | strsn | strsw | strstmp | fertn | fixn | nuptake |
|---|---|---|---|---|---|---|---|
| 2013 | corn | 0.0 | 0.0 | 10.4 | 569 | 0 | 251 |
| 2014 | barl | 0.0 | 0.0 | 16.6 | 936 | 0 | 74 |
| 2015 | alfa | 0.0 | 34.9 | 27.1 | 0 | 379 | 635 |
| 2016 | alfa | 0.0 | 74.7 | 75.5 | 0 | 548 | 628 |
| 2017 | alfa | 0.0 | 67.7 | 67.7 | 0 | 411 | 467 |
| 2018 | corn | 26.6 | 0.0 | 10.0 | 362 | 0 | 139 |
| 2019 | barl | 0.3 | 0.0 | 15.8 | 223 | 0 | 101 |
| 2020 | barl | 0.0 | 0.0 | 21.1 | 350 | 0 | 122 |

Three things worth carrying forward:

- **The annual crops are not water-limited; the alfalfa years are.** `strsw` is exactly zero
  in every corn and barley year and runs 35–75 days in the alfalfa stand — the opposite of
  the pattern assumed before the reconciliation. Alfalfa is nonetheless the crop this model
  *over*-predicts, so its water stress is not what is holding the annuals back.
- **Temperature stress is present everywhere** (10–76 days) and has not been investigated.
- **Uptake, not supply, limits the annuals.** 2014 barley takes up 74 kg N/ha against 936
  applied; 2018 corn 139 against 362. Adding N is not the lever — which is why the yield gap
  survived fixing `orgn_min`.
