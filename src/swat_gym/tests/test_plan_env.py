"""Plans and the env: measured-practice nesting, objective parity, and state reading."""
from __future__ import annotations

import numpy as np
import pytest

from swat_gym.env import OBS_DIM, SwatEnv
from swat_gym.fastrunner import FastRunner
from swat_gym.plan import (ANNUAL_YEARS, DIMS, MAX_EVENT_MM, MEASURED_IRRIGATION_MM,
                           MEASURED_ROTATION, N_YEARS, SPINUP, default_plan, default_x,
                           evaluate, plan_from, time_sim)
from swat_gym.rewarders import average, profit

MEASURED_N_KG = 2090.06


@pytest.fixture(scope="module")
def runner():
    with FastRunner() as r:
        yield r


def test_default_plan_is_measured_rotation_and_manure():
    plan = default_plan()
    assert tuple(a.crop for a in plan) == MEASURED_ROTATION
    assert sum(a.manure_mg for a in plan) == pytest.approx(234.4)
    assert all(a.manure_mg == 0 for a in plan if a.crop == "alfa")


@pytest.mark.parametrize("lever", ["I", "N"])
def test_default_x_reproduces_measured_practice(runner, lever):
    """Rule 5 (irrigation within 1 %) and measured N, for both levers' default."""
    d = evaluate(lever, default_x(lever), runner, prices=average())
    assert abs(d["irrigation_mm"] - MEASURED_IRRIGATION_MM) / MEASURED_IRRIGATION_MM < 0.01
    assert d["n_applied_kg"] == pytest.approx(MEASURED_N_KG, rel=1e-3)


def test_generated_default_matches_shipped_schedule_nitrogen(runner):
    runner.run({"time.sim": time_sim(2013, N_YEARS + SPINUP)})
    shipped = profit(runner, average())
    gen = evaluate("I", default_x("I"), runner, prices=average())
    assert gen["n_applied_kg"] == pytest.approx(shipped["n_applied_kg"], rel=1e-3)


def test_no_irrigation_pass_exceeds_cap():
    for x in (default_x("I"), np.ones(DIMS["I"])):
        for a in plan_from("I", x):
            assert all(mm <= MAX_EVENT_MM + 1e-9 for _, mm in a.irr_day_depths)


def test_n_lever_leaves_alfalfa_unfertilised():
    plan = plan_from("N", np.ones(DIMS["N"]))
    for y, a in enumerate(plan):
        if y not in ANNUAL_YEARS:
            assert a.manure_mg == 0 and not a.fert_splits


@pytest.mark.parametrize("lever", ["I", "N"])
def test_episode_profit_equals_open_loop(runner, lever):
    """Rule 2: the policy path and the open-loop path are the same objective."""
    rng = np.random.default_rng(0)
    prices = average()
    with SwatEnv(lever, prices=prices, runner=runner) as env:
        obs, _ = env.reset(start_year=2013)
        assert obs.shape == (OBS_DIM,)
        total, done = 0.0, False
        while not done:
            obs, r, done, _, info = env.step(rng.random(env.action_dim))
            total += r
        x = env.x.copy()
    openloop = evaluate(lever, x, runner, prices=prices, start_year=2013)
    assert info["profit"] == pytest.approx(openloop["profit"], rel=1e-9)
    assert total * 1e3 == pytest.approx(openloop["profit"], rel=1e-6)


def test_observation_tracks_the_decided_month(runner):
    """State comes from the month just decided, and varies within an episode."""
    with SwatEnv("I", prices=average(), runner=runner) as env:
        env.reset(start_year=2013)
        sw = []
        for _ in range(12):
            env.step([0.3])
            sw.append(env.last["sw"])
    assert len(set(np.round(sw, 3))) > 3
