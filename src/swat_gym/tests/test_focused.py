"""Tests for the shared five-row experiment machinery.

Two properties, both of which a silent break would turn into a misreported headline: that a
stored row carries enough to be re-priced without the engine, and that a reported difference
comes with the dispersion needed to read it.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from swat_gym import FastRunner
from swat_gym.env import DEFAULT_PLAN, default_free, evaluate
from swat_gym.experiments._focused import _max_n_arg, _row, optimize_fixed, paired, run
from swat_gym.rewarders import average
from swat_gym.windows import TEST_YEARS, effective_n


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
    assert p["se_ess"] == pytest.approx(0.0, abs=1e-9), "identical offsets have no paired spread"
    assert p["se_naive"] == pytest.approx(0.0, abs=1e-9)
    assert p["n"] == 3
    # The same numbers compared unpaired would carry a standard error of ~1,600.
    assert np.std([r["profit"] for r in a], ddof=1) > 2000


def test_paired_reports_finite_error_for_a_single_window():
    p = paired([{"profit": 1.0}], [{"profit": 0.0}])
    assert p["mean"] == pytest.approx(1.0) and np.isnan(p["se_ess"])


# -- rule 7: overlapping windows are not independent draws ---------------------------------

def test_paired_has_no_naive_se_under_the_reportable_name():
    """``se`` is deliberately absent, so a stale consumer fails loudly instead of publishing.

    The five held-out windows share up to seven of their eight calendar years. ``sd/sqrt(5)``
    is the number rule 7 forbids; it survives as ``se_naive`` only so the ratio can be shown.
    """
    rows_a = [{"profit": p, "start_year": sy}
              for p, sy in zip((100.0, 400.0, 250.0, 900.0, 600.0), TEST_YEARS)]
    rows_b = [{"profit": 0.0, "start_year": sy} for sy in TEST_YEARS]
    p = paired(rows_a, rows_b)
    assert "se" not in p, "the naive standard error must not be reachable under this name"
    assert p["ess"] == pytest.approx(effective_n(TEST_YEARS))
    assert p["ess"] < p["n"], "overlapping windows cannot carry n windows of evidence"
    assert p["se_ess"] > p["se_naive"], "ignoring overlap always overstates precision"
    assert p["se_ess"] / p["se_naive"] == pytest.approx(np.sqrt(p["n"] / p["ess"]))


def test_effective_sample_size_of_the_test_split():
    """Five eight-year windows one year apart carry 1.25 windows of independent weather."""
    assert effective_n(TEST_YEARS) == pytest.approx(1.25)
    assert effective_n([2013]) == 1.0
    # Disjoint windows are independent, so ESS is the count.
    assert effective_n([1995, 2013]) == pytest.approx(2.0)


def test_ess_interval_is_wider_than_the_bootstrap_one():
    """Both are reported; the bootstrap resamples windows as if they were exchangeable."""
    rows_a = [{"profit": p, "start_year": sy}
              for p, sy in zip((100.0, 400.0, 250.0, 900.0, 600.0), TEST_YEARS)]
    rows_b = [{"profit": 0.0, "start_year": sy} for sy in TEST_YEARS]
    p = paired(rows_a, rows_b)
    boot_w = p["ci95_boot"][1] - p["ci95_boot"][0]
    ess_w = p["ci95_ess"][1] - p["ci95_ess"][0]
    assert ess_w > boot_w
    assert p["resolvable"] is (p["ci95_ess"][0] * p["ci95_ess"][1] > 0)


def test_paired_bootstrap_is_deterministic():
    """An interval must be a property of the rows, not of when it was computed."""
    rows_a = [{"profit": p, "start_year": sy}
              for p, sy in zip((100.0, 400.0, 250.0, 900.0, 600.0), TEST_YEARS)]
    rows_b = [{"profit": 0.0, "start_year": sy} for sy in TEST_YEARS]
    assert paired(rows_a, rows_b)["ci95_boot"] == paired(rows_a, rows_b)["ci95_boot"]


# -- rule 2: the nitrogen cap can never be applied silently ---------------------------------

def test_max_n_has_no_default_and_must_be_passed():
    """``run()`` refuses to start without ``--max-n``.

    The cap binds on ``DEFAULT_PLAN`` itself (569 and 936 kg N/ha clipped to 400), so a capped
    run and an uncapped one are different worlds, not stricter and looser versions of one. A
    default let Exp 3 and Exp 4 inherit 400 while Exp 1 ran uncapped, and composing across that
    line is the same class of error as the cap bug that inverted Exp 1's headline.
    """
    with pytest.raises(SystemExit):
        run("N", Path("/tmp/never_written.json"), ["--budget", "10"])


def test_max_n_parser_accepts_a_number_or_none():
    assert _max_n_arg("400") == 400.0
    assert _max_n_arg("none") is None
    assert _max_n_arg("0") is None
    with pytest.raises(argparse.ArgumentTypeError):
        _max_n_arg("lots")


def test_the_cap_actually_binds_on_the_baseline():
    """The premise of the rule above, measured rather than asserted."""
    from swat_gym.constrainers import total_n
    from swat_gym.env import decode
    uncapped = [total_n(a) for a in decode(DEFAULT_PLAN.ravel(), max_n=None)]
    capped = [total_n(a) for a in decode(DEFAULT_PLAN.ravel(), max_n=400.0)]
    assert max(uncapped) > 400.0 and max(capped) == pytest.approx(400.0)
    assert uncapped != capped, "if the cap were inert the composition rule would not matter"


# -- the CMA-ES search starts from measured practice, always ---------------------------------

def test_optimize_fixed_starts_from_the_arm_default():
    """With Exp 4 cut (2026-09-09) there is no warm start: every search begins at measured
    practice on the arm's own dimensions. This pins that the start point is not silently
    something else — the failure the old warm-start test guarded, in its surviving form."""
    seen = []

    def fake_minimise(fn, x0, **kw):
        seen.append(np.asarray(x0, dtype=float).copy())
        return np.asarray(x0, dtype=float), 0, []

    with mock.patch("swat_gym.experiments._focused.minimise", fake_minimise):
        optimize_fixed("N", [1995], evals=1, seed=0, prices=average(),
                       no3_price=0.0, max_n=None)
        optimize_fixed("I", [1995], evals=1, seed=0, prices=average(),
                       no3_price=0.0, max_n=None)
    assert np.allclose(seen[0], default_free("N"))
    assert np.allclose(seen[1], default_free("I"))
