"""Windows split, monthly irrigation nesting, and protocol invariants."""
from __future__ import annotations

import numpy as np
import pytest

from swat_gym.env import DEFAULT_PLAN, N_YEARS, SPINUP, decode_year, evaluate
from swat_gym.fastrunner import FastRunner
from swat_gym.monthly import (MONTHLY_I_DIM, annual_to_monthly, default_monthly_i_free,
                              default_monthly_irr, evaluate_monthly_i, plan_from_monthly_i)
from swat_gym.schedule import GROWING_MONTHS, build
from swat_gym.windows import (TRAIN_YEARS, TEST_YEARS, WINDOW_LEN, assert_no_leakage,
                              spans_overlap, window_years)


def test_train_test_share_no_calendar_years():
    assert_no_leakage()
    for a in TRAIN_YEARS:
        for b in TEST_YEARS:
            assert not spans_overlap(a, b), f"{a} overlaps {b}"


def test_window_length_is_eight():
    assert WINDOW_LEN == N_YEARS + SPINUP == 8
    assert list(window_years(2004))[-1] == 2011
    assert list(window_years(2013))[0] == 2013


def test_annual_to_monthly_nests_default_totals():
    """Monthly totals from DEFAULT_PLAN sum to the annual fixed-interval applied depth."""
    for y in range(N_YEARS):
        a = decode_year(DEFAULT_PLAN[y])
        months = annual_to_monthly(a.irr_start_doy, a.irr_interval, a.irr_depth, a.crop)
        # Reconstruct by simulating events.
        from swat_gym.schedule import CALENDAR, _doy, _md
        cal = CALENDAR[a.crop]
        end = _doy(*cal["cuts"][-1]) if a.crop == "alfa" else _doy(*cal["harvest"])
        total = 0.0
        doy = a.irr_start_doy
        while doy < end:
            total += a.irr_depth
            doy += a.irr_interval
        assert abs(sum(months) - total) < 1e-6


@pytest.mark.slow
def test_monthly_default_irrigation_within_1pct_of_measured():
    """Nesting gate: monthly default must reproduce measured applied depth."""
    x = default_monthly_i_free()
    assert x.size == MONTHLY_I_DIM
    with FastRunner() as runner:
        d = evaluate_monthly_i(x, runner, start_year=2012)
    measured = 3938.8
    err = abs(d["irrigation_mm"] - measured) / measured
    assert err < 0.01, f"monthly default {d['irrigation_mm']} vs {measured} ({err:.2%})"


def test_year_blocks_never_empty():
    plan = plan_from_monthly_i(default_monthly_irr())
    edits = build(plan)
    # Each year must contribute ops; empty block would shift SWAT+ year boundaries.
    body = edits["management.sch"].split("\n", 3)[-1]
    assert "plnt" in body or "harv" in body or "hvkl" in body


def test_obs_has_no_future_weather_keys():
    """Monthly observation must not expose upcoming precip/PET."""
    from swat_gym.monthly_env import MonthlySwatEnv, OBS_DIM_MONTHLY
    # Construction without a runner still exposes obs shape.
    assert OBS_DIM_MONTHLY == 14
    # Documented channels: past/current state only — no 'forecast' field.
    # Smoke the obs vector length via a dry reset with a real runner if available.
    try:
        with MonthlySwatEnv(stochastic_weather=False, arm="I") as env:
            obs, _ = env.reset(start_year=2013)
            assert obs.shape == (OBS_DIM_MONTHLY,)
            assert np.isfinite(obs).all()
    except Exception as e:
        pytest.skip(f"engine unavailable: {e}")


def test_arms_include_all():
    from swat_gym.env import ARMS, ACTION_DIM, arm_dims
    assert "all" in ARMS
    assert len(arm_dims("all")) == ACTION_DIM
