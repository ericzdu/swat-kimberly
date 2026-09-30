#!/usr/bin/env python3
"""Continuous monoculture per crop (7 site crops) to compare strsn/strsw under uniform
management: unlimited auto-irrigation, fixed N at planting, workbook dates.

Only corn/barl/alfa are site-calibrated; not comparable to rotation results. Runs in copies.

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

#: workbook crop -> (plants.plt name, emerge (mon,day), harvest dates). Alfalfa: four cuts.
CROPS: dict[str, tuple[str, tuple[int, int], list[tuple[int, int]]]] = {
    "ALFA": ("alfa", (3, 1), [(6, 15), (7, 30), (8, 30), (10, 15)]),
    "BARL": ("barl", (4, 15), [(8, 10)]),
    "CSIL": ("corn", (6, 1), [(9, 25)]),
    "POTA": ("pota", (5, 20), [(9, 10)]),
    "PTBN": ("ptbn", (7, 1), [(9, 25)]),
    "WWHT": ("wwht", (3, 1), [(7, 31)]),
    "SGBT": ("sgbt", (5, 1), [(10, 5)]),
}

#: Already in plants.plt; don't overwrite from the workbook.
ALREADY_CALIBRATED = {"corn", "barl", "alfa"}

#: Site harvest ops (generic `grain` has harv_idx 0). Others built by write_harvest_op.
HARVEST = {"corn": "gn_corn", "barl": "gn_barl", "alfa": "gn_alfa"}

#: SWAT IDC -> harv_typ. HI_OVR > 1 means tuber regardless.
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
        # COLMAP keys are 0-based token indices (toks[5] is bm_e).
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
    """Build harv.ops entry from workbook (harv_idx=HARV_EFF, typ from IDC, eff=1). Returns name."""
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

    # Auto decision-table names must come right after the schedule header.
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
