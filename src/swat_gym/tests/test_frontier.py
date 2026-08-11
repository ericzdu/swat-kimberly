"""Frontier arithmetic must agree with the engine, or the whole sweep is fiction."""
from __future__ import annotations

from dataclasses import replace

import pytest

from swat_gym.env import N_YEARS, SPINUP
from swat_gym.experiments._focused import _row
from swat_gym.fastrunner import FastRunner
from swat_gym.frontier import (crossing, dominates, intensities, mean_profit_at, profit_at,
                               sweep)
from swat_gym.monthly import default_monthly_i_free, evaluate_monthly_i
from swat_gym.rewarders import average


@pytest.mark.slow
def test_rescoring_matches_a_real_engine_run():
    """The frontier's central claim: profit at any price is arithmetic, not simulation.

    If this drifts, every sweep table is wrong and nothing warns you — the numbers stay
    plausible because they are computed from a valid identity applied to the wrong terms.
    """
    prices = average()
    x = default_monthly_i_free()
    try:
        with FastRunner() as runner:
            scored = evaluate_monthly_i(x, runner, prices=prices, start_year=2013, max_n=None)
            row = _row(scored, 2013)
            direct = {}
            for w, n in ((0.41, 0.0), (1.20, 0.0), (0.41, 25.0), (2.00, 40.0)):
                p = replace(prices, water=w)
                direct[(w, n)] = evaluate_monthly_i(x, runner, prices=p, start_year=2013,
                                                    no3_price=n, max_n=None)["profit"]
    except Exception as e:  # pragma: no cover - engine may be unavailable
        pytest.skip(f"engine unavailable: {e}")

    for (w, n), engine in direct.items():
        assert profit_at(row, w, n) == pytest.approx(engine, rel=1e-9, abs=1e-6), (
            f"rescoring at water={w} no3={n} gave {profit_at(row, w, n)} "
            f"but the engine says {engine}")


def test_profit_at_is_linear_and_self_consistent():
    row = {"revenue": 25000.0, "irrigation_mm": 4000.0, "manure_cost": 1000.0,
           "fert_cost": 0.0, "op_cost": 20.0, "no3": 10.0,
           "n2o_kg": 40.0, "yield_mg": 100.0}
    assert profit_at(row, 0.41, 0.0) == pytest.approx(25000 - 0.41 * 4000 - 1000 - 20)
    # Doubling the water price subtracts exactly one more water bill.
    assert (profit_at(row, 0.41) - profit_at(row, 0.82)) == pytest.approx(0.41 * 4000)
    # Nitrate enters linearly and only when priced.
    assert (profit_at(row, 0.41, 0.0) - profit_at(row, 0.41, 25.0)) == pytest.approx(25 * 10)


def test_intensities_and_dominance():
    thrifty = [{"revenue": 26000.0, "irrigation_mm": 3900.0, "manure_cost": 1000.0,
                "fert_cost": 0.0, "op_cost": 20.0, "no3": 2.0,
                "n2o_kg": 40.0, "yield_mg": 105.0}]
    thirsty = [{"revenue": 25500.0, "irrigation_mm": 5000.0, "manure_cost": 1000.0,
                "fert_cost": 0.0, "op_cost": 20.0, "no3": 25.0,
                "n2o_kg": 40.4, "yield_mg": 102.0}]
    assert dominates(thrifty, thirsty)
    assert not dominates(thirsty, thrifty)

    i = intensities(thrifty)
    assert i["water_mm_per_Mg"] == pytest.approx(3900 / 105)
    assert i["n2o_kg_per_Mg"] == pytest.approx(40.0 / 105)

    # A dominating strategy wins at every price on the grid — no crossing to find.
    rows = sweep({"thrifty": thrifty, "thirsty": thirsty},
                 water_grid=(0.41, 1.2, 4.0), no3_grid=(0.0, 40.0))
    assert {r["winner"] for r in rows} == {"thrifty"}
    assert crossing(thrifty, thirsty, axis="water") is None or \
        crossing(thrifty, thirsty, axis="water") < 0.41


def test_mean_profit_over_windows():
    rows = [{"revenue": 100.0, "irrigation_mm": 10.0, "manure_cost": 0.0, "fert_cost": 0.0,
             "op_cost": 0.0, "no3": 1.0, "n2o_kg": None, "yield_mg": None},
            {"revenue": 200.0, "irrigation_mm": 20.0, "manure_cost": 0.0, "fert_cost": 0.0,
             "op_cost": 0.0, "no3": 3.0, "n2o_kg": None, "yield_mg": None}]
    assert mean_profit_at(rows, 1.0, 0.0) == pytest.approx(((100 - 10) + (200 - 20)) / 2)
