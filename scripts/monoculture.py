#!/usr/bin/env python3
"""Continuous monoculture runs — one crop, every year, for all seven site crops.

Purpose: read each crop's **nutrient and water stress** (`hru_pw_day.strsn`, `strsw`) under a
common management, so the crops can be compared without the rotation confounding them.

Management is deliberately uniform across crops so the *crop* is the only thing that varies:

* **Water is not limiting.** Auto-irrigation via the shipped `irr_str9_unlim` decision table —
  irrigate when plant water stress drops below 0.9, unlimited source. So `strsw` should stay
  near zero and `strsn` carries the signal.
* **Nitrogen is fixed**, `--n-rate` kg N/ha (default 200) as elemental N broadcast at planting.
  One rate across seven crops is agronomically blunt on purpose: it is the *same* rate, so the
  differences in `strsn` are crop nitrogen demand, not a management difference.
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

    uv run python scripts/monoculture.py                      # all 7, 18 yr, 200 kg N/ha
    uv run python scripts/monoculture.py --crops corn alfa    # subset
    uv run python scripts/monoculture.py --n-rate 0           # unfertilised, max strsn
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

from swat_kimberly.runner import KimberlySwat  # noqa: E402

TIO = ROOT / "model" / "TxtInOut"
CROP_CSV = ROOT / "data" / "crop_params_swat.csv"

#: workbook crop -> (plants.plt name, emerge (mon,day), harvest dates [(mon,day), ...])
#: Dates are the `Plant Harvest Dates` sheet. Alfalfa is perennial with four cuttings.
CROPS: dict[str, tuple[str, tuple[int, int], list[tuple[int, int]]]] = {
    "ALFA": ("alfa", (3, 1), [(6, 15), (7, 30), (8, 30), (10, 15)]),
    "BARL": ("barl", (4, 15), [(8, 10)]),
    "CSIL": ("corn", (6, 1), [(9, 25)]),
    "POTA": ("pota", (5, 20), [(9, 10)]),
    "PTBN": ("ptbn", (7, 1), [(9, 25)]),
    "WWHT": ("wwht", (3, 1), [(7, 31)]),
    "SGBT": ("sgbt", (5, 1), [(10, 5)]),
}

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
SPRINKLER_ILM = ("sprinkler_ilm       25.00000       0.85000       0.00000       0.00000"
                 "       0.00000       0.00000       0.00000  auto-irrigation, added by "
                 "monoculture.py")


def patch_plants(workdir: Path, plt_name: str) -> str | None:
    """Write the workbook's parameters for an unported crop. Returns a note, or None."""
    if plt_name in ALREADY_CALIBRATED:
        return None
    code = next(k for k, v in CROPS.items() if v[0] == plt_name)
    row = pd.read_csv(CROP_CSV).set_index("CPNM").loc[code]
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
        for idx, col in COLMAP.items():
            toks[idx] = f"{float(row[col]):.5f}"
        # Rebuild in plants.plt's fixed width, preserving any trailing description.
        desc = toks[-1] if not _is_float(toks[-1]) else ""
        nums = toks[1:-1] if desc else toks[1:]
        lines[i] = (f"{plt_name:<22}" + "".join(f"{t:>14}" for t in nums)
                    + (f"  {desc}" if desc else "") + "\n")
        path.write_text("".join(lines))
        return f"plants.plt[{plt_name}] <- workbook ({code})"
    raise SystemExit(f"{plt_name} not found in plants.plt")


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
    if plt_name in HARVEST:
        return HARVEST[plt_name]
    code = next(k for k, v in CROPS.items() if v[0] == plt_name)
    row = pd.read_csv(CROP_CSV).set_index("CPNM").loc[code]
    typ = "tuber" if float(row["HI_OVR"]) > 1.0 else IDC_TYP.get(int(row["IDC"]), "grain")
    name = f"wb_{plt_name}"
    path = workdir / "harv.ops"
    path.write_text(
        path.read_text().rstrip("\n") + "\n"
        f"{name:<24s}{typ:>14s}{float(row['HARV_EFF']):>14.5f}{1.0:>14.5f}{0.0:>14.5f}"
        f"  workbook_{code}_HARV_EFF\n")
    return name


def write_plant_ini(workdir: Path, plt_name: str) -> None:
    """Single-plant community: removes the three-plant kimb_comm resident-alfalfa draw."""
    perennial = plt_name == "alfa"
    (workdir / "plant.ini").write_text(
        "plant.ini: written by scripts/monoculture.py\n"
        "pcom_name          plt_cnt  rot_yr_ini          plt_name     lc_status"
        "      lai_init       bm_init      phu_init      plnt_pop      yrs_init"
        "      rsd_init  \n"
        "kimb_comm                1          1  \n"
        f"                                        {plt_name:<9s}"
        f"    {'y' if perennial else 'n'}       0.00000       0.00000       0.00000"
        f"       0.00000       {'1.00000' if perennial else '0.00000'}       0.00000  \n"
    )


def write_management(workdir: Path, plt_name: str, spec, years: int, n_rate: float,
                     harv_op: str) -> int:
    """Continuous monoculture: plant, fertilise, harvest, every year. Auto-irrigation on."""
    _, (em_m, em_d), harvests = spec
    perennial = plt_name == "alfa"
    ops: list[tuple] = []
    for yr in range(years):
        # A perennial is established once; annuals are re-planted every year.
        if not perennial or yr == 0:
            ops.append(("plnt", em_m, em_d, plt_name, "null"))
        if n_rate > 0:
            ops.append(("fert", em_m, em_d, "elem_n", "broadcast", n_rate))
        for (hm, hd) in harvests:
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

    # The auto block is read *before* the scheduled ops, not after — `read_mgtops.f90` consumes
    # `numb_auto` decision-table names immediately after the schedule header. Putting them at the
    # end fails with a bare "End of file" that says nothing about the real cause.
    (workdir / "management.sch").write_text(
        "management.sch: written by scripts/monoculture.py\n"
        "name                                       numb_ops  numb_auto            op_typ"
        "       mon       day        hu_sch          op_data1          op_data2      op_data3  \n"
        f"kimb_rot                             {len(body):<4d}         1  \n"
        f"{'':48s}{'irr_str9_unlim':<18s}\n"
        + "\n".join(body) + "\n"
    )
    return len(body)


def write_time(workdir: Path, start: int, years: int) -> None:
    (workdir / "time.sim").write_text(
        "time.sim: written by scripts/monoculture.py\n"
        "day_start  yrc_start   day_end   yrc_end      step  \n"
        f"         0      {start}         0      {start + years}         0\n"
    )


def add_sprinkler(workdir: Path) -> None:
    path = workdir / "irr.ops"
    text = path.read_text()
    if "sprinkler_ilm" not in text:
        path.write_text(text.rstrip("\n") + "\n" + SPRINKLER_ILM + "\n")


def run_crop(code: str, years: int, start: int, n_rate: float, outdir: Path) -> dict:
    plt_name, _, _ = CROPS[code]
    work = outdir / f"_tio_{plt_name}"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(TIO, work)

    note = patch_plants(work, plt_name)
    harv_op = write_harvest_op(work, plt_name)
    write_plant_ini(work, plt_name)
    n_ops = write_management(work, plt_name, CROPS[code], years, n_rate, harv_op)
    write_time(work, start, years)
    add_sprinkler(work)

    sim = outdir / plt_name
    KimberlySwat(txtinout=work).run(sim_dir=sim)
    shutil.rmtree(work)

    res = {"crop": code, "plants_plt": plt_name, "n_ops": n_ops,
           "params_note": note or "site-calibrated, untouched", "harv_op": harv_op}
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
    ap.add_argument("--n-rate", type=float, default=200.0, help="kg N/ha/yr as elemental N")
    ap.add_argument("--crops", nargs="*", default=None,
                    help=f"subset of {sorted(CROPS)} (default: all)")
    ap.add_argument("--outdir", type=Path, default=ROOT / "runs" / "monoculture")
    args = ap.parse_args()

    codes = args.crops or list(CROPS)
    bad = set(codes) - set(CROPS)
    if bad:
        raise SystemExit(f"unknown crops {sorted(bad)}; have {sorted(CROPS)}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    print(f"{args.years} yr from {args.start_year}, N = {args.n_rate} kg/ha/yr, "
          f"auto-irrigation (irr_str9_unlim)\n")

    rows = []
    for code in codes:
        print(f"  {code} ({CROPS[code][0]}) ... ", end="", flush=True)
        try:
            r = run_crop(code, args.years, args.start_year, args.n_rate, args.outdir)
            rows.append(r)
            print(f"strsn={r.get('mean_strsn', '?')}  strsw={r.get('mean_strsw', '?')}  "
                  f"yld={r.get('mean_yld_t_ha', '?')}")
        except Exception as exc:  # keep going; one crop failing should not lose the rest
            print(f"FAILED: {exc}")
            rows.append({"crop": code, "error": str(exc)})

    out = args.outdir / "summary.json"
    out.write_text(json.dumps(
        {"years": args.years, "start_year": args.start_year, "n_rate": args.n_rate,
         "irrigation": "auto (irr_str9_unlim, w_stress<0.9, unlimited)", "results": rows},
        indent=2))
    print(f"\nwrote {out}")
    ok = [r for r in rows if "error" not in r]
    if ok:
        print(pd.DataFrame(ok).to_string(index=False))


if __name__ == "__main__":
    main()
