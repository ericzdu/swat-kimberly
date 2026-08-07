"""Score the model against every target we have, tiered by whether the target is measured.

The two tiers are kept apart deliberately.

**Tier 1 -- measured.** GRACEnet dry-matter yield for all seven rotation years (2013-2019),
AgriMet TWFI reference evapotranspiration for every simulated year, and the seven-year April
soil-nitrate profile (``scripts/n_trajectory.py``, which explains why that one has to be
reconstructed from fluxes rather than read out of the model).

Yield is reported **per year first**. The aggregate PBIAS is kept, but it is a bias statistic
and it cancels: barley ran +53 % in 2014 and -32 % in 2019, which the crop-level number scores
as +2.3 %.

The simulation runs 2012-2019: a spin-up plus exactly the seven measured years. 2020 used to be
simulated as a repeat of the 2012 barley operations with no irrigation, and being outside the
``nyskip`` window it was scored. The reference column still carries 2020, so it appears here as
a sim/meas gap rather than being silently dropped.

**Tier 2 -- the ArcSWAT reference model's simulated output.** Percolation, N uptake and
nitrate leaching have no measurement here, so agreement with the reference is model-vs-model
and is reported as a prior, never as validation. ET and PET appear in both tiers; the tier-1
comparison is the one that counts.

Irrigation is deliberately absent: the same 158 measured events are an input to both models,
so matching it checks transcription, not behaviour.

    uv run python scripts/calib_report.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

from swat_gym import FastRunner

ROOT = Path(__file__).resolve().parents[1]
REF_CSV = ROOT / "data" / "reference_hru119.csv"

#: Measured GRACEnet annual dry-matter yield (t/ha), from
#: ``USDA GRACEnet/GraceNet crop and manure amounts.xlsx``, sheet ``Crop Yield and Nutrient``
#: (source: Bierer et al. 2022). **All seven rotation years are measured, including both
#: barley years** — an earlier version of this file carried only five and described barley as
#: having no measurement at all. That was wrong, and it understated how far off barley is.
GRACENET = {
    2013: 22.100,    # corn
    2014: 5.900,     # barley
    2015: 9.000,     # alfalfa
    2016: 14.785,    # alfalfa
    2017: 16.158,    # alfalfa
    2018: 22.935,    # corn
    2019: 8.776,     # barley
}

#: Measured nutrient uptake (kg/ha), same sheet. Held but NOT used as a target yet: the
#: sheet's footnote says uptake is "averaged across all years of each crop, alfalfa is **per
#: cutting**, barley N up is just **grain** (whole plant ~240 kg/ha)". That resolves the ~4x
#: disagreement between the 2015 alfalfa figure (147.2) and both models (607-667) — 147.2 is
#: one cutting of several, against a whole-plant annual total. Comparable only after
#: reconciling cuttings and plant part.
GRACENET_NUPTAKE_RAW = {2013: 270.7, 2014: 135.1, 2015: 147.2}

#: Measured reference evapotranspiration from the AgriMet TWFI station (see port_agrimet.py).
#: ``etos`` is GRASS-reference ET, which is the definition SWAT+'s Penman-Monteith PET matches;
#: ``etrs`` is ALFALFA-reference and runs ~35 % higher, so comparing PET against it would be a
#: definitional error, not a model error.
ET_CSV = ROOT / "data" / "observed_et_agrimet.csv"

CROP = {"CSIL": "corn", "BARL": "barl", "ALFA": "alfa"}


def pbias(sim: pd.Series, obs: pd.Series) -> float:
    keep = obs.notna() & sim.notna()
    if not keep.any():
        return float("nan")
    return 100.0 * (sim[keep] - obs[keep]).sum() / obs[keep].sum()


def collect(runner: FastRunner) -> pd.DataFrame:
    """Join a completed run against the reference and the measurements, year by year."""
    ref = pd.read_csv(REF_CSV).set_index("year")
    obs_et = (pd.read_csv(ET_CSV).groupby("year")[["et_mm", "etos_mm", "etrs_mm"]].sum()
              if ET_CSV.is_file() else None)
    yld = runner.yields().set_index("year")
    wb = runner.read("hru_wb_yr.txt").set_index("yr")
    nb = runner.read("basin_nb_yr.txt").set_index("yr")
    aqu = runner.read("basin_aqu_yr.txt").set_index("yr")

    df = pd.DataFrame(index=ref.index)
    df["crop"] = [CROP.get(c, c) for c in ref["crop"]]
    df["yld"] = yld["yld(t)"]
    df["yld_ref"] = ref["yld_t_ha"]
    df["yld_meas"] = [GRACENET.get(y) for y in ref.index]
    for col, src, refcol in [
        ("et", wb["et"], "et_mm"), ("pet", wb["pet"], "pet_mm"),
        ("perc", wb["perc"], "perc_mm"), ("nup", nb["nuptake"], "nup"),
        ("no3", aqu["no3_rchg"], "no3l"),
    ]:
        df[col] = src
        df[f"{col}_ref"] = ref[refcol]
    if obs_et is not None:
        df["pet_meas"] = obs_et["etos_mm"]     # grass-reference ET, measured
        df["etrs_meas"] = obs_et["etrs_mm"]    # alfalfa-reference, for context only
    return df


def report(df: pd.DataFrame, runner: FastRunner | None = None) -> None:
    show = ["crop", "yld", "yld_ref", "yld_meas", "et", "et_ref", "pet", "pet_ref",
            "nup", "nup_ref", "no3", "no3_ref"]
    print(df[show].to_string(float_format=lambda v: f"{v:8.1f}"))

    print("\n-- TIER 1: MEASURED " + "-" * 52)
    meas = df[df["yld_meas"].notna()]
    err = 100.0 * (meas["yld"] - meas["yld_meas"]) / meas["yld_meas"]
    print(f"  GRACEnet dry-matter yield ({len(meas)} years, all rotation years):")
    # Per-year first. A crop-level bias term scores barley's +53/-32 as +2.3 %, which is the
    # cancellation the objective exists to see, so the per-year column leads.
    print("    year   crop      sim     meas      err")
    for year, row in meas.iterrows():
        print(f"    {year}   {row['crop']:<6} {row['yld']:7.1f}  {row['yld_meas']:7.1f}  "
              f"{err[year]:+7.1f} %")
    print(f"    RMS per-year error : {(err ** 2).mean() ** 0.5:6.1f} %   "
          f"(worst {err.abs().max():.1f} %)")
    print(f"    all measured years : {pbias(meas['yld'], meas['yld_meas']):+6.1f} %  "
          f"<- bias only; cancels within a crop")
    for crop, g in df.groupby("crop"):
        if g["yld_meas"].notna().any():
            print(f"    {crop:<16} : {pbias(g['yld'], g['yld_meas']):+6.1f} %  "
                  f"(n={g['yld_meas'].notna().sum()})")
    if "pet_meas" in df:
        n_et = int((df["pet"].notna() & df["pet_meas"].notna()).sum())
        print(f"  AgriMet TWFI reference ET ({n_et} years):")
        print(f"    PET vs meas ETos : {pbias(df['pet'], df['pet_meas']):+6.1f} %   "
              f"({df['pet'].mean():.0f} vs {df['pet_meas'].mean():.0f})")
        print(f"      (the ArcSWAT reference model scores "
              f"{pbias(df['pet_ref'], df['pet_meas']):+.1f} % on the same target)")

    if runner is not None:
        from n_trajectory import report as no3_report
        from n_trajectory import trajectory
        print("  GRACEnet April soil-nitrate profile (7 samplings, 0-122 cm, 4 plots):")
        no3_report(trajectory(runner))

    print("\n-- TIER 2: reference model, simulated (prior, not validation) " + "-" * 14)
    print(f"  yield, all years   : {pbias(df['yld'], df['yld_ref']):+6.1f} %")
    for crop, g in df.groupby("crop"):
        print(f"  {crop:<18} : {pbias(g['yld'], g['yld_ref']):+6.1f} %")
    for var, label in [("et", "ET"), ("pet", "PET"), ("perc", "deep perc"),
                       ("nup", "N uptake"), ("no3", "NO3 leached")]:
        print(f"  {label:<18} : {pbias(df[var], df[f'{var}_ref']):+6.1f} %   "
              f"({df[var].mean():.1f} vs {df[f'{var}_ref'].mean():.1f})")


def main() -> None:
    with FastRunner() as r:
        r.run()
        report(collect(r), runner=r)


if __name__ == "__main__":
    main()
