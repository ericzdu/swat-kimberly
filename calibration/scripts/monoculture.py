#!/usr/bin/env python3
"""Continuous monoculture runs — one crop, every year, for all seven site crops.

Purpose: read each crop's **nutrient and water stress** (`hru_pw_day.strsn`, `strsw`) under a
common management, so the crops can be compared without the rotation confounding them.

Management is deliberately uniform across crops so the *crop* is the only thing that varies:

* **Water is not limiting.** Auto-irrigation via the shipped `irr_str9_unlim` decision table —
  irrigate 9 mm at 100 % efficiency when plant water stress drops below 0.9, unlimited
  source. So `strsw` should stay near zero and `strsn` carries the signal.
* **Nutrients are not limiting either**, by default. The `auto_fert_n` / `auto_fert_p`
  decision tables fertilise to demand: 50 kg/ha of elemental N or P whenever that crop's
  stress factor falls below 0.90, capped at 5 N and 2 P events per year. So `strsn` and
  `strsp` should also stay near zero, and what the run reports is the crop's *demand* —
  read `fertn_kg_ha_yr` in the summary — rather than its response to one imposed rate.
  `--fert constant` restores the old single `--n-rate` broadcast at emergence.
* Planting and harvest dates are the site workbook's (`Plant Harvest Dates` sheet), not guesses.

Two things this run is *not*:

1. **Not calibrated for four of the seven.** `port_crops.py` only maps CSIL/BARL/ALFA. Potato,
   pinto beans, winter wheat and sugarbeet get the workbook's parameters written here, but they
   have never been refit against a measured yield at this site the way corn/barl/alfa were, and
   corn's `bm_e` in particular absorbs a resident-perennial artefact. Cross-crop yield rankings
   are therefore **not** a site result.
2. **Not the calibrated rotation.** `plant.ini` is rewritten to a single-plant community, which
   deliberately removes the resident-alfalfa PAR/water draw that the three-plant `kimb_comm`
   imposes on every year. That is the right choice for a monoculture but means these runs are
   not comparable to Exp 1-4 numbers.

`model/TxtInOut` is never touched: every run is built in its own copy.

    uv run python scripts/monoculture.py                       # all 7, 18 yr, auto N + P
    uv run python scripts/monoculture.py --crops CSIL ALFA     # subset
    uv run python scripts/monoculture.py --fert constant --n-rate 0   # unfertilised, max strsn
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))  # for port_crops.COLMAP

from swat_kimberly.runner import KimberlySwat  # noqa: E402

TIO = ROOT / "model" / "TxtInOut"
CROP_CSV = ROOT / "data" / "crop_params_swat.csv"
ET_FITTED = ROOT / "data" / "et_fitted.json"
#: Per-crop ``days_mat`` tuned so the engine's heat units to maturity equal the workbook's
#: ``Plant Harvest Dates`` column (written by ``scripts/et_phu.py``). SWAT+ has no PHU field;
#: this is the only way the sheet's number reaches the model.
ET_DAYS_MAT = ROOT / "data" / "et_days_mat.json"
#: Per-crop biomass/nutrient-uptake fit (``scripts/biomass_calibrate.py``, since 2026-10-23):
#: ``bm_e``/``tmp_opt``/``tmp_base`` and one N and one P factor on the workbook's DEFAULT
#: BN1-3/BP1-3. Applied by :func:`apply_biomass_fit` on the ET-run path only.
BIOMASS_FITTED = ROOT / "data" / "biomass_fitted.json"
#: The workbook's DEFAULT N/P uptake block (``scripts/port_np_defaults.py``). The collaborator
#: asked for these, not the calibrated block, as the base the uptake factors multiply.
NP_DEFAULT = ROOT / "data" / "crop_np_default.csv"
#: HRU-level hydrology constants for the ET runs, held for every crop and NOT fitted:
#:
#: * ``epco`` 1.0 -- advised to the project, adopted 2026-09-11, and there is nowhere for it to
#:   go: it is a *compensation* factor capped at 1.0, and measured on 2026-09-24, ``epco`` 2.0
#:   gives ET identical to 1.0 for every crop tested. It cannot compensate for anything.
#: * ``pet_co`` 1.0 -- collaborator's instruction, 2026-09-15. It is a linear multiplier on
#:   PET (``et_pot.f90``: ``pet_day = pet_co * pet_day``), basin-wide not crop-specific, and
#:   with full daily weather PET needs no adjustment. The 2026-09-11 fit had it at 1.18-1.59
#:   per crop (archived as ``data/et_fitted_2026-09-11_petco.json``).
ET_HYD_FIXED = {"epco": 1.0, "pet_co": 1.0}

#: ``esco`` is fitted again as of 2026-09-24, but **basin-wide** (one value for all seven crops,
#: like ``pet_co``) rather than per crop: it is a soil property, so a per-crop value would carry
#: the same objection the collaborator raised against a per-crop ``pet_co``. It is not a minor
#: knob under the windowed irrigation -- 0.01 vs the fitted 0.48 is 17.5 % vs 8.3 % mean |PBIAS|
#: -- but it buys that by shifting ET from transpiration to bare-soil evaporation; see
#: ``et_calibrate`` for the control and the partition caveat. (An earlier note here called it
#: worth "under 2 points": that was measured under the old stress-triggered irrigation, where
#: the soil was dry regardless, and does not hold now.) 0.5 is the advised value and the
#: regularisation anchor.
ET_ESCO_DEFAULT = 0.5

#: The `Plant Harvest Dates` sheet, ported by `scripts/port_dates.py`. Read rather than
#: hand-typed since 2026-09-24: the emerge/harvest dates were transcribed here correctly, but
#: the sheet's *irrigation start/end* columns were never read at all, and those turn out to be
#: the dominant control on ET (see `write_irrigation_dtl`).
DATES_CSV = ROOT / "data" / "plant_harvest_dates.csv"


def _load_dates() -> tuple[dict, dict]:
    """(CROPS, IRR_SHEET) from ``data/plant_harvest_dates.csv``."""
    if not DATES_CSV.is_file():
        raise SystemExit(f"missing {DATES_CSV.relative_to(ROOT)}; "
                         f"run `uv run python scripts/port_dates.py` first")
    df = pd.read_csv(DATES_CSV).fillna("")

    def md(v) -> tuple[int, int] | None:
        s = str(v).strip()
        if not s:
            return None
        m, d = s.split("-")
        return int(m), int(d)

    crops, irr = {}, {}
    for _, r in df.iterrows():
        harvests = [md(r[c]) for c in ("harv1", "harv2", "harv3", "harv4")]
        crops[r["crop"]] = (r["plants_plt"], md(r["emerge"]),
                            [h for h in harvests if h is not None])
        irr[r["crop"]] = (md(r["irr_start"]), md(r["irr_end"]))
    return crops, irr


#: workbook crop -> (plants.plt name, emerge (mon,day), harvest dates [(mon,day), ...])
#: Alfalfa is perennial with four cuttings.
CROPS: dict[str, tuple[str, tuple[int, int], list[tuple[int, int]]]]
#: workbook crop -> (irrigation start (mon,day), irrigation end (mon,day)), sheet verbatim.
IRR_SHEET: dict[str, tuple[tuple[int, int], tuple[int, int]]]
CROPS, IRR_SHEET = _load_dates()

#: The sheet's alfalfa footnote, verbatim: "Alfalfa irrigation is stopped one week before
#: harvesting and restarted the day after." Applied only to alfalfa — every annual's sheet
#: `irrigation end` already sits 7-16 days before its harvest, so for those the rule is
#: already baked into the column and re-deriving it would silently move the date.
STOP_BEFORE_CUT_DAYS = 7
RESTART_AFTER_CUT_DAYS = 1

#: Already ported and then refit by calibrate/optimize.py — do NOT overwrite these from the
#: workbook, that would silently reset the calibration to book values.
ALREADY_CALIBRATED = {"corn", "barl", "alfa"}

#: plants.plt name -> harv.ops entry. This is not cosmetic: the generic `grain` entry carries
#: `harv_idx = 0.0`, so using it harvests almost nothing and the run reports ~0.03 t/ha.
#: Only the three site crops have a *fitted* op. The other four get one built from the workbook
#: by `write_harvest_op`, so nothing here is invented — the workbook is the calibration source.
HARVEST = {"corn": "gn_corn", "barl": "gn_barl", "alfa": "gn_alfa"}

#: SWAT IDC -> harv.ops `harv_typ`. 1/2 annual legume, 3 perennial legume, 4 warm annual,
#: 5 cool annual, 6 perennial. Crops whose workbook HI_OVR exceeds 1 are root/tuber crops, whose
#: harvest index is expressed on a fresh-tuber basis; those take `tuber` regardless of IDC.
IDC_TYP = {1: "grain", 2: "grain", 3: "biomass", 4: "grain", 5: "grain", 6: "biomass"}

#: plants.plt token index -> workbook column, mirroring port_crops.COLMAP.
COLMAP = {
    5: "BIO_E", 6: "HVSTI", 7: "BLAI", 8: "FRGRW1", 9: "LAIMX1", 10: "FRGRW2",
    11: "LAIMX2", 12: "DLAI", 15: "RDMX", 16: "T_OPT", 17: "T_BASE",
}

#: The shipped `irr_str9_unlim` decision table references this, but irr.ops does not define it.
#: 9 mm per event at 100 % efficiency (collaborator, 2026-09-15; was 25 mm x 0.85 = 21.25 mm
#: applied). For an ``unlim`` source the engine applies ``amt_mm * eff_frac * (1 - sumq_frac)``
#: straight from this row (rev 62 ``actions.f90``, ``irr_demand``); the table's own ``const``
#: is only a demand figure for non-unlimited sources, but :func:`add_sprinkler` rewrites it to
#: the same 9 mm so the two files agree. The table's per-year cap (``const2``) is never
#: incremented on the ``irr_demand`` path, so 9 mm events are not throttled by it.
IRR_MM, IRR_EFF = 9.0, 1.0
SPRINKLER_ILM = (f"sprinkler_ilm       {IRR_MM:8.5f}       {IRR_EFF:.5f}       0.00000       0.00000"
                 "       0.00000       0.00000       0.00000  auto-irrigation, added by "
                 "monoculture.py")


def patch_plants(workdir: Path, plt_name: str, *, workbook_all: bool = False) -> str | None:
    """Write the workbook's parameters for an unported crop. Returns a note, or None.

    ``workbook_all=True`` is the ET-calibration mode (decided 2026-09-11): every one of the
    seven crops, the three site-calibrated ones included, takes the workbook's calibrated
    block verbatim across the full ``port_crops.COLMAP`` column set, plus ``days_mat`` from
    ``data/et_days_mat.json`` where one has been tuned. The nutrient-fit values the template
    carries for corn/barley/alfalfa (``bm_e``, the corn canopy curve, ``days_mat``) are
    *not* the sheet, and the ET work is specified against the sheet. ``lai_pot`` (BLAI) is
    written here too, as the fit's starting anchor; :func:`apply_et_fit` overlays the fit.
    """
    if plt_name in ALREADY_CALIBRATED and not workbook_all:
        return None
    code = next(k for k, v in CROPS.items() if v[0] == plt_name)
    row = pd.read_csv(CROP_CSV).set_index("CPNM").loc[code]
    if workbook_all:
        import port_crops
        from swat_gym.params import set_value
        colmap = {i: c for i, (c, _) in port_crops.COLMAP.items()}
        days_mat = (json.loads(ET_DAYS_MAT.read_text()).get(plt_name)
                    if ET_DAYS_MAT.is_file() else None)
        h = workdir / "hydrology.hyd"
        text = h.read_text()
        for col, val in {**ET_HYD_FIXED, "esco": ET_ESCO_DEFAULT}.items():
            text = set_value(text, "hydrology.hyd", "hyd1", col, val)
        h.write_text(text)
    else:
        colmap, days_mat = COLMAP, None
    path = workdir / "plants.plt"
    lines = path.read_text().splitlines(keepends=True)
    for i, line in enumerate(lines[2:], start=2):
        toks = line.split()
        if not toks or toks[0] != plt_name:
            continue
        # COLMAP keys are 0-based token indices into the split line, exactly as
        # port_crops.py uses them. Indexing at `idx - 1` shifts every parameter one column
        # left -- BIO_E into days_mat, BLAI into harv_idx -- and the run still completes,
        # reporting plausible-looking nonsense. Verified against the header: toks[5] is bm_e.
        for idx, col in colmap.items():
            toks[idx] = f"{float(row[col]):.5f}"
        if days_mat is not None:
            toks[4] = str(int(days_mat))  # rev 62 reads days_mat as a Fortran integer
        # Rebuild in plants.plt's fixed width, preserving any trailing description.
        desc = toks[-1] if not _is_float(toks[-1]) else ""
        nums = toks[1:-1] if desc else toks[1:]
        lines[i] = (f"{plt_name:<22}" + "".join(f"{t:>14}" for t in nums)
                    + (f"  {desc}" if desc else "") + "\n")
        path.write_text("".join(lines))
        note = f"plants.plt[{plt_name}] <- workbook ({code})"
        return note + (f", days_mat={days_mat}" if days_mat is not None else "")
    raise SystemExit(f"{plt_name} not found in plants.plt")


#: ``plants.plt`` columns the ET fit may write, per crop. ``lai_pot`` (BLAI) has been fitted
#: since the first ET fit; the four canopy-curve columns joined it on 2026-09-24, authorised
#: after measuring what they buy on the full-year monthly target (corn R2 0.76 -> 0.83, barley
#: 0.76 -> 0.84, sugarbeet 0.79 -> 0.84, potato 0.42 -> 0.72). They are a departure from the
#: 2026-09-11 "workbook verbatim" rule and ``runs/et_raw/workbook_check.csv`` flags each one.
ET_PLANT_KNOBS = ("lai_pot", "frac_hu1", "frac_hu2", "hu_lai_decl", "dlai_rate")
#: Hydrology columns the ET fit may write; all basin-wide, none per crop.
ET_HYD_KNOBS = ("esco",)

#: Heat units to maturity, fitted per crop since 2026-09-25 at the collaborator's request
#: (sugarbeet peaked and senesced ahead of eeMetric; "tune them for every other crop").
#:
#: SWAT+ rev 62 has no PHU column. ``plant_init`` derives ``phumat`` once, at start-up, from
#: ``days_mat`` and the weather generator's monthly means — which is why ``et_days_mat.json``
#: could not push sugarbeet past ~2020: a whole wgn year at base 4 degC only holds 2192. But
#: ``proc_cal`` runs *after* ``proc_hru``, and ``calibration.cal``'s ``phu_mat`` writes
#: ``plcur%phumat`` directly (``cal_conditions.f90``), and nothing resets it at planting. Measured
#: on sugarbeet: absval 2300 -> 2321 and 2600 -> 2622 engine heat units, against 2020 without it
#: (the estimator reads ~1 % high at every setting). The override supersedes ``days_mat``
#: entirely: the engine reads ``days_mat`` for nothing else.
#:
#: Two template edits are needed and neither is optional. ``file.cio``'s ``chg`` line must name
#: ``calibration.cal`` (the shipped ``null`` skips the read), and ``cal_parms.cal`` must type
#: ``phu_mat`` as ``plt`` — shipped as ``hru``, it is routed to ``cal_parm_select``, which has no
#: case for it, and the change is dropped with no message.
ET_PHU_KNOB = "phu_mat"


def default_phu(workdir: Path, plt_name: str) -> float:
    """The engine's own ``days_mat = 0`` heat units to maturity for this plant.

    ``plant_init.f90`` verbatim: 0.95 x the sum over a 365-day year of
    ``max(0, (tmp_max_ave + tmp_min_ave)/2 - tmp_base)`` from the HRU's weather-generator station.
    Alfalfa's sheet PHU is "default", and this is that default.
    """
    from swat_gym.params import get_value

    tbase = get_value((workdir / "plants.plt").read_text(), "plants.plt", plt_name, "tmp_base")
    sta = (workdir / "weather-sta.cli").read_text().splitlines()[2].split()[1]
    lines = (workdir / "weather-wgn.cli").read_text().splitlines()
    i = next(k for k, ln in enumerate(lines) if ln.split()[:1] == [sta])
    months = [ln.split() for ln in lines[i + 2:i + 14]]
    days = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
    return 0.95 * sum(n * max(0.0, (float(m[0]) + float(m[1])) / 2.0 - tbase)
                      for n, m in zip(days, months))


def sheet_phu(workdir: Path, code: str) -> float:
    """The PHU anchor: the ``Plant Harvest Dates`` sheet's heat units, or the engine default
    where the sheet says "default" (alfalfa)."""
    v = str(pd.read_csv(DATES_CSV).set_index("crop").loc[code, "sheet_phu"]).strip()
    return float(v) if v.replace(".", "", 1).isdigit() else default_phu(workdir, CROPS[code][0])


def enable_phu_override(workdir: Path) -> None:
    """Point ``file.cio`` at ``calibration.cal`` and type ``phu_mat`` as a plant parameter."""
    import re

    cio = workdir / "file.cio"
    cio.write_text(re.sub(r"^(chg\s+\S+\s+)\S+", r"\1calibration.cal", cio.read_text(),
                          count=1, flags=re.M))
    cal = workdir / "cal_parms.cal"
    cal.write_text(re.sub(r"^(phu_mat\s+)hru\b", r"\1plt", cal.read_text(), flags=re.M))


def build_phu_cal(plt_name: str, phu: float) -> str:
    """``calibration.cal`` setting this plant's heat units to maturity to ``phu``.

    One element (HRU 1 — these are single-HRU runs) and one ``plant`` condition. The element
    list is not optional: with none, ``cal_parmchg_read`` sizes a ``plt`` change by the number of
    plant *database* rows and ``cal_conditions`` then indexes ``pcom`` (per HRU) with them.
    """
    return ("calibration.cal: heat units to maturity, written by scripts/monoculture.py\n1\n"
            "NAME CHG_TYP VAL CONDS LYR1 LYR2 YEAR1 YEAR2 DAY1 DAY2 OBJ_TOT\n"
            f"phu_mat absval {phu:.1f} 1 0 0 0 0 0 0 1 1\n"
            f"plant = 0 {plt_name}\n")


def write_phu_cal(workdir: Path, plt_name: str, phu: float) -> None:
    enable_phu_override(workdir)
    (workdir / "calibration.cal").write_text(build_phu_cal(plt_name, phu))


def load_et_fit() -> tuple[dict, dict]:
    """``(shared, per_crop)`` from ``data/et_fitted.json``; ``({}, {})`` when absent.

    Two shapes are accepted. The current one separates the basin-wide values from the per-crop
    ones, because as of 2026-09-24 ``esco`` and the irrigation trigger are fitted once for the
    whole site rather than per crop::

        {"shared": {"esco": .., "epco": .., "pet_co": .., "irr_sw_frac": ..},
         "crops":  {"corn": {"lai_pot": .., "frac_hu1": .., ..}, ..}}

    The flat ``{plants_plt: {..}}`` shape the fits up to 2026-09-15 wrote is still read, so the
    archived ``data/et_fitted_2026-*.json`` files stay loadable for comparison.
    """
    if not ET_FITTED.is_file():
        return {}, {}
    data = json.loads(ET_FITTED.read_text())
    if "crops" in data:
        return data.get("shared", {}), data["crops"]
    # Flat/legacy: the hydrology values were repeated identically under every crop.
    shared = {k: v for k, v in next(iter(data.values()), {}).items()
              if k in ("esco", "epco", "pet_co")}
    return shared, data


def apply_et_fit(workdir: Path, plt_name: str) -> str | None:
    """Overlay this crop's ET calibration (``data/et_fitted.json``). Returns a note, or None.

    Prefer :func:`prepare_plants` over calling this directly — it sequences the workbook
    rewrite and this overlay in the only order that works.

    ``data/et_fitted.json`` is the single source of truth for the fitted plant parameters and
    the basin-wide hydrology values beside them; ``model/TxtInOut`` is never pre-patched with
    any of them. The hydrology values are HRU-level, so they are written here, into this crop's
    own run directory, never into the shared template (whose ``pet_co`` 0.964 is the
    rotation/nutrient model's AgriMet fit and is left alone).

    ``irr_sw_frac`` is deliberately *not* applied here: it lives in a decision table, not a
    parameter file, and is written at build time by :func:`write_irrigation_dtl`.
    """
    shared, crops = load_et_fit()
    fit = crops.get(plt_name)
    if not fit:
        return None
    from swat_gym.params import set_value

    p = workdir / "plants.plt"
    text = p.read_text()
    for col in ET_PLANT_KNOBS:
        if col in fit:
            text = set_value(text, "plants.plt", plt_name, col, fit[col])
    p.write_text(text)
    if ET_PHU_KNOB in fit:
        write_phu_cal(workdir, plt_name, fit[ET_PHU_KNOB])
    h = workdir / "hydrology.hyd"
    text = h.read_text()
    for col in (*ET_HYD_KNOBS, *ET_HYD_FIXED):
        if col in shared:
            text = set_value(text, "hydrology.hyd", "hyd1", col, shared[col])
    h.write_text(text)
    plants = "  ".join(f"{c}={fit[c]:.3f}" for c in (*ET_PLANT_KNOBS, ET_PHU_KNOB) if c in fit)
    held = "  ".join(f"{c}={shared[c]:.3f}" for c in (*ET_HYD_KNOBS, *ET_HYD_FIXED)
                     if c in shared)
    return f"ET fit: {plants} | basin-wide {held}"


#: ``plants.plt`` columns the biomass fit writes, per crop (collaborator's guide, 2026-10-22).
#: ``days_mat`` is in the guide too but is inert on this path -- ``calibration.cal``'s
#: ``phu_mat`` overrides whatever it gives -- so heat units stay with the ET fit.
BIOMASS_KNOBS = ("bm_e", "tmp_opt", "tmp_base")
#: Each group is scaled by one factor, so the default curve's shape is kept.
N_COLS = ("frac_n_em", "frac_n_50", "frac_n_mat")
P_COLS = ("frac_p_em", "frac_p_50", "frac_p_mat")


def np_defaults(plt_name: str) -> dict[str, float]:
    """``{plants.plt column: DEFAULT value}`` for this crop's six N/P uptake columns."""
    row = pd.read_csv(NP_DEFAULT).set_index("plants_plt").loc[plt_name]
    return dict(zip(N_COLS + P_COLS, (float(row[c]) for c in
                                       ("BN1", "BN2", "BN3", "BP1", "BP2", "BP3"))))


def load_biomass_fit() -> dict:
    """``{plants_plt: {bm_e, tmp_opt, tmp_base, n_scale, p_scale}}``; ``{}`` when absent."""
    if not BIOMASS_FITTED.is_file():
        return {}
    return json.loads(BIOMASS_FITTED.read_text()).get("crops", {})


def biomass_text(plants: str, plt_name: str, fit: dict) -> str:
    """``plants.plt`` text with ``fit``'s knobs and ``default x scale`` N/P written.

    Missing keys fall back to "leave the knob" and a scale of 1.0, so ``fit={}`` is the
    defaults-only state the biomass fit anchors to.
    """
    from swat_gym.params import set_value

    for col in BIOMASS_KNOBS:
        if col in fit:
            plants = set_value(plants, "plants.plt", plt_name, col, fit[col])
    base = np_defaults(plt_name)
    for cols, key in ((N_COLS, "n_scale"), (P_COLS, "p_scale")):
        for col in cols:
            plants = set_value(plants, "plants.plt", plt_name, col,
                               base[col] * fit.get(key, 1.0))
    return plants


def apply_biomass_fit(workdir: Path, plt_name: str, *, use_fit: bool = True) -> str | None:
    """Write DEFAULT N/P uptake x the fitted factors, and the fitted biomass knobs.

    ``use_fit=False`` writes the DEFAULT N/P block alone (factors 1.0, workbook ``bm_e``/
    ``tmp_*``): the state ``biomass_calibrate.py`` starts from, so its regularisation anchor
    does not drift onto its own previous answer -- the same reason ``et_calibrate`` builds with
    ``with_fit=False``. Returns a note, or None when there is no DEFAULT block to write.
    """
    if not NP_DEFAULT.is_file():
        return None
    fit = load_biomass_fit().get(plt_name, {}) if use_fit else {}
    p = workdir / "plants.plt"
    p.write_text(biomass_text(p.read_text(), plt_name, fit))
    if not fit:
        return "N/P uptake <- workbook DEFAULT block"
    knobs = "  ".join(f"{c}={fit[c]:.3f}" for c in BIOMASS_KNOBS if c in fit)
    return (f"biomass fit: {knobs} | N/P <- DEFAULT x {fit.get('n_scale', 1.0):.3f} / "
            f"x {fit.get('p_scale', 1.0):.3f}")


def prepare_plants(workdir: Path, plt_name: str, *, with_fit: bool = True,
                   workbook_all: bool = False,
                   with_biomass: bool = True) -> tuple[str | None, str | None]:
    """Bring one crop's ``plants.plt``/``hydrology.hyd`` to their run-ready state.

    Returns ``(workbook_note, et_note)``, either of which may be None.

    The order is the whole point and is why this exists as a function rather than as two
    calls at each site: :func:`patch_plants` rewrites ``lai_pot`` from the workbook for the
    four crops that were never ported, so it MUST run before :func:`apply_et_fit` — the
    other way round, the fit is silently overwritten for exactly the crops that need it
    most, and the run still completes, reporting plausible-looking nonsense.

    ``with_fit=False`` stops after the workbook step. ``et_calibrate.py`` needs that: the
    fit's regularisation penalty is anchored to the parameters it starts from, so starting
    it from a previous fit's output would let the anchor drift run over run.

    On the ET path (``workbook_all=True``) the biomass/N-P step sits between the two:
    after the workbook rewrite, which would otherwise put the calibrated BN/BP back, and
    independent of ``with_fit``, because the ET fit's anchor is the canopy and PHU, not these
    columns -- the ET refit has to run *on top of* the biomass fit. ``with_biomass=False``
    writes the DEFAULT N/P block alone; ``biomass_calibrate.py`` builds that way.
    """
    note = patch_plants(workdir, plt_name, workbook_all=workbook_all)
    if workbook_all:
        bm_note = apply_biomass_fit(workdir, plt_name, use_fit=with_biomass)
        note = "; ".join(n for n in (note, bm_note) if n) or None
    et_note = apply_et_fit(workdir, plt_name) if with_fit else None
    return note, et_note


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def write_harvest_op(workdir: Path, plt_name: str) -> str:
    """Build this crop's `harv.ops` entry from the workbook. Returns the op name.

    The workbook already carries the calibration, so nothing is fitted here:

    * ``harv_idx`` <- ``HARV_EFF``. This is the established convention on this model, not a
      guess — the three site ops record their own provenance as ``fitted_from_REF_0.98`` /
      ``_0.54`` / ``_0.95``, which are exactly CSIL/BARL/ALFA ``HARV_EFF``.
    * ``harv_typ`` <- ``IDC``, except that ``HI_OVR > 1`` marks a root/tuber crop.
    * ``harv_eff`` = 1.0, matching the site ops (efficiency is carried in the index).
    """
    path = workdir / "harv.ops"
    existing = {ln.split()[0] for ln in path.read_text().splitlines()[2:] if ln.split()}
    if plt_name in HARVEST and HARVEST[plt_name] in existing:
        return HARVEST[plt_name]
    # The site ops (gn_corn/gn_barl/gn_alfa) live in the project's harv.ops, not in the SWAT+
    # defaults, so a SWAT+ editor round-trip deletes them -- one on 2026-10-02 did exactly that.
    # Nothing warns: `cut_alfa` in lum.dtl still names `gn_alfa`, and the engine segfaults in
    # year 1. Rebuilding under the same name from the workbook restores the original values
    # exactly, because that is where they came from (harv_idx = HARV_EFF: CSIL 0.98, BARL 0.54,
    # ALFA 0.95), so this is a restore rather than a new choice.
    code = next(k for k, v in CROPS.items() if v[0] == plt_name)
    row = pd.read_csv(CROP_CSV).set_index("CPNM").loc[code]
    if plt_name in HARVEST:
        # The three site ops were all created as `biomass` (verified against the surviving
        # copies in ~/Desktop/projects/swat-kimberly). Deriving the type from IDC instead gives
        # `grain` for corn (IDC 4) and barley (IDC 5) -- which runs a different harvest routine,
        # changes what biomass is removed, and moved corn's ET by 2 PBIAS points and 42 mm of
        # irrigation when these ops had to be rebuilt on 2026-10-08. Alfalfa (IDC 3) maps to
        # `biomass` anyway, which is why only corn and barley drifted.
        typ = "biomass"
    else:
        typ = "tuber" if float(row["HI_OVR"]) > 1.0 else IDC_TYP.get(int(row["IDC"]), "grain")
    name = HARVEST.get(plt_name, f"wb_{plt_name}")
    if name in existing:
        return name
    path.write_text(
        path.read_text().rstrip("\n") + "\n"
        f"{name:<24s}{typ:>14s}{float(row['HARV_EFF']):>14.5f}{1.0:>14.5f}{0.0:>14.5f}"
        f"  workbook_{code}_HARV_EFF\n")
    return name


def lum_names(workdir: Path) -> tuple[str, str]:
    """``(plnt_com, mgt)`` the HRU's ``landuse.lum`` row actually points at.

    These were hardcoded to ``kimb_comm``/``kimb_rot`` until 2026-10-08. A SWAT+ editor
    round-trip on 2026-10-02 renamed them to ``csil_comm``/``csil_rot`` in ``landuse.lum``,
    and because :func:`write_plant_ini` and :func:`write_management` kept writing the old
    names, every built run referenced a community and a schedule that no longer existed. The
    engine does not complain: it runs to completion with **no plant and no management at all**
    -- LAI, biomass, yield and irrigation all exactly zero, weather and soil temperature
    normal. Reading the names here makes the build survive the next round-trip too.
    """
    rows = [ln.split() for ln in (workdir / "landuse.lum").read_text().splitlines()[2:]
            if ln.split()]
    if not rows or len(rows[0]) < 4:
        raise SystemExit("landuse.lum: no usable land-use row")
    return rows[0][2], rows[0][3]


def write_plant_ini(workdir: Path, plt_name: str) -> None:
    """Single-plant community: removes the three-plant kimb_comm resident-alfalfa draw."""
    perennial = plt_name == "alfa"
    pcom, _ = lum_names(workdir)
    (workdir / "plant.ini").write_text(
        "plant.ini: written by scripts/monoculture.py\n"
        "pcom_name          plt_cnt  rot_yr_ini          plt_name     lc_status"
        "      lai_init       bm_init      phu_init      plnt_pop      yrs_init"
        "      rsd_init  \n"
        f"{pcom:<18s}       1          1  \n"
        f"                                        {plt_name:<9s}"
        f"    {'y' if perennial else 'n'}       0.00000       0.00000       0.00000"
        f"       0.00000       {'1.00000' if perennial else '0.00000'}       0.00000  \n"
    )


def write_management(workdir: Path, plt_name: str, spec, years: int, n_rate: float,
                     harv_op: str, fert: str = "auto",
                     irr_auto: str = "irr_str9_unlim", cut_auto: str | None = None) -> int:
    """Continuous monoculture: plant, fertilise, harvest, every year. Auto-irrigation on.

    ``fert`` selects how nitrogen and phosphorus arrive:

    ``"auto"``
        The ``auto_fert_n`` / ``auto_fert_p`` decision tables in ``lum.dtl`` fertilise to
        demand — 50 kg/ha whenever the growing crop's stress factor drops below 0.90, capped
        at 5 N and 2 P events per year. ``n_rate`` is ignored.

        This is the regime those tables are actually valid in, and the reason is narrower
        than it first looks. Verified against rev-62 ``conditions.f90`` (2026-09-04):

        * ``n_stress`` / ``p_stress`` **average over every growing plant** in the community --
          they do *not* pick one. An earlier version of this note claimed they resolve to
          plant 1; that was wrong.
        * ``plant_gro`` takes a plant **index** from its own ``lim_const``
          (``ipl = Max(Int(lim_const), 1)``), so at the shipped ``1.00000`` it gates on
          plant 1 alone.
        * ``phu_plant`` uses "the first one that is growing".

        So the table really is suppressed outside plant 1's season in a multi-plant
        community -- via ``plant_gro``, not via the stress terms. :func:`write_plant_ini`
        rewrites the community to a single plant, which makes plant 1 *be* this crop and the
        table mean what it reads like.

    ``"constant"``
        The historical behaviour: one ``n_rate`` kg N/ha broadcast at emergence, no P. Kept so
        the earlier monoculture screens stay reproducible.

    ``irr_auto`` names the auto-irrigation decision table. The default is the shipped
    plant-stress table, which is what the nutrient/monoculture screens have always used; the ET
    runs pass the per-crop windowed table from :func:`write_irrigation_dtl` instead.

    ``cut_auto`` names a perennial's cutting decision table (:func:`with_cutting_dtl`). When
    given, the scheduled ``harv`` ops are dropped so the cuttings happen exactly once, from the
    table.
    """
    if fert not in ("auto", "constant"):
        raise ValueError(f"fert must be 'auto' or 'constant', got {fert!r}")
    _, (em_m, em_d), harvests = spec
    perennial = plt_name == "alfa"
    ops: list[tuple] = []
    for yr in range(years):
        # A perennial is established once; annuals are re-planted every year.
        if not perennial or yr == 0:
            ops.append(("plnt", em_m, em_d, plt_name, "null"))
        if fert == "constant" and n_rate > 0:
            ops.append(("fert", em_m, em_d, "elem_n", "broadcast", n_rate))
        for (hm, hd) in ([] if perennial and cut_auto else harvests):
            # `harv` cuts without killing (alfalfa regrows); `hvkl` ends an annual.
            ops.append(("harv" if perennial else "hvkl", hm, hd, plt_name, harv_op))
        if not perennial:
            ops.append(("skip", 12, 31, "null", "null"))

    body = []
    for op in ops:
        typ, mon, day, d1, d2 = op[0], op[1], op[2], op[3], op[4]
        d3 = op[5] if len(op) > 5 else 0.0
        body.append(f"{'':48s}{typ:<14s}{mon:>4d}{day:>10d}{0.0:>14.5f}"
                    f"{d1:>18s}{d2:>18s}{d3:>14.5f}  ")

    autos = [irr_auto] + ([cut_auto] if perennial and cut_auto else [])
    if fert == "auto":
        autos += ["auto_fert_n", "auto_fert_p"]

    _, sched = lum_names(workdir)
    # The auto block is read *before* the scheduled ops, not after — `read_mgtops.f90` consumes
    # `numb_auto` decision-table names immediately after the schedule header. Putting them at the
    # end fails with a bare "End of file" that says nothing about the real cause.
    (workdir / "management.sch").write_text(
        "management.sch: written by scripts/monoculture.py\n"
        "name                                       numb_ops  numb_auto            op_typ"
        "       mon       day        hu_sch          op_data1          op_data2      op_data3  \n"
        f"{sched:<22s}{'':15s}{len(body):<4d}      {len(autos):>4d}  \n"
        + "".join(f"{'':48s}{a:<18s}\n" for a in autos)
        + "\n".join(body) + "\n"
    )
    return len(body)


def write_time(workdir: Path, start: int, years: int) -> None:
    (workdir / "time.sim").write_text(
        "time.sim: written by scripts/monoculture.py\n"
        "day_start  yrc_start   day_end   yrc_end      step  \n"
        f"         0      {start}         0      {start + years}         0\n"
    )


#: Soil-water trigger for the windowed irrigation table: irrigate when soil water falls below
#: this fraction of field capacity. Basin-wide and **fitted** (``et_calibrate.py``), not
#: per-crop — it is an irrigation-management property of the site, and making it per-crop would
#: reintroduce exactly the objection the collaborator raised against a per-crop ``pet_co``.
#: 0.5 is the shipped ``irr_opt_sw_unlim`` value and the fit's starting point.
IRR_SW_FRAC = 0.5

#: Month/day <-> day-of-year conversions for a *static* decision table need one reference year.
#: A non-leap year is the right choice: the table then lines up exactly with the sheet's dates
#: in three years out of four, and is one day early after 29 February in a leap year (a fixed
#: day-of-year lands on the previous calendar date). There is no
#: month/day condition in the decision tables, so this is unavoidable; it is checked, not
#: assumed, by ``et_raw.py``'s irrigation-window audit.
REF_YEAR = 2023


def _doy(md: tuple[int, int]) -> int:
    return int(pd.Timestamp(REF_YEAR, md[0], md[1]).dayofyear)


def _md_str(doy: int) -> str:
    t = pd.Timestamp(REF_YEAR, 1, 1) + pd.Timedelta(days=doy - 1)
    return f"{t.month}/{t.day}"


def irrigation_windows(code: str) -> list[tuple[int, int]]:
    """This crop's irrigation windows as inclusive ``(start_doy, end_doy)`` pairs.

    Annuals get the sheet's ``irrigation start``-``irrigation end`` verbatim: one window.

    Alfalfa's single sheet window is split by the footnote's rule — stop
    :data:`STOP_BEFORE_CUT_DAYS` before each cutting, restart :data:`RESTART_AFTER_CUT_DAYS`
    after it — which yields four windows for the four cuttings. The last blackout begins 10/8,
    one day before the sheet's own 10/9 ``irrigation end``, so the footnote and the column agree
    to within a day and the footnote (being the stricter and the stated rule) wins.
    """
    (start, end) = (_doy(IRR_SHEET[code][0]), _doy(IRR_SHEET[code][1]))
    plt_name, _, harvests = CROPS[code]
    if plt_name != "alfa":
        return [(start, end)]

    windows: list[tuple[int, int]] = []
    cur = start
    for cut in harvests:
        blackout = _doy(cut)
        stop = blackout - STOP_BEFORE_CUT_DAYS
        if stop > cur:
            windows.append((cur, min(stop, end)))
        cur = blackout + RESTART_AFTER_CUT_DAYS
        if cur > end:
            break
    if not windows:
        raise RuntimeError(f"{code}: irrigation windows collapsed to nothing")
    return windows


def _dtl_row(var: str, obj: str, obj_num, lim_var: str, lim_op: str, const: float,
             alts: list[str], comment: str = "") -> str:
    """One condition row in ``lum.dtl``'s fixed layout (widths read off the shipped file)."""
    return (f"{var:<27}{obj:>3}{obj_num:>10}{lim_var:>18}{lim_op:>18}{const:>14.5f}"
            + "".join(f"{a:>10}" for a in alts) + (f"  {comment}" if comment else "  ") + "\n")


def build_irrigation_dtl(dtl_text: str, code: str,
                         sw_frac: float = IRR_SW_FRAC) -> tuple[str, str]:
    """``(lum.dtl text with this crop's windowed irrigation table, table name)``.

    Pure, because ``et_calibrate.py`` fits ``sw_frac`` and so rebuilds this table once per
    trial run rather than once per run directory.

    Replaces the shipped ``irr_str9_unlim`` (irrigate whenever plant water stress < 0.9) for
    the ET runs, and the difference is the single biggest control on simulated ET:

    * ``irr_str9_unlim`` fires only once a plant is *growing* and stressed, so the sheet's
      pre-emergence ``irrigation start`` dates — corn 5/25 against a 6/1 emergence, potato
      5/15 against 5/20, pinto bean 6/26 against 7/1, sugarbeet 4/20 against 5/1 — could not
      do anything, and bare soil was never wetted. Measured, that left every crop 13-53 %
      under the eeMetric target with no parameter able to recover it: the full 0.01-0.95 range
      of ``esco`` was worth under 2 |PBIAS| points *in that configuration* and ``epco`` above
      1.0 is inert (identical ET at 1.0 and 2.0), because the shortfall was never
      evaporative demand — it was water. (Once these windows keep the soil wet, ``esco``
      matters a great deal more; see :data:`ET_ESCO_DEFAULT`.)
    * A ``soil_water`` trigger has no ``plant_gro`` condition, so it irrigates inside the
      window whether or not there is a canopy, which is what the sheet's dates describe.

    The table is ``soil_water < sw_frac x fc`` AND ``jday`` inside one of the windows from
    :func:`irrigation_windows` — one alternative per window, OR-ed, so alfalfa's four cutting
    blackouts are four gaps in one table. ``jday`` bounds are written as strict ``>``/``<``
    against ``start - 1`` / ``end + 1``, since the tables have no ``>=``.
    """
    windows = irrigation_windows(code)
    plt_name = CROPS[code][0]
    name = f"irr_win_{plt_name}"
    n_alt = len(windows)
    conds = 1 + 2 * n_alt
    alt_hdr = [f"alt{i + 1}" for i in range(n_alt)]

    body = _dtl_row("soil_water", "hru", 0, "fc", "-", sw_frac, ["<"] * n_alt,
                    f"!irrigate below this fraction of field capacity, growing or not")
    for k, (start, end) in enumerate(windows):
        for bound, op in ((start - 1, ">"), (end + 1, "<")):
            ops = ["-"] * n_alt
            ops[k] = op
            body += _dtl_row("jday", "hru", 0, "null", "-", float(bound), ops,
                             f"!window {k + 1}: {_md_str(start)}-{_md_str(end)}")

    table = (
        f"\nname                     conds      alts      acts"
        f"       !{name}: sheet irrigation window(s), soil-water triggered\n"
        f"{name:<22}{conds:>8}{n_alt:>10}{1:>10}  \n"
        f"{'var':<22}{'obj':>8}{'obj_num':>10}{'lim_var':>18}{'lim_op':>18}{'lim_const':>14}"
        + "".join(f"{a:>10}" for a in alt_hdr) + "  \n"
        + body
        + f"{'act_typ':<22}{'obj':>8}{'obj_num':>10}{'name':>18}{'option':>18}{'const':>14}"
          f"{'const2':>14}{'fp':>18}  outcome\n"
        + f"{'irr_demand':<27}{'hru':>3}{0:>10}{'sprinkler':>18}{'sprinkler_ilm':>18}"
          f"{IRR_MM:>14.5f}{20.0:>14.5f}{'unlim':>18}  "
        + "".join(f"{'y':<4}" for _ in range(n_alt)) + "\n"
    )

    return _append_dtl(dtl_text, name, table), name


def _append_dtl(dtl_text: str, name: str, table: str) -> str:
    """Append one decision table to ``lum.dtl`` text and bump the table count."""
    lines = dtl_text.splitlines(keepends=True)
    if any(ln.split()[:1] == [name] for ln in lines):
        raise RuntimeError(f"{name} is already in lum.dtl; appending it twice would leave the "
                           f"engine reading the first copy and the count overshooting")
    # Line 2 is the table count. Appending a table without incrementing it leaves the new table
    # unread -- silently, with no error. A count that overshoots instead segfaults the engine
    # partway through year 1, with a backtrace that names nothing.
    n = int(lines[1].strip())
    lines[1] = f"{n + 1}\n"
    return "".join(lines).rstrip("\n") + "\n" + table


def cutting_table_name(code: str) -> str | None:
    """Name of this crop's cutting decision table, or None for an annual (harvested by schedule)."""
    plt_name = CROPS[code][0]
    return f"cut_{plt_name}" if plt_name == "alfa" else None


def with_cutting_dtl(dtl_text: str, code: str) -> str:
    """``lum.dtl`` text with alfalfa's cuttings as a decision table; unchanged for annuals.

    The collaborator asked (2026-09-25) for the cuttings to live in alfalfa's decision table
    beside the irrigation windows, so harvest and the stop-a-week-before rule are defined off
    the same dates in the same file. One alternative per cutting, each ``jday =`` that cut's
    day-of-year on :data:`REF_YEAR` — the same conversion :func:`irrigation_windows` uses, so in a
    leap year the cut and its blackout both land one day early together and the cut stays on the
    blackout's last day.

    The action's ``const2`` caps harvests per year; the engine resets that counter on 1 January
    (``hru_control.f90``) and its ``harvest`` action never increments it, so 4 is a cap, not a
    budget. The cut itself runs ``mgt_harvbiomass`` exactly as the scheduled ``harv`` op did —
    and with ``engine_patches/lai_reset_on_cut.patch`` that now takes LAI to 0.
    """
    name = cutting_table_name(code)
    if name is None:
        return dtl_text
    plt_name, _, harvests = CROPS[code]
    n_alt = len(harvests)
    body = ""
    for k, cut in enumerate(harvests):
        ops = ["-"] * n_alt
        ops[k] = "="
        body += _dtl_row("jday", "hru", 0, "null", "-", float(_doy(cut)), ops,
                         f"!cutting {k + 1}: {cut[0]}/{cut[1]}")
    table = (
        f"\nname                     conds      alts      acts"
        f"       !{name}: sheet cutting dates, harvest-only (stand survives)\n"
        f"{name:<22}{n_alt:>8}{n_alt:>10}{1:>10}  \n"
        f"{'var':<22}{'obj':>8}{'obj_num':>10}{'lim_var':>18}{'lim_op':>18}{'lim_const':>14}"
        + "".join(f"{'alt' + str(i + 1):>10}" for i in range(n_alt)) + "  \n"
        + body
        + f"{'act_typ':<22}{'obj':>8}{'obj_num':>10}{'name':>18}{'option':>18}{'const':>14}"
          f"{'const2':>14}{'fp':>18}  outcome\n"
        + f"{'harvest':<27}{'hru':>3}{0:>10}{'hay_cut':>18}{plt_name:>18}"
          f"{0.0:>14.5f}{float(n_alt):>14.5f}{HARVEST[plt_name]:>18}  "
        + "".join(f"{'y':<4}" for _ in range(n_alt)) + "\n"
    )
    return _append_dtl(dtl_text, name, table)


def write_irrigation_dtl(workdir: Path, code: str, sw_frac: float = IRR_SW_FRAC) -> str:
    """Write this crop's windowed irrigation table into ``workdir/lum.dtl``; return its name."""
    path = workdir / "lum.dtl"
    text, name = build_irrigation_dtl(path.read_text(), code, sw_frac)
    path.write_text(text)
    return name


def align_irr_dtl(dtl_text: str) -> str:
    """Align ``irr_str9_unlim``'s own amount with :data:`IRR_MM` so the two files agree."""
    lines = dtl_text.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.split()[:1] == ["irr_str9_unlim"]:
            for k in range(i + 1, min(i + 6, len(lines))):
                toks = lines[k].split()
                if toks[:1] == ["irr_demand"] and toks[4] == "sprinkler_ilm":
                    lines[k] = lines[k].replace(f"{float(toks[5]):14.5f}", f"{IRR_MM:14.5f}", 1)
                    break
            break
    return "".join(lines)


#: Per-year event cap written into ``auto_fert_n`` / ``auto_fert_p`` for every monoculture and
#: ET run (decided 2026-10-23). The template's 5 N / 2 P events (250 kg N, 100 kg P) bound
#: uptake below the collaborator's targets -- wheat sat on the 250 kg N cap and sugarbeet's
#: 440 kg N target is unreachable under it -- and auto-fert exists to make nutrients
#: non-limiting. The stress < 0.90 / growing / pre-maturity conditions still gate every event,
#: so this only removes the ceiling. The template ``lum.dtl`` (the rotation model) keeps its caps.
FERT_EVENTS_MAX = 20


def lift_fert_caps(dtl_text: str, events: int = FERT_EVENTS_MAX) -> str:
    """``auto_fert_n`` / ``auto_fert_p`` with their per-year event cap (``const2``) raised."""
    lines = dtl_text.splitlines(keepends=True)
    found = set()
    for i, line in enumerate(lines):
        name = line.split()[:1]
        if name not in (["auto_fert_n"], ["auto_fert_p"]):
            continue
        for k in range(i + 1, min(i + 10, len(lines))):
            toks = lines[k].split()
            if toks[:1] == ["fertilize"]:
                old = f"{float(toks[6]):14.5f}"
                if old not in lines[k]:
                    raise RuntimeError(f"lum.dtl: cannot locate {name[0]}'s const2 {toks[6]}")
                lines[k] = lines[k].replace(old, f"{float(events):14.5f}", 1)
                found.add(name[0])
                break
    if found != {"auto_fert_n", "auto_fert_p"}:
        raise RuntimeError(f"lum.dtl: fertilize action not found for "
                           f"{sorted({'auto_fert_n', 'auto_fert_p'} - found)}")
    return "".join(lines)


def prepare_dtl(dtl_text: str) -> str:
    """The template ``lum.dtl`` as every monoculture/ET run uses it: irrigation amount aligned
    with :data:`IRR_MM`, auto-fert caps lifted. The per-crop tables are appended to this."""
    return lift_fert_caps(align_irr_dtl(dtl_text))


def add_sprinkler(workdir: Path) -> None:
    """Define ``sprinkler_ilm`` in irr.ops and bring ``lum.dtl`` to :func:`prepare_dtl`."""
    path = workdir / "irr.ops"
    text = path.read_text()
    if "sprinkler_ilm" not in text:
        path.write_text(text.rstrip("\n") + "\n" + SPRINKLER_ILM + "\n")
    dtl = workdir / "lum.dtl"
    dtl.write_text(prepare_dtl(dtl.read_text()))


def run_crop(code: str, years: int, start: int, n_rate: float, outdir: Path,
             fert: str = "auto") -> dict:
    plt_name, _, _ = CROPS[code]
    work = outdir / f"_tio_{plt_name}"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(TIO, work)

    note, et_note = prepare_plants(work, plt_name)
    harv_op = write_harvest_op(work, plt_name)
    write_plant_ini(work, plt_name)
    n_ops = write_management(work, plt_name, CROPS[code], years, n_rate, harv_op, fert)
    write_time(work, start, years)
    add_sprinkler(work)

    sim = outdir / plt_name
    KimberlySwat(txtinout=work).run(sim_dir=sim)
    shutil.rmtree(work)

    res = {"crop": code, "plants_plt": plt_name, "n_ops": n_ops, "fert_mode": fert,
           "params_note": note or "site-calibrated, untouched", "harv_op": harv_op,
           "et_fit": et_note or "none (data/et_fitted.json absent)"}
    # Applied N/P is read back rather than assumed: under `fert="auto"` the amount is an
    # *outcome* of the stress trajectory and the per-year event caps, not an input.
    nb = sim / "hru_nb_day.txt"
    if nb.is_file():
        d = pd.read_csv(nb, sep=r"\s+", skiprows=1, header=0, engine="python")
        d = d[pd.to_numeric(d["jday"], errors="coerce").notna()]
        n_yr = len(pd.to_numeric(d["yr"], errors="coerce").dropna().unique()) or 1
        for c in ("fertn", "fertp"):
            if c in d:
                res[f"{c}_kg_ha_yr"] = round(
                    float(pd.to_numeric(d[c], errors="coerce").sum()) / n_yr, 2)
    pw = sim / "hru_pw_day.txt"
    if pw.is_file():
        df = pd.read_csv(pw, sep=r"\s+", skiprows=1, header=0, engine="python")
        df = df[pd.to_numeric(df["jday"], errors="coerce").notna()]
        for c in ("strsn", "strsw", "strsp", "strstmp", "lai", "bioms"):
            if c in df:
                res[f"mean_{c}"] = round(float(pd.to_numeric(df[c], errors="coerce").mean()), 4)
        res["days"] = len(df)
    yld = sim / "basin_crop_yld_yr.txt"
    if yld.is_file():
        d = pd.read_csv(yld, sep=r"\s+", skiprows=1, header=0, engine="python")
        num = pd.to_numeric(d.get("yld(t)"), errors="coerce").dropna()
        if len(num):
            res["mean_yld_t_ha"] = round(float(num.mean()), 3)
            res["harvest_rows"] = len(num)
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--years", type=int, default=18)
    ap.add_argument("--start-year", type=int, default=2007,
                    help="first simulated year; weather covers 1995-2025")
    ap.add_argument("--n-rate", type=float, default=200.0,
                    help="kg N/ha/yr as elemental N; only used with --fert constant")
    ap.add_argument("--fert", choices=("auto", "constant"), default="auto",
                    help="auto: auto_fert_n/auto_fert_p decision tables (default); "
                         "constant: one --n-rate broadcast at emergence")
    ap.add_argument("--crops", nargs="*", default=None,
                    help=f"subset of {sorted(CROPS)} (default: all)")
    ap.add_argument("--outdir", type=Path, default=ROOT / "runs" / "monoculture")
    args = ap.parse_args()

    codes = args.crops or list(CROPS)
    bad = set(codes) - set(CROPS)
    if bad:
        raise SystemExit(f"unknown crops {sorted(bad)}; have {sorted(CROPS)}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    fert_desc = ("auto_fert_n + auto_fert_p (stress < 0.90, 5xN / 2xP per yr)"
                 if args.fert == "auto" else f"constant {args.n_rate} kg N/ha/yr")
    print(f"{args.years} yr from {args.start_year} to {args.start_year + args.years}, "
          f"fertiliser: {fert_desc}, auto-irrigation (irr_str9_unlim)\n")

    rows = []
    for code in codes:
        print(f"  {code} ({CROPS[code][0]}) ... ", end="", flush=True)
        try:
            r = run_crop(code, args.years, args.start_year, args.n_rate, args.outdir,
                         args.fert)
            rows.append(r)
            print(f"strsn={r.get('mean_strsn', '?')}  strsw={r.get('mean_strsw', '?')}  "
                  f"N={r.get('fertn_kg_ha_yr', '?')}  P={r.get('fertp_kg_ha_yr', '?')}  "
                  f"yld={r.get('mean_yld_t_ha', '?')}")
        except Exception as exc:  # keep going; one crop failing should not lose the rest
            print(f"FAILED: {exc}")
            rows.append({"crop": code, "error": str(exc)})

    out = args.outdir / "summary.json"
    out.write_text(json.dumps(
        {"years": args.years, "start_year": args.start_year, "fert_mode": args.fert,
         "n_rate": args.n_rate if args.fert == "constant" else None,
         "fertiliser": fert_desc,
         "irrigation": "auto (irr_str9_unlim, w_stress<0.9, unlimited)", "results": rows},
        indent=2))
    print(f"\nwrote {out}")
    ok = [r for r in rows if "error" not in r]
    if ok:
        print(pd.DataFrame(ok).to_string(index=False))


if __name__ == "__main__":
    main()
