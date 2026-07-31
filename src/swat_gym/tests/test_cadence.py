"""Tests for the split mineral-N program and the cadence sweep.

The load-bearing ones here are about *fairness of the comparison* rather than correctness of a
number. Exp 1c asks whether a finer cadence pays, and there are two ways to get a false "no":
let dimensionality grow with k so CMA-ES under-converges at high k, or let the constraint
repair silently reduce k. Both are asserted against.
"""
from __future__ import annotations

import numpy as np
import pytest

from swat_gym import FastRunner
from swat_gym.constrainers import MAX_N_LOADING, feasible, mineral_n, repair, total_n
from swat_gym.experiments.exp1c_cadence import (CADENCES, DECISION_MONTHS, PARAMS_PER_YEAR,
                                                ROTATION, decode)
from swat_gym.env import N_YEARS
from swat_gym.rewarders import average, fert_applied, profit
from swat_gym.fastrunner import TXTINOUT
from swat_gym.schedule import (MINERAL_N_FRAC, MINERAL_SOURCE, YearAction, _doy, _md,
                                build)


# --- the split program ---------------------------------------------------------------------

def test_splits_emit_one_op_each():
    """fert_splits is keyed by day-of-year, so month 4/6/8 means _doy(m, 1)."""
    a = YearAction(crop="corn", manure_mg=0.0, irr_depth=0.0,
                   fert_splits=tuple((_doy(m, 1), 50.0) for m in (4, 6, 8)))
    sch = build([a])["management.sch"]
    rows = [ln.split() for ln in sch.splitlines() if ln.split()[:1] == ["fert"]]
    assert len(rows) == 3
    assert [int(r[1]) for r in rows] == [4, 6, 8]
    assert [int(r[2]) for r in rows] == [1, 1, 1]
    for r in rows:
        assert float(r[6]) == pytest.approx(50.0 / MINERAL_N_FRAC[MINERAL_SOURCE], rel=1e-6)


def test_split_day_of_year_is_not_quantised_to_months():
    """The timing lever needs day resolution — DOY 100 must land on 10 April, not 1 April."""
    a = YearAction(crop="corn", manure_mg=0.0, irr_depth=0.0, fert_splits=((100, 40.0),))
    row = next(ln.split() for ln in build([a])["management.sch"].splitlines()
               if ln.split()[:1] == ["fert"])
    assert (int(row[1]), int(row[2])) == (4, 10)


def test_splits_supersede_the_scalar_application():
    """Both set must not double-apply — the schedule and the cap have to agree on which wins."""
    a = YearAction(crop="corn", manure_mg=0.0, irr_depth=0.0,
                   fert_n_kg=999.0, fert_splits=((_doy(5, 1), 100.0),))
    sch = build([a])["management.sch"]
    rows = [ln.split() for ln in sch.splitlines() if ln.split()[:1] == ["fert"]]
    assert len(rows) == 1
    assert mineral_n(a) == pytest.approx(100.0)


def test_zero_rate_splits_are_skipped():
    a = YearAction(crop="corn", manure_mg=0.0, irr_depth=0.0,
                   fert_splits=((_doy(4, 1), 0.0), (_doy(6, 1), 80.0)))
    sch = build([a])["management.sch"]
    assert sum(ln.split()[:1] == ["fert"] for ln in sch.splitlines()) == 1


# --- fairness of the sweep -----------------------------------------------------------------

@pytest.mark.parametrize("k", CADENCES)
def test_dimensionality_is_constant_across_cadence(k):
    """The point of the parameterisation: k must not change the size of the search."""
    x = np.full(N_YEARS * PARAMS_PER_YEAR, 0.5)
    plan = decode(x, k)
    assert len(plan) == N_YEARS
    assert x.size == N_YEARS * PARAMS_PER_YEAR == 21


@pytest.mark.parametrize("k", CADENCES)
def test_cadence_is_actually_k_on_fertilisable_years(k):
    x = np.full(N_YEARS * PARAMS_PER_YEAR, 0.5)
    for a, crop in zip(decode(x, k), ROTATION):
        if crop == "alfa":
            assert mineral_n(a) == 0.0, "alfalfa must not be fertilised"
        else:
            assert len(a.fert_splits) == k


@pytest.mark.parametrize("k", CADENCES)
def test_repair_preserves_cadence_when_it_clips(k):
    """Clipping to the cap must scale doses, never drop passes — dropping would change k."""
    splits = tuple((_doy(DECISION_MONTHS[i % len(DECISION_MONTHS)], 1), 500.0)
                   for i in range(k))
    a = YearAction(crop="corn", manure_mg=0.0, fert_splits=splits)
    fixed = repair([a])[0]
    assert len(fixed.fert_splits) == k
    assert total_n(fixed) == pytest.approx(MAX_N_LOADING)
    assert feasible([fixed])
    rates = [kg for _, kg in fixed.fert_splits]
    assert max(rates) == pytest.approx(min(rates)), "equal doses must stay equal"


@pytest.mark.parametrize("k", CADENCES)
def test_all_applications_land_inside_the_decision_window(k):
    for x in (np.zeros(21), np.full(21, 0.5), np.ones(21)):
        for a in decode(x, k):
            for doy, _ in a.fert_splits:
                mon = _md(doy)[0]
                assert DECISION_MONTHS[0] <= mon <= DECISION_MONTHS[-1], (
                    f"k={k} put an application in month {mon} (doy {doy})")


def test_cap_can_be_disabled():
    x = np.ones(21)  # total N at the top of its range in every year
    capped = decode(x, 4)
    uncapped = decode(x, 4, max_n=None)
    assert max(total_n(a) for a in capped) == pytest.approx(MAX_N_LOADING)
    assert max(total_n(a) for a in uncapped) == pytest.approx(MAX_N_LOADING)
    # With the cap disabled and a higher ceiling the plan must be free to exceed it.
    assert feasible(uncapped, max_n=None)


# --- against the engine ---------------------------------------------------------------------

def test_pass_cost_grows_with_cadence():
    """The mechanism that makes the cadence question answerable at all."""
    prices = average()
    one = [YearAction(crop="corn", manure_mg=0.0, irr_depth=0.0,
                      fert_splits=((_doy(5, 1), 210.0),))]
    three = [YearAction(crop="corn", manure_mg=0.0, irr_depth=0.0,
                        fert_splits=tuple((_doy(m, 1), 70.0) for m in (5, 6, 7)))]
    sch1 = build(one)["management.sch"]
    sch3 = build(three)["management.sch"]
    frt = (TXTINOUT / "fertilizer.frt").read_text()
    assert len(fert_applied(sch1, frt)) == 1
    assert len(fert_applied(sch3, frt)) == 3
    # Same total N, so the only reward difference must be the pass cost.
    assert fert_applied(sch1, frt)["n_kg_ha"].sum() == pytest.approx(
        fert_applied(sch3, frt)["n_kg_ha"].sum(), rel=1e-6)
    assert prices.fert_op > 0


def test_split_program_runs_and_matches_engine_nitrogen():
    from swat_gym.experiments.exp1c_cadence import _edits

    plan = [YearAction(crop="corn", manure_mg=0.0, irr_depth=0.0,
                       fert_splits=tuple((_doy(m, 1), 60.0) for m in (5, 6, 7)))]
    with FastRunner() as r:
        r.run(_edits(plan, 2012))
        applied = float(r.read("basin_nb_yr.txt")["fertn"].sum())
        d = profit(r, average())
    assert applied == pytest.approx(180.0, rel=1e-3)
    assert d["n_fert_events"] == 3
    assert d["op_cost"] == pytest.approx(3 * average().fert_op)
