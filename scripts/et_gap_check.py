#!/usr/bin/env python3
"""How far is this model's *in-crop* ET from measured crop ET? Report only, nothing applied.

The paper model is calibrated on the **demand** side only: ``pet_co = 0.964`` is fitted to
measured AgriMet grass-reference ETos (PROVENANCE §5h) and actual ET has never had a measured
target — it is compared to the ArcSWAT reference model, which is tier 2 and explicitly not
validation. The prescribed calibration protocol is the other way round: remove nutrient stress,
then move ``lai_pot`` and ``esco`` until **ET** matches, and touch PET only if you must.

This script measures the gap that protocol would be closing, without changing a single input.
It answers three questions and stops:

1. **How biased is in-crop ET?** Per crop-year, over each crop's own emerge→last-harvest window
   (:data:`scripts.monoculture.CROPS`), because outside the window the field is bare and the
   difference there is management, not canopy — window scoring moved a sibling fit's wheat bias
   from −30.3 % to −14.6 % at unchanged parameters.
2. **Is the PET ceiling binding?** SWAT+ caps actual ET at PET, so if measured ET/simulated PET
   ≥ 1 in-window then no ``lai_pot``/``esco`` setting can reach the target and step 3 of the
   protocol is forced. This is the specific check that decided it in the sibling project
   (obs/PET 1.04 corn, 1.03 wheat, 1.02 alfalfa at ``pet_co`` 0.964).
3. **How much of the gap is definitional?** ``pet_co`` was fitted to *grass*-reference ET; a
   full canopy runs a crop coefficient of roughly 1.15–1.2× that. The implied Kc is reported so
   the gap can be read as "wrong parameter" or "right parameter, wrong reference definition".

**What the target is, and what it is not.** ``--openet`` reads the OpenET eeMetric series built
for the sibling project. That series is **21 different fields** across the Magic Valley, three
crop-years each (2020, 2021, 2022) — *not this field, and not these years*. It is a regional
per-crop benchmark and it is reported as a range across those fields. Nothing here is a
validation of this field's water balance, and nothing here should be written up as one. The
one on-site series is AgriMet ETos, which is already matched to +0.0 % and is a *reference* ET,
not a crop ET.

    uv run python scripts/et_gap_check.py
    uv run python scripts/et_gap_check.py --openet ~/Desktop/projects/Ai-SWAT-Plus/\\
        swat-kimberly-calibration/data/et_reference.csv
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from swat_gym import FastRunner  # noqa: E402
from swat_gym.fastrunner import TXTINOUT  # noqa: E402

from monoculture import CROPS  # noqa: E402

REF_CSV = ROOT / "data" / "reference_hru119.csv"
ET_CSV = ROOT / "data" / "observed_et_agrimet.csv"
OUT = ROOT / "runs" / "et_gap_check.json"

#: Default location of the sibling project's OpenET series. Absent by design from this repo:
#: it belongs to the per-crop project, and copying it here would invite it being cited as an
#: on-site measurement.
OPENET_DEFAULT = (Path.home() / "Desktop/projects/Ai-SWAT-Plus/swat-kimberly-calibration"
                  / "data" / "et_reference.csv")

CROP = {"CSIL": "corn", "BARL": "barl", "ALFA": "alfa"}


def _md(mon, day):
    """Month/day as one sortable integer, so a window is a single comparison."""
    return mon * 100 + day


def crop_window(plt_name: str) -> tuple[int, int]:
    """(emerge, last harvest) for a plants.plt crop, from the workbook dates."""
    code = next(k for k, v in CROPS.items() if v[0] == plt_name)
    _, (em_m, em_d), harvests = CROPS[code]
    hm, hd = harvests[-1]
    return _md(em_m, em_d), _md(hm, hd)


def simulated(daily: pd.DataFrame, crops: dict[int, str]) -> pd.DataFrame:
    """In-window ET and PET per crop-year, from one unmodified run of the rotation."""
    d = daily.copy()
    d["md"] = _md(d["mon"], d["day"])
    rows = []
    for yr, plt_name in crops.items():
        lo, hi = crop_window(plt_name)
        w = d[(d["yr"] == yr) & d["md"].between(lo, hi)]
        if not len(w):
            continue
        rows.append({"year": yr, "crop": plt_name,
                     "window": f"{lo // 100}/{lo % 100}-{hi // 100}/{hi % 100}",
                     "days": int(len(w)),
                     "sim_et": float(w["et"].sum()), "sim_pet": float(w["pet"].sum())})
    return pd.DataFrame(rows)


def observed_openet(path: Path) -> pd.DataFrame:
    """Regional per-crop in-window ET totals: one row per (crop, year, field)."""
    ref = pd.read_csv(path, parse_dates=["date"])
    ref["md"] = _md(ref["date"].dt.month, ref["date"].dt.day)
    ref["yr"] = ref["date"].dt.year
    out = []
    for (crop, yr, loc), g in ref.groupby(["crop", "yr", "location"]):
        if crop not in {v[0] for v in CROPS.values()}:
            continue
        lo, hi = crop_window(crop)
        out.append({"crop": crop, "year": int(yr), "field": loc,
                    "obs_et": float(g.loc[g["md"].between(lo, hi), "et_mm"].sum())})
    return pd.DataFrame(out)


def measured_kc(openet: pd.DataFrame, etos_daily: pd.DataFrame) -> pd.DataFrame:
    """Measured seasonal crop coefficient: regional crop ET over on-site ETos, same window.

    This is the comparison that survives the years not matching. The OpenET fields are
    2020-2022 and this model's rotation is 2013-2019, so comparing ET *depths* across them
    confounds the model gap with whatever those seasons' weather did. A crop coefficient
    divides that out: both numerator and denominator move with the weather, and what is left
    is how much water the crop takes relative to a grass reference — a crop property, stable
    across years, and directly comparable to the model's own implied Kc.
    """
    d = etos_daily.copy()
    dt = pd.to_datetime(d["year"].astype(str), format="%Y") + pd.to_timedelta(d["jday"] - 1, "D")
    d["md"] = _md(dt.dt.month, dt.dt.day)
    rows = []
    for (crop, yr), g in openet.groupby(["crop", "yr"]):
        if crop not in {v[0] for v in CROPS.values()}:
            continue
        lo, hi = crop_window(crop)
        obs = float(g.loc[g["md"].between(lo, hi), "et_mm"].sum())
        eto = float(d.loc[(d["year"] == yr) & d["md"].between(lo, hi), "etos_mm"].sum())
        rows.append({"crop": crop, "year": int(yr), "obs_et": obs, "etos": eto,
                     "obs_kc": obs / eto if eto else float("nan")})
    return pd.DataFrame(rows)


def observed_etos(daily_etos: pd.DataFrame, crops: dict[int, str]) -> dict[int, float]:
    """In-window measured grass-reference ETos, for the implied crop coefficient."""
    d = daily_etos.copy()
    dt = pd.to_datetime(d["year"].astype(str), format="%Y") + pd.to_timedelta(d["jday"] - 1, "D")
    d["md"] = _md(dt.dt.month, dt.dt.day)
    out = {}
    for yr, plt_name in crops.items():
        lo, hi = crop_window(plt_name)
        w = d[(d["year"] == yr) & d["md"].between(lo, hi)]
        out[yr] = float(w["etos_mm"].sum()) if len(w) else float("nan")
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--openet", type=Path, default=OPENET_DEFAULT,
                    help="OpenET eeMetric series (regional benchmark, not this field)")
    ap.add_argument("--tree", type=Path, default=None,
                    help="TxtInOut to score (default: the shipped model). Use the no-stress "
                         "calibration tree from et_nostress.py for step 2 of the protocol")
    ap.add_argument("--lai-mult", type=float, default=1.0,
                    help="scale every crop's lai_pot by this before scoring — step 2 of the "
                         "protocol, asking whether canopy has any room left")
    ap.add_argument("--esco", type=float, default=None,
                    help="override hydrology.hyd:esco — the other half of the protocol's "
                         "step 2; lower draws evaporative demand from deeper soil layers")
    ap.add_argument("--pet-co", type=float, default=None,
                    help="override hydrology.hyd:pet_co — step 3, used only after 1 and 2 "
                         "are shown to have no room left")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args()

    crops = {int(r.year): CROP[r.crop] for r in pd.read_csv(REF_CSV).itertuples()}

    # Daily hru_wb only: this changes what is *written*, never what is simulated.
    tio = {"txtinout": args.tree} if args.tree else {}
    edits, editable = {}, {}
    if args.lai_mult != 1.0:
        from swat_gym.fastrunner import EDITABLE
        from swat_gym.params import CALIBRATABLE, get_value, set_value
        src = ((args.tree or TXTINOUT) / "plants.plt").read_text()
        txt = src
        for crop in ("corn", "barl", "alfa"):
            v = get_value(src, "plants.plt", crop, "lai_pot")
            txt = set_value(txt, "plants.plt", crop, "lai_pot", min(v * args.lai_mult, 10.0))
        edits, editable = {"plants.plt": txt}, {"editable": EDITABLE | CALIBRATABLE}
    if args.esco is not None or args.pet_co is not None:
        from swat_gym.fastrunner import EDITABLE
        from swat_gym.params import CALIBRATABLE, set_value
        hyd = ((args.tree or TXTINOUT) / "hydrology.hyd").read_text()
        for col, val in (("esco", args.esco), ("pet_co", args.pet_co)):
            if val is not None:
                hyd = set_value(hyd, "hydrology.hyd", "hyd1", col, val)
        edits["hydrology.hyd"] = hyd
        editable = {"editable": EDITABLE | CALIBRATABLE}
    with FastRunner(**tio, **editable, keep={"hru_wb": {"daily"}}) as r:
        r.run(edits)
        daily = r.read("hru_wb_day.txt")
    sim = simulated(daily, crops)
    if sim.empty:
        raise SystemExit("no in-window days found — check the daily hru_wb table")

    etos = observed_etos(pd.read_csv(ET_CSV), crops)
    sim["etos_in_window"] = [etos.get(y, float("nan")) for y in sim["year"]]
    # What crop coefficient the model is implicitly running: in-crop ET over measured
    # grass-reference ET across the same days.
    sim["implied_kc"] = sim["sim_et"] / sim["etos_in_window"]
    sim["sim_et_over_pet"] = sim["sim_et"] / sim["sim_pet"]

    raw = None
    if args.openet.is_file():
        raw = pd.read_csv(args.openet, parse_dates=["date"])
        raw["md"] = _md(raw["date"].dt.month, raw["date"].dt.day)
        raw["yr"] = raw["date"].dt.year
    obs = observed_openet(args.openet) if args.openet.is_file() else pd.DataFrame()
    summary = {
        "tree": str(args.tree) if args.tree else "model/TxtInOut (shipped, measured practice)",
        "lai_mult": args.lai_mult, "esco": args.esco, "pet_co": args.pet_co,
        "note": ("OpenET rows are 21 DIFFERENT Magic Valley fields, 2020-2022 — a regional "
                 "per-crop benchmark, not a measurement of this field. AgriMet ETos is the "
                 "only on-site series and it is a reference ET, already matched to +0.0 %."),
        "openet_source": str(args.openet) if len(obs) else None,
        "per_year": sim.round(3).to_dict(orient="records"),
    }

    print(f"in-crop ET, this model, unmodified inputs (pet_co "
          f"{'0.964' if True else ''}, esco 0.95, workbook lai_pot)\n")
    print(f"{'year':>6} {'crop':>6} {'window':>12} {'sim ET':>8} {'sim PET':>8} {'ET/PET':>7}"
          f" {'ETos':>7} {'impl Kc':>8}")
    for r_ in sim.itertuples():
        print(f"{r_.year:>6} {r_.crop:>6} {r_.window:>12} {r_.sim_et:>8.0f} {r_.sim_pet:>8.0f}"
              f" {r_.sim_et_over_pet:>7.2f} {r_.etos_in_window:>7.0f} {r_.implied_kc:>8.2f}")

    if len(obs):
        print(f"\nregional OpenET benchmark, same windows, 2020-2022, one field per crop-year")
        print(f"{'crop':>6} {'obs mean':>9} {'obs range':>16} {'sim mean':>9} {'PBIAS':>8}"
              f" {'obs/simPET':>11}")
        by_crop = {}
        for crop, g in obs.groupby("crop"):
            s = sim[sim["crop"] == crop]
            if not len(s):
                continue
            obs_mean = float(g["obs_et"].mean())
            sim_mean = float(s["sim_et"].mean())
            pb = 100.0 * (sim_mean - obs_mean) / obs_mean
            # The ceiling test: measured crop ET against this model's PET over the same days.
            ceiling = obs_mean / float(s["sim_pet"].mean())
            by_crop[crop] = {"obs_mean": obs_mean, "obs_min": float(g["obs_et"].min()),
                             "obs_max": float(g["obs_et"].max()), "n_fields": int(len(g)),
                             "sim_mean": sim_mean, "pbias": pb, "obs_over_sim_pet": ceiling}
            print(f"{crop:>6} {obs_mean:>9.0f} "
                  f"{f'{g.obs_et.min():.0f}-{g.obs_et.max():.0f}':>16} {sim_mean:>9.0f}"
                  f" {pb:>+7.1f}% {ceiling:>11.2f}")
        summary["by_crop"] = by_crop
        # The years do not overlap, so the depth comparison above confounds the model gap with
        # season-to-season weather. Crop coefficients divide that out.
        kc = measured_kc(raw, pd.read_csv(ET_CSV))
        print(f"\nseasonal crop coefficient (ET / on-site grass ETos, same window) — the "
              f"comparison\nthat survives the years not overlapping:")
        print(f"{'crop':>6} {'measured Kc':>26} {'model Kc':>22} {'gap':>7}")
        kc_rows = {}
        for crop, g in kc.groupby("crop"):
            s_ = sim[sim["crop"] == crop]
            if not len(s_):
                continue
            om, mm = float(g["obs_kc"].mean()), float(s_["implied_kc"].mean())
            kc_rows[crop] = {"measured_kc_mean": om, "measured_kc_min": float(g["obs_kc"].min()),
                             "measured_kc_max": float(g["obs_kc"].max()),
                             "model_kc_mean": mm, "model_kc_min": float(s_["implied_kc"].min()),
                             "model_kc_max": float(s_["implied_kc"].max()),
                             "gap_factor": om / mm}
            print(f"{crop:>6} {f'{om:.2f} ({g.obs_kc.min():.2f}-{g.obs_kc.max():.2f})':>26}"
                  f" {f'{mm:.2f} ({s_.implied_kc.min():.2f}-{s_.implied_kc.max():.2f})':>22}"
                  f" {f'x{om / mm:.2f}':>7}")
        summary["crop_coefficient"] = kc_rows
        binding = [c for c, v in by_crop.items() if v["obs_over_sim_pet"] >= 1.0]
        summary["pet_ceiling_binding"] = binding
        print(f"\nPET ceiling binding (obs crop ET >= this model's PET in-window): "
              f"{binding if binding else 'no crop'}")
        print("  binding => lai_pot/esco alone cannot reach the target and pet_co must move;"
              "\n  not binding => the protocol's step 2 has room and step 3 stays optional.")
    else:
        print(f"\n[no OpenET series at {args.openet} — ran the on-site half only]")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))
    print(f"\n-> {args.out}")


if __name__ == "__main__":
    main()
