"""Port the Portneuf profile into soils.sol, and set the HRU to 1 ha.

**Source: the calibrated ArcSWAT reference model** (`TxtInOut-2/000140001.sol`, HRU 119 /
subbasin 14 — the same Kimberly GRACEnet field), *not* RuFaS. That model reproduces the
GRACEnet measurements closely, so its soil parameterization is the one to match. An earlier
version of this script wrote a RuFaS-derived 6-layer profile to 1500 mm, which differed in
layer count, depth, hydrologic group (B vs C), AWC, Ksat, albedo and organic carbon.

SWAT+ stores available water capacity (AWC = field capacity - wilting point) rather than
FC/WP separately, which is exactly what the reference's "Ave. AW Incl. Rock Frag" row holds.
The HRU (hru1) uses soil '80295'; we rewrite that block in place (keeping the name so
hru-data.hru stays valid) and leave the other soils untouched.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TIO = ROOT / "model" / "TxtInOut"
SOIL_CSV = ROOT / "data" / "soil_gracenet.csv"

SOIL_NAME = "80295"
HYD_GRP = "C"
ANION_EXCL, PERC_CRK = 0.5, 0.5

# Reference profile, one tuple per layer, in soils.sol column order:
#   dp (mm), bd, awc, soil_k (mm/hr), carbon (%), clay, silt, sand, rock (%),
#   alb, usle_k, ec, caco3, ph
# pH and CaCO3 are zero below layer 2 in the reference file; carried across verbatim
# (codes.bsn has carbon=0, so the CENTURY routines that read them are inactive).
LAYERS = [
    (150.0,  1.30, 0.20, 32.40, 1.50, 17.0, 69.3, 13.7, 0.0, 0.30, 0.43, 0.0,  8.0, 7.9),
    (310.0,  1.40, 0.18, 10.15, 0.75,  9.5, 69.3, 21.2, 0.0, 0.30, 0.64, 5.0, 23.0, 8.4),
    (610.0,  1.50, 0.18, 10.15, 0.75,  9.5, 69.3, 21.2, 0.0, 0.30, 0.64, 5.0,  0.0, 0.0),
    (1220.0, 1.40, 0.18, 10.15, 0.75,  9.5, 69.3, 21.2, 0.0, 0.30, 0.64, 5.0,  0.0, 0.0),
]

HRU_AREA_HA = 1.0
LAT, LON = 42.54, -114.32

BD_COL = 1   # index of bd within a LAYERS tuple


def measured_bd() -> list[float]:
    """Bulk density per soils.sol layer, from the GRACEnet measurement rather than the reference.

    ``GraceNet Soil and Nutrient Properties.xlsx::Soil Bulk Density`` samples four plots at
    five depths; ``extract_primary.py`` writes the plot mean to ``data/soil_gracenet.csv``.
    That file was being produced and then never read — the profile below was the ArcSWAT
    reference's, which is plot 203 alone (1.30/1.40/1.50/1.40/1.30) rather than the four-plot
    mean. The differences are small (<=3.4 % per layer) but they propagate into every
    mass-per-hectare conversion the model reports, and there is no reason to prefer one plot's
    profile over the measured mean of all four.

    Samples are assigned to layers by depth and thickness-weighted where a layer spans more
    than one sample (the 610-1220 mm layer covers the 910 and 1220 mm samples).
    """
    df = pd.read_csv(SOIL_CSV).dropna(subset=["bd_g_cm3"]).sort_values("depth_mm")
    tops = [0.0] + [float(d) for d in df["depth_mm"][:-1]]
    df = df.assign(top=tops, thick=lambda d: d["depth_mm"] - d["top"])

    out, lyr_top = [], 0.0
    for lyr in LAYERS:
        lyr_bot = lyr[0]
        span = df[(df["depth_mm"] > lyr_top) & (df["top"] < lyr_bot)]
        out.append(float((span["bd_g_cm3"] * span["thick"]).sum() / span["thick"].sum()))
        lyr_top = lyr_bot
    return out


def main() -> None:
    for lyr_i, bd in enumerate(measured_bd()):
        old = LAYERS[lyr_i][BD_COL]
        LAYERS[lyr_i] = LAYERS[lyr_i][:BD_COL] + (round(bd, 4),) + LAYERS[lyr_i][BD_COL + 1:]
        print(f"soils.sol layer {lyr_i + 1} (to {LAYERS[lyr_i][0]:.0f} mm): "
              f"bd {old} -> {round(bd, 4)} (GRACEnet measured)")

    sol = (TIO / "soils.sol").read_text().splitlines(keepends=True)
    # locate the 80295 header line and capture its indent style from the following layer line
    hdr_i = next(i for i, ln in enumerate(sol) if ln.split()[:1] == [SOIL_NAME])
    old_nly = int(sol[hdr_i].split()[1])
    layer_line = sol[hdr_i + 1]
    prefix = layer_line[: len(layer_line) - len(layer_line.lstrip(" "))]  # leading spaces

    # rebuild header: name nly hyd_grp dp_tot anion_excl perc_crk texture
    dp_tot = LAYERS[-1][0]
    texture = "-_".join(["SIL"] * len(LAYERS))
    new_hdr = (
        f"{SOIL_NAME:<30}{len(LAYERS):>6}{HYD_GRP:>18}{dp_tot:>14.5f}"
        f"{ANION_EXCL:>14.5f}{PERC_CRK:>14.5f}  {texture}\n"
    )
    new_block = [new_hdr] + [
        prefix + "".join(f"{v:>14.5f}" for v in lyr) + "  \n" for lyr in LAYERS
    ]
    sol[hdr_i : hdr_i + 1 + old_nly] = new_block
    (TIO / "soils.sol").write_text("".join(sol))
    print(f"soils.sol: {SOIL_NAME} -> reference Portneuf, {len(LAYERS)} layers to "
          f"{dp_tot:.0f} mm, hyd_grp {HYD_GRP} (was {old_nly} layers)")

    # set HRU area to 1 ha and coordinates to the Kimberly site
    hru = (TIO / "hru.con").read_text().splitlines(keepends=True)
    parts = hru[2].split()
    parts[3] = f"{HRU_AREA_HA:.5f}"   # area (ha)
    parts[4] = f"{LAT:.5f}"
    parts[5] = f"{LON:.5f}"
    # reassemble with generous spacing (SWAT+ reads free-format)
    hru[2] = "  ".join(parts) + "  \n"
    (TIO / "hru.con").write_text("".join(hru))
    print(f"hru.con: area -> {HRU_AREA_HA} ha, lat/lon -> {LAT} / {LON}")

    resize_containing_objects()


#: Objects that inherit the a10 catchment's 1431.72 ha and must follow the HRU down to 1 ha.
#: Each entry is (filename, first data line index, column indices holding an area).
#: ``object.cnt`` is the load-bearing one -- its ``ls_area``/``tot_area`` are what SWAT+
#: normalises the basin-level tables by.
CONTAINERS = [
    ("object.cnt", 2, (1, 2)),
    ("aquifer.con", 2, (3,)),
    ("rout_unit.con", 2, (3,)),
    ("ls_unit.def", 3, (2,)),
    ("chandeg.con", 2, (3,)),
]


def resize_containing_objects() -> None:
    """Shrink the routing unit, landscape unit and aquifers to the HRU's area.

    The a10 template's HRU sits inside a 1431.72 ha catchment. ``hru.con`` was resized to
    1 ha, but the objects *containing* it were not, so every table SWAT+ normalises by an
    object area rather than by land area -- ``basin_aqu_*`` above all -- came out diluted by
    a factor of ~1432. Recharge read 0.04 mm against 62 mm of soil percolation, and nitrate
    reaching groundwater read ~0.1 kg/ha against a real value two orders of magnitude larger.
    Nothing was mis-simulated; the reported units were simply not per-field.

    This matters beyond tidiness: ``basin_aqu_yr.no3_rchg`` is the leaching externality in the
    gym's reward, and at 1/1432 scale it would have looked like a constant zero.
    """
    for name, line_i, cols in CONTAINERS:
        path = TIO / name
        lines = path.read_text().splitlines(keepends=True)
        changed = []
        for i in range(line_i, len(lines)):
            parts = lines[i].split()
            if len(parts) <= max(cols):
                continue
            changed.append(parts[1] if len(cols) == 1 else parts[0])
            for col in cols:
                parts[col] = f"{HRU_AREA_HA:.5f}"
            lines[i] = "  ".join(parts) + "  \n"
        path.write_text("".join(lines))
        print(f"{name}: area -> {HRU_AREA_HA} ha for {', '.join(changed)}")


if __name__ == "__main__":
    main()
