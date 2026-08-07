"""Compare this SWAT+ model against the calibrated ArcSWAT reference and GRACEnet.

The reference is HRU 119 / subbasin 14 of an ArcSWAT (SWAT2012) model of the same Kimberly
GRACEnet field, whose annual results are committed to ``data/reference_hru119.csv`` (see
that file's provenance in the README). It tracks the GRACEnet measurements closely, so it
is the target this model's inputs were reconciled against.

    uv run python scripts/compare_reference.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from swat_gym import FastRunner

ROOT = Path(__file__).resolve().parents[1]
REF_CSV = ROOT / "data" / "reference_hru119.csv"

# GRACEnet measured annual dry-matter yield (t/ha). Single source of truth is
# calib_report.GRACENET -- this file used to carry its own five-year copy that omitted both
# barley years, so it printed NaN for barley and reported a GRACEnet PBIAS computed over the
# five easy years. Barley is the model's worst crop against measurement; excluding it flattered
# the score by ~10 points.
from calib_report import GRACENET  # noqa: E402

CROP = {"CSIL": "corn", "BARL": "barl", "ALFA": "alfa"}


def pbias(sim: pd.Series, obs: pd.Series) -> float:
    return 100.0 * (sim - obs).sum() / obs.sum()


def main() -> None:
    ref = pd.read_csv(REF_CSV).set_index("year")

    with FastRunner() as r:
        r.run()
        yld = r.yields().set_index("year")
        wb = r.read("hru_wb_yr.txt").set_index("yr")

    rows = []
    for year in ref.index:
        if year not in yld.index:
            continue
        rows.append({
            "year": year,
            "crop": CROP.get(ref.loc[year, "crop"], ref.loc[year, "crop"]),
            "swat+": float(yld.loc[year, "yld(t)"]),
            "ref": float(ref.loc[year, "yld_t_ha"]),
            "gracenet": GRACENET.get(year, float("nan")),
            "irr": float(wb.loc[year, "irr"]),
            "ref_irr": float(ref.loc[year, "irr_mm"]),
            "et": float(wb.loc[year, "et"]),
            "ref_et": float(ref.loc[year, "et_mm"]),
        })
    df = pd.DataFrame(rows)

    print("Annual dry-matter yield (t/ha), irrigation and ET (mm)\n")
    print(df.to_string(index=False, float_format=lambda v: f"{v:8.2f}"))

    print(f"\nyield  PBIAS vs reference: {pbias(df['swat+'], df['ref']):+6.1f} %")
    meas = df.dropna(subset=["gracenet"])
    print(f"yield  PBIAS vs GRACEnet : {pbias(meas['swat+'], meas['gracenet']):+6.1f} %")
    print(f"        (reference vs GRACEnet: {pbias(meas['ref'], meas['gracenet']):+6.1f} %)")
    print(f"irrig  PBIAS vs reference: {pbias(df['irr'], df['ref_irr']):+6.1f} %")
    print(f"ET     PBIAS vs reference: {pbias(df['et'], df['ref_et']):+6.1f} %")

    print("\nBy crop (yield PBIAS vs reference):")
    for crop, g in df.groupby("crop"):
        print(f"  {crop}: {pbias(g['swat+'], g['ref']):+6.1f} %   "
              f"(n={len(g)}, mean SWAT+ {g['swat+'].mean():5.2f} vs ref {g['ref'].mean():5.2f})")


if __name__ == "__main__":
    main()
