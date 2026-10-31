"""Localize the per-crop biomass shortfall to a mechanism, without fitting anything.

The yield pathway is not the suspect. ``harv.ops`` applies a biomass-type harvest index
(``gn_corn`` 0.98 / ``gn_barl`` 0.54 / ``gn_alfa`` 0.95, ``harv_eff`` 1.0), and
0.54 x 4.5 t/ha peak biomass reproduces the observed 2.42 t/ha barley yield exactly. So the
gap between this model and both the measurements and the ArcSWAT reference is **biomass
accumulation**, and this script asks where in the accumulation it is lost.

Two questions, one run each:

**1. Is the canopy ever actually closed?** With ``ext_co`` 0.65 a LAI of 4.0 already intercepts
1 - exp(-0.65 x 4) = 93 % of PAR, so the ``lai_pot`` *ceiling* cannot explain a 50 % biomass
shortfall -- raising it to 6.0 buys 6 %. What can is the canopy spending few days near that
ceiling. ``lai_days`` below counts them.

**2. Does realized growth match the radiation it intercepted?** SWAT+ accumulates
``bm_grow = bm_e x 0.5 x solarad x (1 - exp(-ext_co x LAI))``, before stress. Summing that
from the daily table and comparing against realized ``bm_max`` separates "the canopy never
intercepted the radiation" from "it did, and the growth was thrown away by a stress or a
multiplier". The ratio is reported as ``real/pot``.

    uv run python scripts/diagnose_growth.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from swat_gym import FastRunner  # noqa: E402
from swat_gym.fastrunner import TXTINOUT  # noqa: E402
from swat_gym.params import get_value  # noqa: E402

from calib_report import GRACENET  # noqa: E402

REF_CSV = ROOT / "data" / "reference_hru119.csv"
CROP = {"CSIL": "corn", "BARL": "barl", "ALFA": "alfa"}

#: Harvest index actually applied, from ``harv.ops`` (harv_typ = biomass, harv_eff 1.0).
HARV_IDX = {"corn": 0.98, "barl": 0.54, "alfa": 0.95}


def crop_by_year() -> dict[int, str]:
    ref = pd.read_csv(REF_CSV)
    return {int(r.year): CROP.get(r.crop, r.crop) for r in ref.itertuples()}


def plant_params(names=("corn", "barl", "alfa")) -> pd.DataFrame:
    """The growth parameters that set the radiation-use ceiling, straight from plants.plt."""
    text = (TXTINOUT / "plants.plt").read_text()
    cols = ("bm_e", "ext_co", "lai_pot", "harv_idx", "days_mat", "tmp_base", "tmp_opt",
            "frac_hu1", "lai_max1", "frac_hu2", "lai_max2", "hu_lai_decl", "dlai_rate")
    return pd.DataFrame(
        {c: {n: get_value(text, "plants.plt", n, c) for n in names} for c in cols}
    )


def growth_table(day: pd.DataFrame, params: pd.DataFrame, years: dict[int, str]) -> pd.DataFrame:
    """Per crop-year: canopy duration, intercepted-radiation potential, and what was realized."""
    rows = []
    for yr, g in day.groupby("yr"):
        crop = years.get(int(yr))
        if crop is None or crop not in params.index:
            continue
        p = params.loc[crop]
        grow = g[g["bioms"] > 0.0]
        if grow.empty:
            continue

        # Potential accumulation, before any stress: bm_e * 0.5 * SR * (1 - exp(-k*LAI)).
        fpar = 1.0 - np.exp(-p["ext_co"] * grow["lai"])
        pot = (p["bm_e"] * 0.5 * grow["solarad"] * fpar).sum()  # kg/ha
        realized = grow["bm_max"].max()

        rows.append({
            "yr": int(yr),
            "crop": crop,
            "days": len(grow),
            # Days the canopy spent near its own ceiling -- the duration question.
            "lai_pk": grow["lai"].max(),
            "lai>75%": int((grow["lai"] > 0.75 * p["lai_pot"]).sum()),
            "lai_mean": grow.loc[grow["lai"] > 0, "lai"].mean(),
            "fpar_mn": fpar[grow["lai"] > 0].mean(),
            "pot_t": pot / 1000.0,
            "bm_t": realized / 1000.0,
            "real/pot": realized / pot if pot else np.nan,
            "yld_t": realized / 1000.0 * HARV_IDX[crop],
            "meas_t": GRACENET.get(int(yr), np.nan),
            "strsw": grow["strsw"].sum(),
            "strstmp": grow["strstmp"].sum(),
            "strsn": grow["strsn"].sum(),
            "phu": grow["phubas0"].max(),
        })
    return pd.DataFrame(rows)


def main() -> None:
    params = plant_params()
    print("plants.plt growth parameters\n")
    print(params.to_string(float_format=lambda v: f"{v:8.3f}"))

    # trim_outputs=False: the diagnosis needs hru_pw_day and mgt_out, which the gym trims away.
    with FastRunner(trim_outputs=False) as r:
        r.run()
        day = r.read("hru_pw_day.txt")
        tbl = growth_table(day, params, crop_by_year())

    print("\n\nper crop-year: canopy duration, radiation-use budget, realized biomass\n")
    print(tbl.to_string(index=False, float_format=lambda v: f"{v:8.2f}"))

    print("\n  days      = days with standing biomass")
    print("  lai>75%   = days above 75 % of that crop's lai_pot (canopy duration)")
    print("  fpar_mn   = mean fraction of PAR intercepted while green")
    print("  pot_t     = bm_e * 0.5 * solarad * fPAR summed, i.e. unstressed potential (t/ha)")
    print("  real/pot  = realized peak biomass / that potential")
    print("  yld_t     = bm_t * harv.ops harvest index; compare against meas_t")

    print("\n\nbiomass needed to reach the measured yield\n")
    need = tbl.dropna(subset=["meas_t"]).copy()
    need["bm_needed"] = need["meas_t"] / need["crop"].map(HARV_IDX)
    need["shortfall"] = need["bm_needed"] - need["bm_t"]
    need["x"] = need["bm_needed"] / need["bm_t"]
    print(need[["yr", "crop", "bm_t", "bm_needed", "shortfall", "x", "pot_t"]]
          .to_string(index=False, float_format=lambda v: f"{v:8.2f}"))
    print("\n  x = multiple of current biomass required. Compare against pot_t: where "
          "bm_needed < pot_t,\n  the radiation to get there was intercepted and lost "
          "downstream of interception.")


if __name__ == "__main__":
    main()
