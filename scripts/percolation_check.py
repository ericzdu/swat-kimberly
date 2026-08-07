#!/usr/bin/env python3
"""Is the percolation pathway usable as a leaching signal? (OPEN_ITEMS #11, PROVENANCE 5h)

Both of those records predate the nitrogen refit and are stale: 5h reports `no3_rchg` at
0.02 kg/ha/yr, while the current measured-practice run gives ~0.49. This re-measures.

F1  Water and nitrogen balance at measured practice under the current calibration.
F2  Per-strategy closure, plus the **implied leachate concentration** (kg N / percolation mm).
    That is the diagnostic that matters: leaching and percolation must be consistent with a
    physically possible concentration. Above ~50 mg/L the two pathways disagree and the
    leaching column cannot carry a frontier.

    uv run python scripts/percolation_check.py
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from swat_gym.env import N_YEARS, SPINUP, time_sim
from swat_gym.fastrunner import FastRunner
from swat_gym.monthly import default_monthly_i_free, evaluate_monthly_i
from swat_gym.rewarders import average, profit
from swat_gym.windows import TEST_YEARS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "percolation_check.json"

#: 1 kg N in 1 mm over 1 ha = 1 kg / 10,000 L = 100 mg/L.
MG_L_PER_KG_PER_MM = 100.0
#: Above this the water and nitrate pathways are not telling the same story.
IMPLAUSIBLE_MG_L = 50.0


def _wb(runner) -> dict:
    """Annual-mean water balance for the scored years."""
    wb = runner.read("hru_wb_yr.txt")
    pw = runner.read("hru_pw_yr.txt")
    n = len(wb)
    out = {c: float(wb[c].sum()) / n for c in ("precip", "irr", "et", "perc", "surq_gen")
           if c in wb.columns}
    for c in ("pet",):
        if c in pw.columns:
            out[c] = float(pw[c].sum()) / n
        elif c in wb.columns:
            out[c] = float(wb[c].sum()) / n
    return out


def _summarise(tag: str, runner, prices) -> dict:
    d = profit(runner, prices)
    w = _wb(runner)
    perc_total = w.get("perc", 0.0) * N_YEARS
    no3 = d["no3_leached_kg"]
    # Concentration is only defined where water actually moves. With no percolation and no
    # nitrate the ratio is 0/0 -- undefined, not implausible; scoring it as infinite would
    # condemn the pathway for behaving correctly in a year that drained nothing.
    conc = (no3 / perc_total * MG_L_PER_KG_PER_MM) if perc_total > 1.0 else None
    row = {
        "strategy": tag,
        "irrigation_mm": d["irrigation_mm"],
        "precip_mm_yr": w.get("precip"),
        "et_mm_yr": w.get("et"),
        "pet_mm_yr": w.get("pet"),
        "et_over_pet": (w["et"] / w["pet"]) if w.get("pet") else None,
        "perc_mm_yr": w.get("perc"),
        "surq_mm_yr": w.get("surq_gen"),
        "no3_kg_7yr": no3,
        "no3_kg_yr": no3 / N_YEARS,
        "implied_mg_L": conc,
        "n2o_kg": d.get("n2o_kg"),
        "profit": d["profit"],
    }
    return row


def main() -> dict:
    prices = average()
    rows = []

    # F1 -- measured practice, the row PROVENANCE 5h characterises.
    with FastRunner() as r:
        for sy in TEST_YEARS:
            r.run({"time.sim": time_sim(sy, N_YEARS + SPINUP)})
            rows.append({**_summarise("measured", r, prices), "start_year": sy})

    # F2 -- response of percolation to applied water. If percolation only responds once
    # irrigation exceeds ET demand, the low-water baseline being near zero is correct
    # behaviour rather than a broken pathway.
    base = default_monthly_i_free()
    with FastRunner() as r:
        for scale in (0.6, 0.8, 1.0, 1.2, 1.4, 1.6):
            x = np.clip(base * scale, 0.0, 1.0)
            evaluate_monthly_i(x, r, prices=prices, start_year=2013, max_n=None)
            rows.append({**_summarise(f"default x{scale:g}", r, prices),
                         "start_year": 2013, "scale": scale})

    hdr = (f"{'strategy':<16}{'irr_mm':>9}{'ET':>8}{'PET':>8}{'ET/PET':>8}"
           f"{'perc/yr':>9}{'NO3/yr':>8}{'mg/L':>9}")
    print(hdr)
    print("-" * len(hdr))
    for x in rows:
        c = x["implied_mg_L"]
        print(f"{x['strategy']:<16}{x['irrigation_mm']:>9.0f}{x['et_mm_yr'] or 0:>8.0f}"
              f"{x['pet_mm_yr'] or 0:>8.0f}{(x['et_over_pet'] or 0):>8.2f}"
              f"{x['perc_mm_yr'] or 0:>9.2f}{x['no3_kg_yr']:>8.2f}"
              f"{'  n/a' if c is None else f'{c:>9.1f}'}")

    scaled = [x for x in rows if "scale" in x]
    conc = [x["implied_mg_L"] for x in rows if x["implied_mg_L"] is not None]
    draining = [x for x in scaled if (x["perc_mm_yr"] or 0) > 1.0]
    verdict = {
        "max_implied_mg_L": max(conc) if conc else None,
        "n_rows_with_drainage": len(conc),
        # The physical question: does percolation switch on once irrigation exceeds ET
        # demand, rather than being inert at all application rates?
        "perc_responds_to_water": (
            (scaled[-1]["perc_mm_yr"] or 0) > 20.0 and len(draining) >= 2
            if scaled else None),
        "plausible": bool(conc) and max(conc) < IMPLAUSIBLE_MG_L,
    }
    print()
    if conc:
        print(f"implied concentration     : {min(conc):.1f}-{max(conc):.1f} mg/L "
              f"over {len(conc)} rows that drained (threshold {IMPLAUSIBLE_MG_L})")
    print(f"percolation responds to water: {verdict['perc_responds_to_water']}")
    ok = verdict["plausible"] and verdict["perc_responds_to_water"]
    print(f"VERDICT: leaching column is "
          f"{'usable for within-model ranking' if ok else 'NOT usable'}")
    verdict["usable"] = bool(ok)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"rows": rows, "verdict": verdict}, indent=2))
    print(f"-> {OUT}")
    return verdict


if __name__ == "__main__":
    main()
