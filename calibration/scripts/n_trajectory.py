"""Reconstruct the modelled soil-nitrate trajectory and score it against measurement.

**Why a reconstruction rather than an output.** SWAT+ rev 62 does not print the soil nitrate
pool. Every ``no3`` column in every one of the ~24 output tables is either a flux
(``surqno3``, ``lat3no3``, ``tileno3``, ``no3_rchg``, ``denit``) or a store belonging to some
other object (``aquifer.no3_st``, channel and reservoir ``no3_stor``). Enabling the whole
``hru_cb_*`` family does not help: ``hru_soil_snap`` carries the physical profile only (bulk
density, AWC, texture, total carbon) and ``hru_ncycle`` carries transformation *rates*. So the
pool has to be accumulated from the fluxes that enter and leave it.

**What closes and what does not.** At this site the loss terms are negligible — surface and
lateral nitrate, tile drainage, denitrification and recharge together come to under 5 kg/ha in
the worst year and under 0.3 kg/ha in five of the seven. The balance is therefore essentially
*mineralisation in, uptake out*, plus fertiliser in the manure years. One term is unreported:
the applied **ammonium**. The GRACEnet manures are 20 % mineral N by mass and that mineral
fraction is 99 % NH3-N (``fertilizer.frt``), and rev 62 prints neither the nitrification flux
nor the volatilisation loss, so the fate of that ammonium is invisible.

Rather than assume it, the reconstruction **brackets** it: ``lo`` is the pool if every applied
ammonium ion volatilises, ``hi`` if all of it nitrifies and none is lost. The three alfalfa
years apply no fertiliser at all, so there the bracket collapses to a point and the balance is
exact — those are the years the calibration can actually be held to.

**One-step-ahead, not free-run.** Each year is started from the *measured* April pool rather
than from the previous year's simulated one, so a year's score reflects that year's fluxes
instead of inheriting every earlier error. The free-running trajectory is reported alongside
because a model that only works when re-anchored annually is worth knowing about.

    uv run python scripts/n_trajectory.py
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
MEAS_CSV = ROOT / "data" / "soil_no3_gracenet.csv"

#: The measured profile is sampled every April, so the change between two samples is driven by
#: the calendar year in between. Fertiliser goes on ~10 April, just *after* the sampling, which
#: is what makes the alignment clean rather than approximate.
SAMPLE_MONTH = "April"


def measured() -> pd.DataFrame:
    """The April profile-nitrate stock, kg/ha, indexed by year."""
    return pd.read_csv(MEAS_CSV).set_index("year")


def fertiliser_split(txtinout: Path) -> tuple[float, float]:
    """``(mineral fraction of applied N, NH3 fraction of that mineral N)`` for the site manures.

    Derived from ``fertilizer.frt`` rather than hard-coded. All four GRACEnet manures
    (``gn2013``, ``gn2014``, ``gn2018``, ``gn2019``) share the same 0.20 mineral / 0.80 organic
    split, so a single pair of numbers describes every application; the assertion below is what
    guarantees that stays true if the manure analyses are ever re-ported.
    """
    rows = {}
    for line in (txtinout / "fertilizer.frt").read_text().splitlines()[2:]:
        t = line.split()
        if len(t) >= 6 and t[0].startswith("gn"):
            min_n, org_n, nh3 = float(t[1]), float(t[3]), float(t[5])
            rows[t[0]] = (min_n / (min_n + org_n), nh3)
    if not rows:
        raise SystemExit("fertilizer.frt: no gn* GRACEnet manure rows found")
    splits = set(round(v[0], 6) for v in rows.values())
    nh3s = set(round(v[1], 6) for v in rows.values())
    if len(splits) != 1 or len(nh3s) != 1:
        raise SystemExit(
            f"GRACEnet manures no longer share one mineral/NH3 split: {rows}. "
            "The bracket in n_trajectory.py assumes a single pair; make it per-year."
        )
    return splits.pop(), nh3s.pop()


def fluxes(runner) -> pd.DataFrame:
    """Per-year soil-nitrate inputs and outputs, kg/ha, from a completed run."""
    nb = runner.read("basin_nb_yr.txt").set_index("yr")
    ls = runner.read("basin_ls_yr.txt").set_index("yr")
    aqu = runner.read("basin_aqu_yr.txt").set_index("yr")
    min_frac, nh3_frac = fertiliser_split(Path(runner.workdir))

    d = pd.DataFrame(index=nb.index)
    d["mineralised"] = nb["act_nit_n"]              # active humus organic N -> nitrate
    d["fert_min"] = nb["fertn"] * min_frac          # mineral N applied (NH4 + NO3)
    d["fert_nh4"] = d["fert_min"] * nh3_frac        # ...of which ammonium: fate unreported
    d["fert_no3"] = d["fert_min"] - d["fert_nh4"]   # ...and nitrate: enters the pool directly
    d["fixed"] = nb["fixn"]                         # goes to the plant, never to the soil pool
    # Uptake is whole-plant; the share met by fixation never passed through the soil pool.
    d["soil_uptake"] = (nb["nuptake"] - nb["fixn"]).clip(lower=0.0)
    d["losses"] = (nb["denit"] + ls["surqno3"] + ls["lat3no3"] + ls["tileno3"]
                   + aqu["no3_rchg"])
    d["net_lo"] = d["mineralised"] + d["fert_no3"] - d["soil_uptake"] - d["losses"]
    d["net_hi"] = d["net_lo"] + d["fert_nh4"]
    return d


def trajectory(runner) -> pd.DataFrame:
    """Join the reconstruction to the measurement, one-step-ahead and free-running."""
    obs, flux = measured(), fluxes(runner)
    years = [y for y in flux.index if y in obs.index and (y + 1) in obs.index]

    rows = []
    free = float(obs.loc[years[0], "no3_kg_ha"]) if years else float("nan")
    for y in years:
        f, start = flux.loc[y], float(obs.loc[y, "no3_kg_ha"])
        target = float(obs.loc[y + 1, "no3_kg_ha"])
        lo, hi = start + f["net_lo"], start + f["net_hi"]
        rows.append({
            "year": y,
            "obs_start": start,
            "obs_end": target,
            "obs_change": target - start,
            "sim_lo": lo,
            "sim_hi": hi,
            "exact": f["fert_nh4"] < 1e-9,          # no ammonium applied -> bracket is a point
            # Signed distance outside the bracket; 0 when the measurement is inside it.
            "miss": 0.0 if lo <= target <= hi else (target - hi if target > hi else target - lo),
            "free_lo": free + f["net_lo"],
            "free_hi": free + f["net_hi"],
        })
        free = max(0.0, free + 0.5 * (f["net_lo"] + f["net_hi"]))
    return pd.DataFrame(rows).set_index("year")


def score(traj: pd.DataFrame, exact_only: bool = True) -> float:
    """Root-mean-square miss in kg N/ha — 0 when every year lands inside its bracket.

    ``exact_only`` restricts the score to the fertiliser-free years, where the reconstruction
    has no unreported term. Those are the only years the model can be *held* to; the manure
    years still contribute a reported miss, but scoring them would be scoring the width of our
    own ignorance about ammonium.
    """
    g = traj[traj["exact"]] if exact_only else traj
    if g.empty:
        return float("nan")
    return float((g["miss"] ** 2).mean() ** 0.5)


#: Context for the mineralisation rate, both from `PROVENANCE` §5e. Neither is a target here —
#: the first is a different field under a heavier manure regime and is 0-60 cm rather than the
#: full profile; the second is a model. They are quoted because they bracket the same quantity
#: from a measurement and from SWAT2012, and our SWAT+ figure sits far below both.
MINERALISATION_CONTEXT = (
    (209.8, "measured buried-bag net N min, 0-60 cm, LT Manure 30_Annual field (8 yr)"),
    (117.0, "ArcSWAT reference A_MN on *this* field, 2013-2019 mean"),
)


def report(traj: pd.DataFrame, flux: pd.DataFrame | None = None) -> None:
    show = traj[["obs_start", "obs_end", "obs_change", "sim_lo", "sim_hi", "miss", "exact"]]
    print(show.to_string(float_format=lambda v: f"{v:9.1f}"))
    if flux is not None:
        ours = float(flux["mineralised"].mean())
        print(f"\n  humus mineralisation, this model : {ours:6.1f} kg N/ha/yr")
        for value, label in MINERALISATION_CONTEXT:
            print(f"    vs {value:6.1f}  ({ours / value - 1:+.0%})  {label}")
    n_exact = int(traj["exact"].sum())
    print(f"\n  RMS miss, fertiliser-free years only (n={n_exact}) : "
          f"{score(traj):8.1f} kg N/ha")
    print(f"  RMS miss, all years (n={len(traj)})                  : "
          f"{score(traj, exact_only=False):8.1f} kg N/ha")
    inside = int((traj["miss"] == 0).sum())
    print(f"  years landing inside their bracket               : {inside}/{len(traj)}")


def main() -> None:
    from swat_gym import FastRunner

    with FastRunner() as r:
        r.run()
        traj, flux = trajectory(r), fluxes(r)
    print("measured April soil nitrate (kg N/ha, 0-122 cm) vs reconstructed balance\n")
    report(traj, flux)


if __name__ == "__main__":
    main()
