"""Sweep one plants.plt / hydrology.hyd parameter and score every crop against measurement.

Built for the Phase-1 question "which parameter is responsible for the opposite-direction
per-crop bias", so it reports **per-crop PBIAS against measured GRACEnet yield** rather than a
single aggregate — an aggregate hides exactly the cancellation that is the problem.

The suspects are the columns SWAT+ has that SWAT2012 does not, which ``port_crops.py``'s
``COLMAP`` therefore cannot fill from the site table and which sit at a10 template defaults
with no provenance: ``lai_min``, ``dlai_rate``, ``plnt_pop1/2``, ``frac_lai1/2``.

    uv run python scripts/diagnose_sweep.py alfa.lai_min 2.0 1.0 0.5 0.1 0.0
    uv run python scripts/diagnose_sweep.py corn.dlai_rate 0.1 0.5 1.0
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from swat_gym import FastRunner  # noqa: E402
from swat_gym.fastrunner import EDITABLE, TXTINOUT  # noqa: E402
from swat_gym.params import CALIBRATABLE, set_value  # noqa: E402

from calib_report import collect, pbias  # noqa: E402

FILE_OF = {
    "lai_min": "plants.plt", "dlai_rate": "plants.plt", "plnt_pop1": "plants.plt",
    "plnt_pop2": "plants.plt", "frac_lai1": "plants.plt", "frac_lai2": "plants.plt",
    "bm_e": "plants.plt", "lai_pot": "plants.plt", "tmp_base": "plants.plt",
    "hu_lai_decl": "plants.plt", "harv_idx": "plants.plt", "days_mat": "plants.plt", "frac_hu1": "plants.plt", "frac_hu2": "plants.plt", "lai_max1": "plants.plt", "lai_max2": "plants.plt",
    "epco": "hydrology.hyd", "esco": "hydrology.hyd", "perco": "hydrology.hyd",
}


def score(df: pd.DataFrame) -> dict[str, float]:
    """Per-crop PBIAS against measured yield, plus the PET sanity bound."""
    meas = df[df["yld_meas"].notna()]
    out = {c: pbias(g["yld"], g["yld_meas"]) for c, g in meas.groupby("crop")}
    out["all"] = pbias(meas["yld"], meas["yld_meas"])
    #: Worst single crop -- the number that actually gates the RL work, since the rotation
    #: lever sees the *spread* between crops, not the mean.
    out["worst"] = max(abs(out[c]) for c in ("corn", "barl", "alfa") if c in out)
    if "pet_meas" in df:
        out["pet"] = pbias(df["pet"], df["pet_meas"])
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("param", help="row.column, e.g. alfa.lai_min")
    ap.add_argument("values", nargs="+", type=float)
    args = ap.parse_args()

    row, column = args.param.split(".")
    file = FILE_OF[column]
    src = (TXTINOUT / file).read_text()

    rows = []
    with FastRunner(editable=EDITABLE | CALIBRATABLE) as r:
        for v in args.values:
            r.run({file: set_value(src, file, row, column, v)})
            rows.append({args.param: v, **score(collect(r))})

    df = pd.DataFrame(rows)
    print(f"\nper-crop PBIAS vs measured GRACEnet yield, sweeping {args.param}\n")
    print(df.to_string(index=False, float_format=lambda v: f"{v:+8.1f}"))
    print("\n  worst = largest absolute per-crop bias; this is the RL-readiness number")
    print("  target: every crop within +/-15 %")


if __name__ == "__main__":
    main()
