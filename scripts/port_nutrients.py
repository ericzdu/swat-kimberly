"""Port initial soil nutrients, topography, hydrology and basin N-cycling parameters.

**Source: the calibrated ArcSWAT reference model** (`TxtInOut-2`, HRU 119 / subbasin 14 —
the same Kimberly GRACEnet field), *not* RuFaS. The reference reproduces the GRACEnet
yields closely, so where the two disagree the reference wins.

The single most consequential value here is ``orgn_min`` (SWAT2012 ``CMN``), the humus
organic-N mineralisation rate factor. The SWAT+ template ships it at **0.0**, meaning humus
organic N never mineralises — which is precisely the "only ~14 %/yr of applied organic
manure N becomes plant-available" symptom that made corn and barley N-limited here while
alfalfa (which fixes its own N) was unaffected. The reference uses 0.0020.

``pet_co`` is SWAT+'s PET multiplier in hydrology.hyd, the structural analogue of the RuFaS
``pet_calibration_coefficient`` (2.4). **This script no longer owns it** —
``scripts/calibrate_petco.py`` does, having fitted it to measured AgriMet grass-reference ETos
(PROVENANCE §5h). Running this port used to reset ``pet_co`` to 1.0, which would silently
discard that calibration; it is now left alone unless ``--pet-co`` is passed explicitly.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
TIO = ROOT / "model" / "TxtInOut"
SOIL_CSV = ROOT / "data" / "soil_gracenet.csv"

HRU_SOILNUT, HRU_TOPO, HRU_HYD = "soilnut1", "topohru1", "hyd1"

# 000140001.hru
REF_SLOPE = 0.012          # HRU_SLP
REF_SLOPE_LEN = 121.951    # SLSUBBSN
REF_DIST_CHA = 35.0        # DIS_STREAM
REF_CANMX = 0.0            # CANMX (the SWAT+ template ships 1.0)

# basins.bsn -> parameters.bsn. The SWAT2012 name is in the comment.
#
# ``orgn_min`` (SWAT2012 CMN) is no longer the reference's 0.0020. ``USDA Long-Term
# Manure/LT Manure Data Summary.xlsx`` contains a completed six-configuration sweep of this
# parameter against *measured* buried-bag net N mineralisation on this soil (209.8 kg N/ha/yr
# over eight years). The accepted configuration is labelled **cmn = 0.001** and scores +4.7 %;
# the SWAT defaults score -36.2 % and the alternatives tested land at -17.8 %, +40.2 % and
# +48.3 %. Someone did this calibration on this site against real data, so their value is used
# rather than the reference model's unexplained doubling of it. Independently confirmed to be
# yield-neutral here: sweeping 0.0003-0.003 moves barley yield by 0.00 t/ha, because N is not
# the limiting factor for these crops (see PROVENANCE 5e).
REF_BASIN = {
    "orgn_min": 0.0010,    # CMN     humus active organic-N mineralisation rate factor
    "n_uptake": 10.0,      # N_UPDIS nitrogen uptake distribution parameter
    "n_perc": 0.20,        # NPERCO  nitrogen percolation coefficient
    "denit_exp": 0.001,    # CDN     denitrification exponential rate coefficient
    "surq_lag": 1.0,       # SURLAG  surface runoff lag time (days)
}


def measured_soil_nutrients() -> tuple[float, float]:
    """Profile-mean initial nitrate and labile P (ppm) from the GRACEnet April-2013 sampling.

    The reference model starts the profile at **zero nitrate** and the SWAT+ template default
    of 5 ppm labile P, then charges the soil with a synthetic 350 kg N/ha elemental fertiliser
    in the 2012 spin-up. That device exists only because the initial state was unknown — and it
    was not unknown. ``GraceNet Soil and Nutrient Properties.xlsx::Soil N & P`` samples four
    plots at five depths in April 2013:

        depth (cm)      15      31      61      91     122
        NO3-N mg/kg  16.68   20.75    7.33    5.63    5.60
        Olsen P      53.35    6.88    1.88    0.88    1.23

    Averaged over the profile by layer mass (thickness x bulk density, the same basis SWAT+
    uses to convert ppm to kg/ha) this gives ~9.3 ppm nitrate and ~8.1 ppm P. Both land close
    to the reference model's own internal state — its 1 Jan 2013 charge was 183.3 kg NO3-N/ha
    == 10.7 ppm, and its converted labile P was 9.45 ppm — which is the independent check that
    the measurement and the reference are describing the same field, and that the zero in the
    ``.chm`` file was an initialisation placeholder rather than a claim about the soil.

    Two caveats, stated rather than hidden. (1) The measurement is April 2013 and it is being
    applied at 1 January 2012; the 2012 spin-up year absorbs the offset. (2) Olsen P is not
    identical to SWAT labile P — the topsoil is 53 mg/kg against a profile mean of 8 — so the
    profile mean is used rather than the surface value, and P remains the weaker of the two.
    """
    df = pd.read_csv(SOIL_CSV).sort_values("depth_mm")
    thick = df["depth_mm"].diff().fillna(df["depth_mm"])
    mass = thick * df["bd_g_cm3"]
    wmean = lambda col: float((df[col] * mass).sum() / mass.sum())   # noqa: E731
    return wmean("no3_n_mg_kg"), wmean("olsen_p_mg_kg")


def _is_float(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def _set_tokens(path: Path, row_name: str, updates: dict[int, float]) -> None:
    """Rewrite the row whose first token is row_name, replacing tokens by index."""
    lines = path.read_text().splitlines(keepends=True)
    for i, ln in enumerate(lines):
        toks = ln.split()
        if toks[:1] != [row_name]:
            continue
        for idx, val in updates.items():
            toks[idx] = f"{val:.5f}"
        desc = toks[-1] if not _is_float(toks[-1]) else ""
        nums = toks[1:-1] if desc else toks[1:]
        lines[i] = (f"{row_name:<22}" + "".join(f"{t:>14}" for t in nums)
                    + (f"  {desc}" if desc else "") + "\n")
        path.write_text("".join(lines))
        return
    raise SystemExit(f"{path.name}: row {row_name!r} not found")


def _set_basin(path: Path, updates: dict[str, float]) -> None:
    """parameters.bsn is one header row plus one value row, matched by name."""
    lines = path.read_text().splitlines()
    header, values = lines[1].split(), lines[2].split()
    for name, val in updates.items():
        if name not in header:
            raise SystemExit(f"{path.name}: parameter {name!r} not in header")
        values[header.index(name)] = f"{val:.5f}"
    lines[2] = "  ".join(values)
    path.write_text("\n".join(lines) + "\n")


def _set_nyskip(path: Path, nyskip: int) -> None:
    """print.prt line index 2 is the nyskip / date-range value row."""
    lines = path.read_text().splitlines()
    toks = lines[2].split()
    toks[0] = str(nyskip)
    lines[2] = "".join(f"{t:<10}" for t in toks)
    path.write_text("\n".join(lines) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pet-co", type=float, default=None,
                    help="PET multiplier. Default: leave whatever calibrate_petco.py set. "
                         "Pass a value only to override that deliberately.")
    args = ap.parse_args()

    # --- initial soil nutrients (nutrients.sol: lab_p = token 2, nitrate = token 3) ---
    nitrate, lab_p = measured_soil_nutrients()
    _set_tokens(TIO / "nutrients.sol", HRU_SOILNUT, {2: lab_p, 3: nitrate})
    print(f"nutrients.sol: nitrate -> {nitrate:.2f} ppm, lab_p -> {lab_p:.2f} ppm "
          f"(GRACEnet measured April 2013, profile mass-weighted)")

    # --- topography (slp = 1, slp_len = 2, lat_len = 3, dist_cha = 4) ---
    _set_tokens(TIO / "topography.hyd", HRU_TOPO,
                {1: REF_SLOPE, 2: REF_SLOPE_LEN, 3: REF_SLOPE_LEN, 4: REF_DIST_CHA})
    print(f"topography.hyd: slp -> {REF_SLOPE}, slp_len/lat_len -> {REF_SLOPE_LEN} m, "
          f"dist_cha -> {REF_DIST_CHA} m")

    # --- hydrology (can_max = token 3, pet_co = token 13) ---
    hyd = {3: REF_CANMX} | ({13: args.pet_co} if args.pet_co is not None else {})
    _set_tokens(TIO / "hydrology.hyd", HRU_HYD, hyd)
    print(f"hydrology.hyd: can_max -> {REF_CANMX}, pet_co -> "
          + (f"{args.pet_co} (overridden)" if args.pet_co is not None
             else "left as calibrated (see calibrate_petco.py)"))

    # --- basin N-cycling parameters ---
    _set_basin(TIO / "parameters.bsn", REF_BASIN)
    print("parameters.bsn: " + ", ".join(f"{k} -> {v}" for k, v in REF_BASIN.items()))

    # --- output: skip the 2012 spin-up year only (reference NYSKIP=1) ---
    _set_nyskip(TIO / "print.prt", 1)
    print("print.prt: nyskip -> 1 (2012 spin-up only; 2013 keeps its HRU diagnostics)")


if __name__ == "__main__":
    main()
