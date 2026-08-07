#!/usr/bin/env python3
"""Nitrogen response on top of measured practice — does the fertiliser price bind on its own?

The question this answers: if the agent may buy mineral N with **no loading cap**, where does
it stop? If the marginal value of nitrogen falls below the urea price inside a sensible range,
the input cost is a sufficient brake and no invented cap is needed — the policy discovers a
sane rate because over-applying loses money.

Design choices that matter:

* **Mineral N is swept *on top of* the measured manure**, not on a bare field. The measured
  rotation already supplies 2,090 kg N/ha, so a sweep from zero would answer a question about
  a field that does not exist. The stale `runs/exp1_n_response.json` (2026-07-30) did exactly
  that, which is why its optimum looked so generous.
* **No cap** (`max_n=None`). `MAX_N_LOADING` is a policy choice, not a measurement, and
  measured practice already violates it. Here it is a *reported diagnostic*: if the optimum
  lands above it, that is a finding about loading policy.
* **Applied to the annual crops only.** Alfalfa fixes its own nitrogen; fertilising it is not
  practice and would confound the response.
* Irrigation is held at the measured schedule, so only nitrogen moves.

    uv run python scripts/n_response.py
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from swat_gym.constrainers import MAX_N_LOADING, repair
from swat_gym.env import DEFAULT_PLAN, N_YEARS, SPINUP, decode_year, time_sim
from swat_gym.fastrunner import FastRunner
from swat_gym.monthly import default_monthly_irr, year_events
from swat_gym.rewarders import average, profit
from swat_gym.schedule import build
from swat_gym.windows import TEST_YEARS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "n_response.json"

#: kg N/ha/yr of mineral N added to each annual-crop year, on top of measured manure.
DOSES = (0, 25, 50, 100, 150, 200, 300, 400, 600)

#: Two splits, mirroring DEFAULT_ACTION's timing (DOY 120 and 152).
SPLIT_DAYS = (120, 152)


def _plan_with_mineral(dose_kg: float):
    """Measured plan + ``dose_kg`` of mineral N per annual-crop year, split over two passes.

    Irrigation is rendered exactly as the experiments render it — monthly volumes split into
    passes of at most ``MAX_EVENT_MM`` — so the leaching reported here is the leaching an arm
    would actually see. Building this diagnostic on a different cadence answers a question
    about a regime the experiments never enter.
    """
    month_mm = default_monthly_irr()
    plan = []
    for y in range(N_YEARS):
        a = decode_year(DEFAULT_PLAN[y])
        # Same renderer as the experiments: monthly volume -> <=MAX_EVENT_MM passes.
        a = replace(a, irr_depth=0.0, irr_interval=0, irr_month_depths=None,
                    irr_day_depths=year_events(month_mm[y], a.crop))
        if dose_kg > 0 and a.crop != "alfa":
            a = replace(a, fert_splits=tuple((d, dose_kg / 2.0) for d in SPLIT_DAYS))
        else:
            a = replace(a, fert_splits=())
        plan.append(a)
    # Rotation constraints only — the cap is deliberately not enforced here.
    return repair(plan, max_n=None)


def _n_flows(runner) -> dict:
    """Plant uptake and the soil-supplied share, from `basin_nb_yr`.

    Not `hru_nb_yr` — the runner trims `print.prt` to `printprt.GYM_OUTPUTS` and only the
    basin-level nutrient balance is emitted. Uptake is whole-plant, and the share met by
    legume fixation never passes through the soil pool, so the soil-supplied uptake that a
    nitrogen balance should be closed against is ``nuptake - fixn`` (PROVENANCE 5i).
    """
    nb = runner.read("basin_nb_yr.txt")
    tot = lambda c: float(nb[c].sum()) if c in nb.columns else 0.0
    uptake, fixn = tot("nuptake"), tot("fixn")
    return {"n_uptake_kg": uptake, "n_fixed_kg": fixn,
            "soil_uptake_kg": max(0.0, uptake - fixn),
            "mineralised_kg": tot("act_nit_n"), "denit_kg": tot("denit")}


def main() -> list[dict]:
    prices = average()
    windows = list(TEST_YEARS)
    rows = []

    with FastRunner() as runner:
        for dose in DOSES:
            edits = build(_plan_with_mineral(dose))
            acc = []
            for sy in windows:
                edits["time.sim"] = time_sim(sy, N_YEARS + SPINUP)
                runner.run(edits)
                d = profit(runner, prices)
                y = runner.yields()
                acc.append({
                    "profit": d["profit"], "revenue": d["revenue"],
                    "fert_cost": d["fert_cost"], "n_applied_kg": d["n_applied_kg"],
                    "mineral_n_kg": d["fert_n_kg"], "no3_kg": d["no3_leached_kg"],
                    "n2o_kg": d["n2o_kg"], "irrigation_mm": d["irrigation_mm"],
                    "yield_mg": float(y["yld(t)"].sum()) if len(y) else 0.0,
                    **_n_flows(runner),
                })
            m = {k: (float(np.mean([a[k] for a in acc])) if acc[0][k] is not None else None)
                 for k in acc[0]}
            rows.append({"dose_kg_ha_yr": dose, **m, "n_windows": len(acc)})
            print(f"  dose {dose:>4} -> profit {m['profit']:>8.0f}  "
                  f"N {m['n_applied_kg']:>7.0f}  NO3 {m['no3_kg']:>6.2f}", flush=True)

    urea = prices.fert_n
    hdr = (f"{'dose':>6}{'N tot':>8}{'profit':>9}{'dProfit':>9}{'$/kgN':>8}"
           f"{'yield':>8}{'NO3':>8}{'N2O':>8}{'uptake':>8}{'surplus':>9}")
    print("\n" + hdr); print("-" * len(hdr))
    prev = None
    for r in rows:
        dp = r["profit"] - prev["profit"] if prev else None
        dn = r["n_applied_kg"] - prev["n_applied_kg"] if prev else None
        mv = dp / dn if dn else None
        up = r.get("soil_uptake_kg")
        surplus = (r["n_applied_kg"] - up) if up is not None else None
        print(f"{r['dose_kg_ha_yr']:>6}{r['n_applied_kg']:>8.0f}{r['profit']:>9.0f}"
              f"{(f'{dp:+.0f}' if dp is not None else '-'):>9}"
              f"{(f'{mv:+.2f}' if mv is not None else '-'):>8}"
              f"{r['yield_mg']:>8.1f}{r['no3_kg']:>8.2f}{r['n2o_kg']:>8.1f}"
              f"{(f'{up:.0f}' if up is not None else '-'):>8}"
              f"{(f'{surplus:.0f}' if surplus is not None else '-'):>9}")
        prev = r

    best = max(rows, key=lambda r: r["profit"])
    print(f"\nurea price {urea:.2f} $/kg N — already inside `profit`, so the marginal column "
          f"above is NET of it: the optimum is where it crosses ZERO, not {urea:.2f}.")
    print(f"profit-maximising dose: {best['dose_kg_ha_yr']} kg N/ha/yr "
          f"(total applied {best['n_applied_kg']:.0f} kg N/ha)")
    print(f"MAX_N_LOADING = {MAX_N_LOADING:.0f} kg N/ha/yr is reported, not enforced; "
          f"the optimum {'EXCEEDS' if best['n_applied_kg'] / 4 > MAX_N_LOADING else 'sits below'} it")
    # How far does pricing nitrate move the optimum? Exact arithmetic on the stored rows.
    print("\noptimal dose under a nitrate price (profit - lambda_n x NO3):")
    for lam in (0, 8, 16, 40, 100, 250):
        top = max(rows, key=lambda r: r["profit"] - lam * r["no3_kg"])
        print(f"  lambda_n = {lam:>4} $/kg N  ->  dose {top['dose_kg_ha_yr']:>4} kg N/ha/yr, "
              f"NO3 {top['no3_kg']:>6.2f}, scored {top['profit'] - lam * top['no3_kg']:>9.0f}")
    dnd = ((rows[-1]["no3_kg"] - rows[0]["no3_kg"])
           / (rows[-1]["n_applied_kg"] - rows[0]["n_applied_kg"]))
    print(f"  marginal leaching fraction dNO3/dN = {dnd:.4f} "
          f"({100 * dnd:.2f}% of each extra kg N leaches)")

    dn0 = rows[0]["no3_kg"]
    print(f"leaching over the sweep: {dn0:.2f} -> {rows[-1]['no3_kg']:.2f} kg N/ha "
          f"({100 * rows[-1]['no3_kg'] / max(rows[-1]['n_applied_kg'], 1e-9):.2f}% of applied N "
          "at the top dose)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"urea_price": urea, "doses": rows}, indent=2))
    print(f"-> {OUT}")
    return rows


if __name__ == "__main__":
    main()
