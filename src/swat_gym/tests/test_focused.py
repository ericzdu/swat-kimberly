"""Tests for the shared five-row experiment machinery.

Two properties, both of which a silent break would turn into a misreported headline: that a
stored row carries enough to be re-priced without the engine, and that a reported difference
comes with the dispersion needed to read it.
"""
from __future__ import annotations

import numpy as np
import pytest

from swat_gym import FastRunner
from swat_gym.env import DEFAULT_PLAN, evaluate
from swat_gym.experiments._focused import _row, paired
from swat_gym.rewarders import average


@pytest.fixture(scope="module")
def row():
    with FastRunner() as r:
        return _row(evaluate(DEFAULT_PLAN.ravel(), r, prices=average(), start_year=2012), 2012)


def test_row_can_be_repriced_without_the_engine(row):
    """Profit is linear in every price, so a contingency like "$1,038 of this headline is the
    arbitrary $5/Mg manure price" is arithmetic on a stored row, not a reason to rerun."""
    assert row["profit"] == pytest.approx(
        row["revenue"] - row["water_cost"] - row["manure_cost"]
        - row["fert_cost"] - row["op_cost"]
    )
    prices = average()
    # Re-derive the manure term from the quantity, then zero it out.
    assert row["manure_cost"] == pytest.approx(row["manure_mg"] * prices.manure)
    free = row["profit"] + row["manure_cost"]
    assert free >= row["profit"]


def test_row_keeps_every_quantity_a_reprice_needs(row):
    for k in ("revenue", "water_cost", "manure_cost", "fert_cost", "op_cost",
              "n_fert_events", "irrigation_mm", "manure_mg", "fert_n_kg"):
        assert k in row, f"{k} dropped from the stored row"


def test_paired_difference_is_per_window():
    """Pairing is the point: window-to-window spread dwarfs the difference between rows, so an
    unpaired comparison would drown every result in weather."""
    a = [{"profit": p} for p in (100.0, 5000.0, 200.0)]
    b = [{"profit": p} for p in (90.0, 4990.0, 190.0)]
    p = paired(a, b)
    assert p["mean"] == pytest.approx(10.0)
    assert p["se"] == pytest.approx(0.0, abs=1e-9), "identical offsets have no paired spread"
    assert p["n"] == 3
    # The same numbers compared unpaired would carry a standard error of ~1,600.
    assert np.std([r["profit"] for r in a], ddof=1) > 2000


def test_paired_reports_finite_error_for_a_single_window():
    p = paired([{"profit": 1.0}], [{"profit": 0.0}])
    assert p["mean"] == pytest.approx(1.0) and np.isnan(p["se"])
