#!/usr/bin/env python3
"""Is the monthly arm's leaching physical, or an artefact of huge single-day applications?

The monthly action space applies a whole month's water in one ``irrm`` event, up to
``MONTH_DEPTH_MAX = 200`` mm in a day. The weekly space spreads the *same* annual depth over 26
events and leaches essentially nothing. Before treating that as an agronomic finding we need to
know whether SWAT+ is routing 200 mm single-day applications sensibly.

The diagnostic holds **annual applied depth constant** and varies only the number of events, so
event size is the sole difference. What to look for:

* **Surface runoff should rise with event size.** A 200 mm application exceeds any silt-loam
  infiltration capacity, so a physical model sheds part of it. If runoff stays flat while
  percolation absorbs everything, the engine is treating the application as if it infiltrates
  regardless of rate, and the monthly leaching signal is a modelling artefact.
* **The balance should close**: irrigation + precip = ET + percolation + runoff + storage change.

    uv run python scripts/event_size_check.py
"""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np

from swat_gym.constrainers import repair
from swat_gym.env import DEFAULT_PLAN, N_YEARS, SPINUP, decode_year, time_sim
from swat_gym.fastrunner import FastRunner
from swat_gym.monthly import default_monthly_irr
from swat_gym.rewarders import average, profit
from swat_gym.schedule import CALENDAR, _doy, build
from swat_gym.weekly import WEEK_START_DOY

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "event_size_check.json"

#: Events per growing season. 6 is the monthly arm, 26 the weekly one.
N_EVENTS = (3, 6, 13, 26, 52)

#: Annual applied depth, held constant across every cadence (measured 3,938.8 mm / 7 yr).
ANNUAL_MM = 3938.8 / N_YEARS

SEASON_DAYS = 183  # 1 April - 30 September


def _plan(n_events: int):
    """Uniform ``n_events`` applications spanning the season, same annual total each time."""
    depth = ANNUAL_MM / n_events
    step = SEASON_DAYS / n_events
    doys = [int(WEEK_START_DOY + round(i * step)) for i in range(n_events)]
    plan = []
    for y in range(N_YEARS):
        base = decode_year(DEFAULT_PLAN[y])
        cal = CALENDAR[base.crop]
        end = _doy(*cal["cuts"][-1]) if base.crop == "alfa" else _doy(*cal["harvest"])
        acc: dict[int, float] = {}
        for d in doys:
            day = d if d < end else end - 1
            acc[day] = acc.get(day, 0.0) + depth
        plan.append(replace(base, irr_depth=0.0, irr_interval=0, irr_month_depths=None,
                            irr_day_depths=tuple(sorted(acc.items()))))
    return repair(plan, max_n=None), depth


def _wb(runner) -> dict:
    wb = runner.read("hru_wb_yr.txt")
    n = len(wb)
    out = {}
    for c in ("precip", "irr", "et", "perc", "surq_gen", "sw_final", "pet"):
        if c in wb.columns:
            out[c] = float(wb[c].sum()) / n
    return out


def main() -> list[dict]:
    prices = average()
    mm = default_monthly_irr()
    print(f"monthly arm's largest single application in the default plan: "
          f"{mm.max():.1f} mm  (MONTH_DEPTH_MAX is 200)")
    print(f"holding annual depth at {ANNUAL_MM:.1f} mm/yr\n")

    rows = []
    with FastRunner() as runner:
        for n in N_EVENTS:
            plan, depth = _plan(n)
            edits = build(plan)
            edits["time.sim"] = time_sim(2013, N_YEARS + SPINUP)
            runner.run(edits)
            d = profit(runner, prices)
            w = _wb(runner)
            bal = (w.get("precip", 0) + w.get("irr", 0)
                   - w.get("et", 0) - w.get("perc", 0) - w.get("surq_gen", 0))
            rows.append({"n_events": n, "mm_per_event": depth, **w,
                         "no3_kg": d["no3_leached_kg"], "profit": d["profit"],
                         "balance_residual_mm": bal})

    hdr = (f"{'events':>7}{'mm/event':>10}{'irr':>8}{'precip':>8}{'ET':>8}"
           f"{'perc':>9}{'runoff':>8}{'NO3':>8}{'resid':>8}")
    print(hdr); print("-" * len(hdr))
    for r in rows:
        print(f"{r['n_events']:>7}{r['mm_per_event']:>10.1f}{r.get('irr',0):>8.0f}"
              f"{r.get('precip',0):>8.0f}{r.get('et',0):>8.0f}{r.get('perc',0):>9.2f}"
              f"{r.get('surq_gen',0):>8.2f}{r['no3_kg']:>8.2f}"
              f"{r['balance_residual_mm']:>8.1f}")

    # The question is whether runoff *responds* to event size, not whether it is non-zero.
    # An earlier version of this check tested `max(runoff) > 1.0` and passed a model whose
    # runoff was flat at 2.3 mm/yr while event size varied 17-fold — the wrong test.
    runoff = [r.get("surq_gen", 0.0) for r in rows]
    biggest, smallest = rows[0], rows[-1]
    spread = max(runoff) - min(runoff)
    share = spread / (biggest["mm_per_event"] - smallest["mm_per_event"])
    print(f"\nevent size {smallest['mm_per_event']:.1f} -> {biggest['mm_per_event']:.1f} mm "
          f"({biggest['mm_per_event'] / smallest['mm_per_event']:.0f}x)")
    print(f"runoff      {min(runoff):.2f} -> {max(runoff):.2f} mm/yr "
          f"(spread {spread:.2f} mm, {100 * share:.1f}% of the extra depth per event)")
    print(f"percolation {smallest.get('perc', 0):.2f} -> {biggest.get('perc', 0):.2f} mm/yr")

    if spread < 0.1 * biggest["mm_per_event"]:
        print("\n  >>> WARNING: runoff does not respond to application rate. SWAT+ derives "
              "surface runoff from a curve number on *daily precipitation*; irrigation applied "
              "as `irrm` appears to bypass it, so an application of any size infiltrates whole "
              "and the surplus percolates. Leaching in this model is therefore driven by "
              "application *size*, which the action space sets, rather than by a physical "
              "infiltration limit.")
        print("  >>> Consequence: the leaching column ranks action-space resolutions, not "
              "management. Any arm confined to coarse events will leach; any arm with "
              "realistic event sizes (<= ~43 mm here) leaches exactly zero.")
    else:
        print("\n  runoff responds to event size, as a physical model should.")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2))
    print(f"-> {OUT}")
    return rows


if __name__ == "__main__":
    main()
