"""Tests for the mineral-N lever and the nitrogen cap the two sources share.

The load-bearing one is :func:`test_mineral_n_matches_engine_nitrogen`: the action is expressed
in **kg N/ha** but ``op_data3`` wants kg of *product*, so the schedule divides by the product's
``min_n``. Agreeing with ``basin_nb_yr.fertn``, which the engine computes independently by
multiplying that mass back out, is a real check on the conversion rather than a restatement of
it. Getting it backwards would silently apply 2.17x the intended nitrogen.
"""
from __future__ import annotations

import numpy as np
import pytest

from swat_gym import FastRunner
from swat_gym.fastrunner import TXTINOUT
from dataclasses import replace

from swat_gym.constrainers import (MAX_N_LOADING, feasible, manure_n, mineral_n, repair,
                                   total_n, violations)
from swat_gym.env import (ACTION_DIM, ARMS, DEFAULT_PLAN, N_YEARS, TIMING_FLOOR, decode,
                          decode_year)
from swat_gym.rewarders import AVERAGE_YEARS, average, fert_applied, nass, profit
from swat_gym.schedule import MINERAL_N_FRAC, MINERAL_SOURCE, YearAction, build


# --- rendering ----------------------------------------------------------------------------

def test_mineral_n_renders_product_mass_not_n_mass():
    """100 kg N of urea is 217.4 kg of product, and it is the product that goes in the file."""
    plan = [YearAction(crop="corn", manure_mg=0.0, fert_n_kg=100.0, irr_depth=0.0)]
    sch = build(plan)["management.sch"]
    # op layout is: typ mon day hu_sch op_data1 op_data2 op_data3
    rows = [ln.split() for ln in sch.splitlines() if ln.split()[:1] == ["fert"]]
    urea = [r for r in rows if r[4] == MINERAL_SOURCE]
    assert len(urea) == 1
    assert float(urea[0][6]) == pytest.approx(100.0 / MINERAL_N_FRAC[MINERAL_SOURCE], rel=1e-6)


def test_zero_mineral_n_emits_no_op():
    sch = build([YearAction(crop="corn", manure_mg=0.0, fert_n_kg=0.0, irr_depth=0.0)])
    assert MINERAL_SOURCE not in sch["management.sch"]


def test_mineral_n_is_not_incorporated():
    """Broadcast urea stays on the surface; incorporating it would hand the lever free N."""
    plan = [YearAction(crop="corn", manure_mg=0.0, fert_n_kg=200.0, irr_depth=0.0)]
    sch = build(plan)["management.sch"]
    assert "gn_disk" not in sch, "mineral N must not pull in the manure incorporation tillage"


def test_unknown_mineral_source_rejected():
    with pytest.raises(ValueError, match="mineral source"):
        YearAction(crop="corn", fert_src="not_a_fertiliser")


# --- the shared cap -----------------------------------------------------------------------

def test_cap_counts_both_sources():
    a = YearAction(crop="corn", manure_mg=20.0, manure_src="gn2013", fert_n_kg=200.0)
    assert mineral_n(a) == pytest.approx(200.0)
    assert total_n(a) == pytest.approx(manure_n(a) + 200.0)
    assert total_n(a) > MAX_N_LOADING
    assert violations([a])


def test_repair_clips_mineral_first_and_keeps_manure():
    """Manure is a disposal stream taken anyway; urea is the purchase that gives way."""
    a = YearAction(crop="corn", manure_mg=20.0, manure_src="gn2013", fert_n_kg=400.0)
    fixed = repair([a])[0]
    assert fixed.manure_mg == pytest.approx(20.0), "manure under the cap must survive intact"
    assert total_n(fixed) == pytest.approx(MAX_N_LOADING)
    assert feasible([fixed])


def test_repair_clips_manure_when_it_breaches_the_cap_alone():
    a = YearAction(crop="corn", manure_mg=90.0, manure_src="gn2014", fert_n_kg=100.0)
    fixed = repair([a])[0]
    assert fixed.fert_n_kg == 0.0
    assert total_n(fixed) == pytest.approx(MAX_N_LOADING)


def test_alfalfa_gets_neither_source():
    """The mineral lever must not inherit the loophole that zeroing manure closed."""
    plan = [YearAction(crop="alfa", manure_mg=40.0, fert_n_kg=300.0) for _ in range(3)]
    for a in repair(plan):
        assert a.manure_mg == 0.0 and a.fert_n_kg == 0.0


def test_repair_is_feasible_and_idempotent_with_mineral_n():
    rng = np.random.default_rng(1)
    for _ in range(50):
        plan = decode(rng.random(N_YEARS * ACTION_DIM), constrain=False)
        fixed = repair(plan)
        assert feasible(fixed), violations(fixed)
        again = repair(fixed)
        assert [(a.crop, a.manure_mg, a.fert_n_kg) for a in again] == \
               [(a.crop, a.manure_mg, a.fert_n_kg) for a in fixed]


# --- action space -------------------------------------------------------------------------

def test_measured_practice_applies_no_mineral_n():
    """The human bar buys no nitrogen — that is the counterfactual the N arm is scored against."""
    for row in DEFAULT_PLAN:
        assert mineral_n(decode_year(row)) == 0.0


def test_n_arm_owns_both_sources_and_nothing_else():
    # manure rate/day/source + two mineral (rate, day) pairs
    assert set(ARMS["N"]) == {3, 4, 5, 6, 7, 8, 9}
    assert not set(ARMS["N"]) & set(ARMS["I"]), "N and I must not share dimensions"
    assert not set(ARMS["N"]) & set(ARMS["R"])


def test_mineral_range_reaches_the_cap():
    """If the lever cannot reach MAX_N_LOADING, the cap is untestable rather than binding."""
    for rate_dim in (6, 8):
        v = DEFAULT_PLAN[0].copy()
        v[rate_dim] = 1.0
        assert mineral_n(decode_year(v)) == pytest.approx(MAX_N_LOADING), (
            f"a single application on dim {rate_dim} must be able to reach the cap alone")


def test_two_applications_nest_a_single_one():
    """Exp 1c found k>=3 harmful and k=1/k=2 tied, so the arm must be able to *choose* k=1.

    Driving one rate to zero has to yield one application pass, not two at half rate — if the
    zero-rate entry still emitted an op the arm would be paying a pass cost it never chose.
    """
    v = DEFAULT_PLAN[0].copy()
    v[6], v[8] = 1.0, 0.0
    a = decode_year(v)
    assert len(a.fert_splits) == 2, "both slots exist in the action"
    assert sum(kg > 0 for _, kg in a.fert_splits) == 1, "only one is actually applied"
    # Count *mineral* ops only: DEFAULT_PLAN also carries 45 Mg of manure, which is its own
    # legitimate fert op and not the zero-rate split this test is looking for.
    sch = build([replace(a, crop="corn")])["management.sch"]
    rows = [ln.split() for ln in sch.splitlines() if ln.split()[:1] == ["fert"]]
    assert sum(r[4] == MINERAL_SOURCE for r in rows) == 1
    assert len(rows) == 2, "one manure pass + one mineral pass"


def test_timing_floor_is_reachable_and_below_the_old_bound():
    """Both prior runs pinned timing at a floor of DOY 60 / month 4; the range now goes lower."""
    assert TIMING_FLOOR < 60.0
    v = DEFAULT_PLAN[0].copy()
    v[4] = v[7] = v[9] = 0.0
    a = decode_year(v)
    assert a.manure_doy == pytest.approx(TIMING_FLOOR, abs=1)
    assert all(d == pytest.approx(TIMING_FLOOR, abs=1) for d, _ in a.fert_splits)


# --- prices -------------------------------------------------------------------------------

def test_average_is_the_mean_of_the_converted_vectors():
    avg = average()
    for crop in ("alfa", "barl", "corn"):
        expected = np.mean([nass(y).crop[crop] for y in AVERAGE_YEARS])
        assert avg.crop[crop] == pytest.approx(expected)


def test_average_sits_below_the_rotation_crossover():
    """1.489 against a crossover at ~1.60 — close, and the reason the caveat is documented."""
    assert average().alfalfa_ratio() == pytest.approx(1.489, abs=0.01)


def test_mineral_n_is_priced():
    """A zero N price would let the arm buy nitrogen for free and the null would be vacuous."""
    assert average().fert_n > 1.0


# --- against the engine ---------------------------------------------------------------------

def test_fert_applied_separates_the_two_sources():
    plan = [YearAction(crop="corn", manure_mg=10.0, manure_src="gn2013",
                       fert_n_kg=150.0, irr_depth=0.0)]
    sch = build(plan)["management.sch"]
    df = fert_applied(sch, (TXTINOUT / "fertilizer.frt").read_text())
    assert set(df["kind"]) == {"manure", "mineral"}
    assert float(df.loc[df["kind"] == "mineral", "n_kg_ha"].iloc[0]) == pytest.approx(150.0, rel=1e-6)
    assert float(df.loc[df["kind"] == "manure", "mg_ha"].iloc[0]) == pytest.approx(10.0)


def test_mineral_n_matches_engine_nitrogen():
    """The engine's own fertn must agree with the kg N the action asked for.

    This is the conversion cross-check: we write kg of product, SWAT+ multiplies it back by
    min_n, and the round trip has to land on the action's kg N.
    """
    from swat_gym.env import _edits

    plan = [YearAction(crop="corn", manure_mg=0.0, fert_n_kg=180.0, irr_depth=0.0)] * 2
    with FastRunner() as r:
        r.run(_edits(plan, 2012))
        nb = r.read("basin_nb_yr.txt")
        applied = float(nb["fertn"].sum())
    # Two decision years at 180, plus a manure-free, fertiliser-free spin-up year.
    assert applied == pytest.approx(360.0, rel=1e-3)


def test_profit_charges_for_mineral_n():
    from swat_gym.env import _edits

    prices = average()
    plan = [YearAction(crop="corn", manure_mg=0.0, fert_n_kg=200.0, irr_depth=0.0)]
    with FastRunner() as r:
        r.run(_edits(plan, 2012))
        d = profit(r, prices)
    assert d["fert_n_kg"] == pytest.approx(200.0, rel=1e-3)
    assert d["fert_cost"] == pytest.approx(200.0 * prices.fert_n, rel=1e-3)
