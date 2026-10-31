#!/usr/bin/env python3
"""Tune ``days_mat`` per crop so the engine's heat units to maturity match the workbook.

The collaborator's ``Plant Harvest Dates`` sheet gives heat units to maturity (1800 barley and
corn, 2000 potato and winter wheat, 1000 pinto bean, 2300 sugarbeet; alfalfa "default"). SWAT+
rev 62 has no PHU field: it derives each planting's PHU target from ``plants.plt days_mat`` and
the weather generator, so the sheet's number can only reach the model through ``days_mat``.

The target the engine actually uses is read back, not assumed: ``mgt_out.txt`` prints the
fraction of PHU reached at every operation (``phuplant``), and ``hru_pw_day`` gives the daily
mean temperature, so

    PHU_target = sum(max(0, tmpav - tmp_base)) from planting to op  /  phuplant at op

for every irrigation and harvest op past 30 % of the season, medianed over 2016-2018. That
estimate is stable to <10 degree-days across ops and years. ``days_mat`` is then bisected on
integers until the estimate is within ``--tol`` of the sheet (PHU is monotone in days_mat).

Alfalfa is perennial (``days_mat`` 0, sheet says "default") and is left alone.

    uv run python scripts/et_phu.py            # report only
    uv run python scripts/et_phu.py --apply    # -> data/et_days_mat.json
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import et_calibrate as etc  # noqa: E402
import monoculture as mono  # noqa: E402
from swat_gym.fastrunner import FastRunner  # noqa: E402
from swat_gym.params import get_value, set_value  # noqa: E402

#: Heat units to maturity, ``Plant Harvest Dates`` sheet. Alfalfa is "default" -> untuned.
SHEET_PHU = {"BARL": 1800, "CSIL": 1800, "POTA": 2000, "PTBN": 1000, "WWHT": 2000, "SGBT": 2300}
YEARS = (2016, 2017, 2018)
LO, HI = 30, 300


def engine_phu(tio: Path, plt: str, days_mat: int) -> float:
    """Median PHU-to-maturity the engine used for ``plt`` at this ``days_mat``."""
    p = tio / "plants.plt"
    p.write_text(set_value(p.read_text(), "plants.plt", plt, "days_mat", days_mat))
    tbase = get_value(p.read_text(), "plants.plt", plt, "tmp_base")
    with FastRunner(txtinout=tio, trim_outputs=False, editable=frozenset()) as r:
        r.run()
        pw = r.read("hru_pw_day.txt")
        ops = [ln.split() for ln in (r.workdir / "mgt_out.txt").read_text().splitlines()[3:]]
    est = []
    for yr in YEARS:
        d = pw[pw["yr"] == yr].set_index("jday")
        hu = np.maximum(0.0, d["tmpav"] - tbase).cumsum()
        yr_ops = [o for o in ops if int(o[1]) == yr]
        plant = next(o for o in yr_ops if o[5] == "PLANT")
        pj = pd.Timestamp(yr, int(plant[2]), int(plant[3])).dayofyear
        for o in yr_ops:
            if o[5] in ("IRRIGATE", "HARV/KILL", "HARVEST", "KILL") and float(o[7]) > 0.3:
                j = pd.Timestamp(yr, int(o[2]), int(o[3])).dayofyear
                est.append((hu[j] - hu[pj]) / float(o[7]))
    return float(np.median(est))


def tune(code: str, work: Path, tol: float) -> dict:
    plt = mono.CROPS[code][0]
    tio = etc.CropFit._build(code, 2015, 8, work / f"_tio_{plt}")
    stock = int(get_value((tio / "plants.plt").read_text(), "plants.plt", plt, "days_mat"))
    target = SHEET_PHU[code]
    phu_stock = engine_phu(tio, plt, stock)
    lo, hi = LO, HI
    trace = [(stock, phu_stock)]
    while hi - lo > 1:
        mid = (lo + hi) // 2
        phu = engine_phu(tio, plt, mid)
        trace.append((mid, phu))
        if abs(phu - target) <= tol:
            lo = hi = mid
            break
        if phu < target:
            lo = mid
        else:
            hi = mid
    cands = [(abs(phu - target), dm, phu) for dm, phu in trace]
    _, best, phu_best = min(cands)
    return {"crop": code, "plants_plt": plt, "sheet_phu": target,
            "days_mat_stock": stock, "phu_stock": phu_stock,
            "days_mat": best, "phu": phu_best, "evals": len(trace)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--crops", nargs="*", default=list(SHEET_PHU))
    ap.add_argument("--tol", type=float, default=10.0, help="degree-days")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    work = etc.OUT / "_work_phu"
    work.mkdir(parents=True, exist_ok=True)
    # Tune from the sheet's parameters with no prior days_mat overlay.
    if mono.ET_DAYS_MAT.is_file():
        prior = json.loads(mono.ET_DAYS_MAT.read_text())
        mono.ET_DAYS_MAT.rename(mono.ET_DAYS_MAT.with_suffix(".json.bak"))
    else:
        prior = None
    try:
        rows = [tune(c, work, args.tol) for c in args.crops]
    finally:
        bak = mono.ET_DAYS_MAT.with_suffix(".json.bak")
        if bak.exists():
            bak.rename(mono.ET_DAYS_MAT)
        shutil.rmtree(work, ignore_errors=True)

    df = pd.DataFrame(rows)
    print(df.to_string(index=False, float_format=lambda v: f"{v:8.0f}"))
    (etc.OUT / "et_phu.csv").parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(etc.OUT / "et_phu.csv", index=False)
    if args.apply:
        out = prior or {}
        out.update({r["plants_plt"]: int(r["days_mat"]) for r in rows})
        mono.ET_DAYS_MAT.write_text(json.dumps(out, indent=2))
        print(f"wrote {mono.ET_DAYS_MAT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
