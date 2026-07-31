"""Tests for the profit reward.

The load-bearing one is :func:`test_manure_matches_engine_nitrogen`. The reward reads manure
mass off the schedule's ``op_data3`` while the engine independently computes the nitrogen that
mass carries, so agreeing with ``basin_nb_yr.fertn`` to floating-point is a real cross-check on
the parse -- not a restatement of it.
"""
from __future__ import annotations

import pytest

from swat_gym import FastRunner
from swat_gym.fastrunner import TXTINOUT
from swat_gym.rewarders import Prices, manure_applied, nass, profit


@pytest.fixture(scope="module")
def runner():
    with FastRunner() as r:
        r.run()
        yield r


# --- price vectors ----------------------------------------------------------------------

def test_nass_scenarios_are_ordered_as_published():
    """Alfalfa fell and the alfalfa:corn ratio collapsed in 2024 — the reason prices are swept."""
    p22, p23, p24 = (nass(y) for y in (2022, 2023, 2024))
    assert p22.crop["alfa"] > p23.crop["alfa"] > p24.crop["alfa"]
    assert p22.alfalfa_ratio() == pytest.approx(p23.alfalfa_ratio(), rel=0.02)
    assert p24.alfalfa_ratio() < 0.8 * p22.alfalfa_ratio()


def test_at_ratio_moves_alfalfa_only():
    base = nass(2024)
    swept = base.at_ratio(2.0)
    assert swept.alfalfa_ratio() == pytest.approx(2.0)
    assert swept.crop["alfa"] == pytest.approx(2.0 * base.crop["corn"])
    for c in ("corn", "barl"):
        assert swept.crop[c] == base.crop[c]
    assert swept.water == base.water and swept.manure == base.manure


def test_dry_matter_conversion_is_applied():
    """$/Mg DM must exceed the $/short ton as-fed figure: smaller unit, and moisture removed."""
    assert nass(2024).crop["alfa"] > 154.0


# --- reading the run --------------------------------------------------------------------

def test_manure_matches_engine_nitrogen(runner):
    """Schedule-parsed manure mass x composition == the N the engine says was applied."""
    sch = (TXTINOUT / "management.sch").read_text()
    frt = (TXTINOUT / "fertilizer.frt").read_text()
    parsed = manure_applied(sch, frt)

    assert len(parsed) == 4, "the four measured GRACEnet manure applications"
    assert parsed["mg_ha"].sum() > 0
    engine_n = runner.read("basin_nb_yr.txt")["fertn"].sum()
    assert parsed["n_kg_ha"].sum() == pytest.approx(engine_n, rel=1e-4)


# --- the reward itself ------------------------------------------------------------------

def test_profit_terms_are_consistent(runner):
    d = profit(runner, nass(2024))
    assert d["profit"] == pytest.approx(
        d["revenue"] - d["water_cost"] - d["manure_cost"] - d["fert_cost"]
        - d["op_cost"] - d["leach_cost"]
    )
    assert d["revenue"] > 0 and d["irrigation_mm"] > 0


def test_application_passes_are_charged(runner):
    """The measured schedule is four manure passes; each one costs a trip across the field."""
    d = profit(runner, nass(2024))
    assert d["n_fert_events"] == 4
    assert d["op_cost"] == pytest.approx(4 * nass(2024).fert_op)
    free = profit(runner, nass(2024, fert_op=0.0))
    assert free["op_cost"] == 0.0
    assert d["profit"] == pytest.approx(free["profit"] - d["op_cost"])


def test_leaching_is_excluded_unless_priced(runner):
    """The externality is reported alongside by default, never silently inside profit."""
    free = profit(runner, nass(2024))
    assert free["leach_cost"] == 0.0
    assert free["no3_leached_kg"] > 0, (
        "no3_rchg is zero — the leaching ablation has no signal. See the deep-percolation "
        "note in port_crops.OVERRIDES."
    )

    priced = profit(runner, nass(2024), no3_price=10.0)
    assert priced["leach_cost"] == pytest.approx(10.0 * free["no3_leached_kg"])
    assert priced["profit"] < free["profit"]


def test_water_cost_scales_with_price(runner):
    base = nass(2024)
    doubled = profit(runner, Prices(base.crop, base.water * 2, base.manure, "x2"))
    assert doubled["water_cost"] == pytest.approx(2 * profit(runner, base)["water_cost"])


def test_unpriced_crop_raises(runner):
    """A rotation the price vector does not cover must fail loudly, not score as zero revenue."""
    with pytest.raises(KeyError, match="no price for"):
        profit(runner, Prices({"corn": 150.0}, 0.4, 0.0, "incomplete"))
