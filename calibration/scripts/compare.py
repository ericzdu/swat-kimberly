"""Compare the SWAT+ Kimberly run against RuFaS and GRACEnet on the same plot."""
from __future__ import annotations

from pathlib import Path

import pandas as pd

RUN = Path(__file__).resolve().parents[1] / "runs" / "latest"

# reference values (measured GRACEnet + calibrated RuFaS), from the RuFaS cross-model study
# dry Mg/ha, all seven rotation years. Both barley years (2014: 5.90, 2019: 8.78) were missing
# here and in compare_reference.py; calib_report.GRACENET is the single source of truth.
from calib_report import GRACENET as GRACENET_YLD  # noqa: E402
GRACENET_N = {2013: 271.0, 2014: 135.1, 2015: 147.2}
RUFAS_AGB = {2013: 18.2, 2018: 21.7}          # peak above-ground biomass Mg/ha (corn)
RUFAS_N = {2013: 317.0, 2018: 380.0}
HRU_AREA_HA = 1.0


def load(name: str) -> pd.DataFrame:
    return pd.read_csv(RUN / name, sep=r"\s+", skiprows=[0, 2], header=0, engine="python")


def main() -> None:
    yld = pd.read_csv(RUN / "basin_crop_yld_yr.txt", sep=r"\s+", skiprows=1, header=0, engine="python")
    yld = yld[yld["yld(t)"] > 0].set_index("year")
    # NB: harv_area accumulates one field-area per CUT, so SWAT+'s own yld(t/ha) is a
    # PER-CUT figure for multi-cut alfalfa. GRACEnet reports annual totals, so divide the
    # annual total yld(t) by the true HRU area instead.
    yld["ann_yld"] = yld["yld(t)"] / HRU_AREA_HA
    yld["cuts"] = (yld["harv_area(ha)"] / HRU_AREA_HA).round().astype(int)
    nb = load("hru_nb_yr.txt").set_index("yr")
    wb = load("hru_wb_yr.txt").set_index("yr")

    print("ANNUAL CROP YIELD (dry Mg/ha)              &   N UPTAKE (kg/ha)")
    print(f"{'yr':>4} {'crop':>6} {'cuts':>5} | {'SWAT+':>6} {'RuFaS':>6} {'GRACEnet':>8} | "
          f"{'SWAT+N':>7} {'RuFaS':>6} {'GN':>5}")
    for yr in range(2013, 2020):
        if yr not in yld.index:
            continue
        crop = yld.loc[yr, "plant_name"]
        sy = yld.loc[yr, "ann_yld"]
        cuts = yld.loc[yr, "cuts"]
        sn = nb.loc[yr, "nuptake"] if yr in nb.index else float("nan")
        print(f"{yr:>4} {crop:>6} {cuts:>5} | {sy:6.1f} {RUFAS_AGB.get(yr,float('nan')):6} "
              f"{GRACENET_YLD.get(yr,float('nan')):>8} | {sn:7.0f} {RUFAS_N.get(yr,float('nan')):>6} {GRACENET_N.get(yr,float('nan')):>5}")

    print(f"\nWATER BALANCE (8-yr mean, mm/yr):  ET {wb.et.mean():.0f}   PET {wb.pet.mean():.0f}   "
          f"deep perc {wb.perc.mean():.0f}   irrig {wb.irr.mean():.0f}")
    print("  reference: RuFaS ET ~865 (incl soil evap), perc 32;  GRACEnet/SWAT-Victor perc 0-46")


if __name__ == "__main__":
    main()
