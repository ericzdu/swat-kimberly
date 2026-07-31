"""Tests for the action space, the constraint repair, and the environment.

The properties that matter here are the ones a silent break would corrupt an experiment with:
that a repaired plan is actually feasible, that an arm only moves its own lever, and that the
weather window is really changing the dynamics rather than being ignored.
"""
from __future__ import annotations

import numpy as np
import pytest

from swat_gym import FastRunner
from swat_gym.constrainers import (MAX_CONSECUTIVE_CORN, MAX_N_LOADING, MIN_ALFALFA_STAND,
                                   MANURE_N_FRAC, feasible, repair, violations)
from swat_gym.env import (ACTION_DIM, ARMS, DEFAULT_PLAN, MEASURED_ROTATION, N_YEARS, OBS_DIM,
                          SwatEnv, arm_vector, decode, default_free, evaluate, time_sim)
from swat_gym.schedule import CROPS, YearAction, build


# --- constraints ------------------------------------------------------------------------

def test_repair_is_idempotent_and_feasible():
    rng = np.random.default_rng(0)
    for _ in range(50):
        plan = decode(rng.random(N_YEARS * ACTION_DIM), constrain=False)
        fixed = repair(plan)
        assert feasible(fixed), violations(fixed)
        assert [ (a.crop, a.manure_mg) for a in repair(fixed) ] == \
               [ (a.crop, a.manure_mg) for a in fixed ], "repair must be a projection"


def test_corn_on_corn_is_capped():
    plan = [YearAction(crop="corn") for _ in range(N_YEARS)]
    crops = [a.crop for a in repair(plan)]
    run = best = 0
    for c in crops:
        run = run + 1 if c == "corn" else 0
        best = max(best, run)
    assert best <= MAX_CONSECUTIVE_CORN


def test_short_alfalfa_stand_is_extended():
    plan = [YearAction(crop=c) for c in ("corn", "alfa", "corn", "corn", "barl", "barl", "barl")]
    crops = [a.crop for a in repair(plan)]
    assert crops[1:1 + MIN_ALFALFA_STAND] == ["alfa"] * MIN_ALFALFA_STAND


def test_nitrogen_loading_is_capped():
    plan = [YearAction(crop="corn", manure_mg=500.0, manure_src="gn2014")
            for _ in range(N_YEARS)]
    for a in repair(plan):
        assert a.manure_mg * MANURE_N_FRAC[a.manure_src] * 1000.0 <= MAX_N_LOADING + 1e-6


def test_alfalfa_is_not_manured():
    plan = [YearAction(crop="alfa", manure_mg=50.0) for _ in range(N_YEARS)]
    assert all(a.manure_mg == 0.0 for a in repair(plan))


# --- action space -----------------------------------------------------------------------

def test_default_plan_is_the_measured_rotation():
    assert [a.crop for a in decode(DEFAULT_PLAN.ravel(), constrain=False)] == list(MEASURED_ROTATION)


def test_default_irrigation_is_near_measured_practice():
    """The baseline an arm improves on must be realistic, or gains are measured off a strawman."""
    plan = decode(DEFAULT_PLAN.ravel())
    a = plan[0]
    events = len(range(a.irr_start_doy, 263, a.irr_interval))
    assert 400 < events * a.irr_depth < 700, "should bracket the measured ~563 mm/yr"


@pytest.mark.parametrize("arm", sorted(ARMS))
def test_arm_moves_only_its_own_dimensions(arm):
    dims = ARMS[arm]
    free = np.full(N_YEARS * len(dims), 0.123) if dims else np.zeros(0)
    got = arm_vector(free, arm).reshape(N_YEARS, ACTION_DIM)
    for d in range(ACTION_DIM):
        if d in dims:
            assert np.allclose(got[:, d], 0.123)
        else:
            assert np.allclose(got[:, d], DEFAULT_PLAN[:, d])


def test_default_free_round_trips():
    for arm in ARMS:
        assert np.allclose(arm_vector(default_free(arm), arm), DEFAULT_PLAN.ravel())


# --- schedule / engine ------------------------------------------------------------------

def test_generated_schedule_runs_and_prices():
    with FastRunner() as r:
        d = evaluate(DEFAULT_PLAN.ravel(), r)
        assert d["revenue"] > 0
        assert d["irrigation_mm"] > 0
        assert not d["infeasible"]


def test_alfalfa_stand_is_planted_once():
    plan = [YearAction(crop=c) for c in ("corn", "alfa", "alfa", "alfa", "corn", "barl", "barl")]
    sch = build(plan)["management.sch"]
    plnt_alfa = [l for l in sch.splitlines() if " plnt " in f" {l.split()[0]} " and "alfa" in l]
    assert len(plnt_alfa) == 1, "a perennial stand is established once, not replanted each year"
    assert sum("hvkl" in l and "alfa" in l for l in sch.splitlines()) == 1


def test_weather_window_changes_the_result():
    """If time.sim were ignored, stochastic weather would be a no-op and Exp 2 meaningless."""
    with FastRunner() as r:
        a = evaluate(DEFAULT_PLAN.ravel(), r, start_year=1996)["profit"]
        b = evaluate(DEFAULT_PLAN.ravel(), r, start_year=2012)["profit"]
    assert a != pytest.approx(b, rel=1e-6)


def test_time_sim_window_spans_spinup_plus_decision_years():
    txt = time_sim(1996).split("\n")[2].split()
    assert int(txt[1]) == 1996 and int(txt[3]) == 1996 + N_YEARS


# --- the default must really be the default ----------------------------------------------
# Two compounding defects once made every generated row 22 % drier than the human bar it was
# scored against — an `eff_frac` of 0.85 the measured record does not have, and a depth that
# integrated to 3,060 mm against a measured 3,938.8. Neither was visible in any assertion, and
# the resulting confound was read as an experimental finding. These pin both.

def test_generated_irrigation_efficiency_matches_the_measured_record():
    """A generated event must deliver what it asks for, exactly as the measured events do."""
    from swat_gym.fastrunner import TXTINOUT

    # columns: name  amt_mm  eff_frac  sumq_frac  ...
    measured = {l.split()[2] for l in (TXTINOUT / "irr.ops").read_text().splitlines()
                if l.startswith("gn0")}
    assert measured == {"1.00000"}, "the measured record's own efficiency moved"

    generated = [l for l in build([YearAction()])["irr.ops"].splitlines() if l.startswith("gy")]
    assert generated, "no generated irr.ops entries to check"
    assert {l.split()[2] for l in generated} == measured


def test_default_plan_irrigates_like_measured_practice():
    """DEFAULT_PLAN is the counterfactual every arm is scored against, so its water has to
    match the field's. Within 1 %: the fixed-interval grid approximates an irregular record."""
    with FastRunner() as r:
        r.run({"time.sim": time_sim(2012)})
        measured = float(r.read("hru_wb_yr.txt")["irr"].sum())
        default = evaluate(DEFAULT_PLAN.ravel(), r, start_year=2012)["irrigation_mm"]
    assert default == pytest.approx(measured, rel=0.01), (default, measured)


# --- environment ------------------------------------------------------------------------

def test_episode_terminates_and_rewards_sum_to_profit():
    """Per-step rewards must telescope to the rotation profit, up to the learning-signal scale.

    ``info["cum_profit"]`` stays in dollars precisely so evaluation is never affected by
    :data:`SwatEnv.REWARD_SCALE`; this pins the two together.
    """
    rng = np.random.default_rng(1)
    with SwatEnv(stochastic_weather=False) as env:
        env.reset(start_year=2012)
        total = 0.0
        for _ in range(N_YEARS):
            _, rew, term, _, info = env.step(rng.random(ACTION_DIM))
            total += rew
        assert term
        assert total / SwatEnv.REWARD_SCALE == pytest.approx(info["cum_profit"])


def test_observation_exposes_soil_carryover():
    """Next year's weather is unknowable at decision time, so carryover is the *only* channel
    a policy can be adaptive through. An observation without it cannot express adaptivity even
    in principle — which is what Exp 1's PPO null was actually measuring."""
    with SwatEnv(stochastic_weather=False, arm="N") as env:
        obs, _ = env.reset(start_year=2012)
        assert obs.shape == (OBS_DIM,)
        assert not obs.any(), "reset must not leak state from a previous episode"
        obs, *_ = env.step(np.full(len(env.free_dims), 0.5))
        assert obs.shape == (OBS_DIM,)
        for k in ("strsn", "strsw", "sw", "n_surplus"):
            assert k in env.last, f"{k} missing from carryover"
        assert env.last["sw"] > 0, "soil water must be a real reading, not a placeholder"
        assert np.isfinite(obs).all()


def test_observation_reports_previous_crop():
    with SwatEnv(stochastic_weather=False) as env:
        env.reset(start_year=2012)
        a = np.zeros(ACTION_DIM)
        a[CROPS.index("alfa")] = 1.0
        obs, *_ = env.step(a)
        assert obs[1 + CROPS.index("alfa")] == 1.0
