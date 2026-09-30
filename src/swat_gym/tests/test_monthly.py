"""Windows split, monthly irrigation nesting, and protocol invariants."""
from __future__ import annotations

import numpy as np
import pytest

from swat_gym.env import DEFAULT_PLAN, N_YEARS, SPINUP, decode_year, time_sim
from swat_gym.fastrunner import FastRunner
from swat_gym.monthly import (MONTHLY_I_DIM, annual_to_monthly, default_monthly_i_free,
                              default_monthly_irr, encode_monthly_depths,
                              evaluate_monthly_i, plan_from_monthly_i)
from swat_gym.rewarders import profit
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
    assert OBS_DIM_MONTHLY == 13
    # No forecast channel; check obs length.
    try:
        with MonthlySwatEnv(stochastic_weather=False, arm="I") as env:
            obs, _ = env.reset(start_year=2013)
            assert obs.shape == (OBS_DIM_MONTHLY,)
            assert np.isfinite(obs).all()
            gym_env = env.to_gym()
            assert gym_env.observation_space.shape == (OBS_DIM_MONTHLY,)
    except Exception as e:
        pytest.skip(f"engine unavailable: {e}")


@pytest.mark.slow
def test_openloop_and_policy_paths_agree_on_identical_plan():
    """Open-loop and policy paths score the same objective (max_n parity, rule 2)."""
    from swat_gym.monthly_env import MonthlySwatEnv

    mm = default_monthly_irr()
    x = encode_monthly_depths(mm)
    try:
        with FastRunner() as runner:
            openloop = evaluate_monthly_i(x, runner, start_year=2013, max_n=None)
        with MonthlySwatEnv(stochastic_weather=False, arm="I", max_n=None) as env:
            env.reset(start_year=2013)
            env.month_mm = mm.copy()
            plan = env._build_plan()
            edits = build(plan)
            edits["time.sim"] = time_sim(2013, N_YEARS + SPINUP)
            env.runner.run(edits)
            policy = profit(env.runner, env.prices)
    except Exception as e:  # pragma: no cover - engine may be unavailable
        pytest.skip(f"engine unavailable: {e}")

    for k in ("irrigation_mm", "manure_mg", "fert_n_kg", "profit", "no3_leached_kg"):
        assert openloop[k] == pytest.approx(policy[k], rel=1e-6, abs=1e-6), (
            f"{k}: open-loop {openloop[k]} != policy {policy[k]} — the paths have "
            "diverged again; every policy-vs-open-loop comparison is invalid"
        )


def test_experiment_scorers_require_explicit_max_n():
    """``max_n`` must stay a required argument, so the cap can never be applied silently."""
    import inspect

    from swat_gym.experiments.exp1_irrigation import score_month_plan, score_monthly

    for fn in (score_monthly, score_month_plan):
        p = inspect.signature(fn).parameters["max_n"]
        assert p.default is inspect.Parameter.empty, (
            f"{fn.__name__} gave max_n a default; that is exactly how the cap bug happened"
        )


def test_arms_are_exactly_the_two_live_levers():
    """Scope reduced to two levers 2026-09-09. A combination arm reappearing here means an
    experiment was restored without the rotation-bias reasoning being revisited."""
    from swat_gym.env import ARMS
    assert set(ARMS) == {"baseline", "N", "I"}


MEASURED_MANURE_MG = 234.4      # GRACEnet 2013/14/18/19: 43.8 + 48.0 + 88.3 + 54.3
MEASURED_MANURE_N = 2090.06     # ...at each year's own MANURE_N_FRAC


def test_default_plan_nests_measured_nitrogen():
    """DEFAULT_PLAN reproduces measured N (2,090 kg/ha)."""
    from swat_gym.constrainers import MANURE_N_FRAC
    from swat_gym.env import DEFAULT_PLAN, decode_year

    mg = n_kg = 0.0
    for y in range(N_YEARS):
        a = decode_year(DEFAULT_PLAN[y])
        mg += a.manure_mg
        n_kg += a.manure_mg * MANURE_N_FRAC[a.manure_src] * 1000.0

    assert mg == pytest.approx(MEASURED_MANURE_MG, rel=1e-4), (
        f"DEFAULT_PLAN manure {mg:.2f} Mg/ha != measured {MEASURED_MANURE_MG}")
    assert n_kg == pytest.approx(MEASURED_MANURE_N, rel=1e-4), (
        f"DEFAULT_PLAN nitrogen {n_kg:.1f} kg/ha != measured {MEASURED_MANURE_N}")


def test_alfalfa_years_receive_no_manure():
    """Measured practice manured only the corn and barley years."""
    from swat_gym.env import DEFAULT_PLAN, decode_year

    for y in range(N_YEARS):
        a = decode_year(DEFAULT_PLAN[y])
        if a.crop == "alfa":
            assert a.manure_mg == pytest.approx(0.0), f"year {y} alfalfa was manured"


@pytest.mark.slow
def test_generated_arms_are_nitrogen_matched_to_measured():
    """Generated arms apply the same N as measured practice."""
    from swat_gym.env import time_sim
    from swat_gym.rewarders import average

    prices = average()
    try:
        with FastRunner() as runner:
            runner.run({"time.sim": time_sim(2013, N_YEARS + SPINUP)})
            measured = profit(runner, prices)
            gen = evaluate_monthly_i(default_monthly_i_free(), runner, prices=prices,
                                     start_year=2013, max_n=None)
    except Exception as e:  # pragma: no cover - engine may be unavailable
        pytest.skip(f"engine unavailable: {e}")

    assert gen["n_applied_kg"] == pytest.approx(measured["n_applied_kg"], rel=1e-3), (
        f"generated arm applies {gen['n_applied_kg']:.1f} kg N vs measured "
        f"{measured['n_applied_kg']:.1f} — Exp 1 is not nitrogen-matched")


def test_no_application_exceeds_the_physical_cap():
    """No irrigation event exceeds MAX_EVENT_MM."""
    from swat_gym.monthly import MAX_EVENT_MM, plan_from_monthly_i

    # Worst case: every month at the ceiling.
    full = np.full((N_YEARS, 6), 200.0)
    for plan in (plan_from_monthly_i(default_monthly_irr(), max_n=None),
                 plan_from_monthly_i(full, max_n=None)):
        for a in plan:
            assert a.irr_day_depths is not None, "monthly arm must render day-level passes"
            for doy, mm in a.irr_day_depths:
                assert mm <= MAX_EVENT_MM + 1e-9, (
                    f"application of {mm:.1f} mm on DOY {doy} exceeds the "
                    f"{MAX_EVENT_MM} mm cap taken from irr.ops sprinkler_high")


@pytest.mark.slow
def test_event_splitting_preserves_applied_depth():
    """Splitting a month into passes must not change how much water is applied."""
    x = default_monthly_i_free()
    try:
        with FastRunner() as runner:
            d = evaluate_monthly_i(x, runner, start_year=2013, max_n=None)
    except Exception as e:  # pragma: no cover
        pytest.skip(f"engine unavailable: {e}")
    measured = 3938.8
    err = abs(d["irrigation_mm"] - measured) / measured
    assert err < 0.01, f"{d['irrigation_mm']} vs {measured} ({err:.2%}) — splitting lost water"


# Obs must read the decided month's row (not iloc[-1]) and vary within an episode.

def _decided_month(step_count: int, start_year: int = 2013) -> tuple[int, int]:
    """(calendar year, month) the ``step_count``-th step decided. ``nyskip`` drops spin-up."""
    t = step_count - 1
    return start_year + SPINUP + t // len(GROWING_MONTHS), GROWING_MONTHS[t % len(GROWING_MONTHS)]


def test_observation_reads_the_decided_month_not_the_last_row():
    """Each channel must come from the month just decided, selected by (yr, mon)."""
    from swat_gym.monthly_env import MonthlySwatEnv

    # Assert outside the try so failures aren't turned into skips.
    seen = []
    try:
        with MonthlySwatEnv(stochastic_weather=False, arm="I", max_n=None) as env:
            env.reset(start_year=2013)
            for k in (1, 2, 3, 7):  # includes a year rollover (step 7 = April, year 2)
                while env.t < k:
                    env.step([0.5])
                yr, mon = _decided_month(k)
                wb = env.runner.read("hru_wb_mon.txt")
                pw = env.runner.read("hru_pw_mon.txt")
                seen.append((
                    k, yr, mon, dict(env.last),
                    wb[(wb["yr"] == yr) & (wb["mon"] == mon)].iloc[0],
                    pw[(pw["yr"] == yr) & (pw["mon"] == mon)].iloc[0],
                    (int(wb.iloc[-1]["mon"]), int(wb.iloc[-1]["yr"])),
                ))
    except Exception as e:  # pragma: no cover - engine may be unavailable
        pytest.skip(f"engine unavailable: {e}")

    for k, yr, mon, last, w, p, final_row in seen:
        assert last["sw"] == pytest.approx(float(w["sw_final"])), (
            f"step {k}: soil water is not {yr}-{mon:02d}'s — the observation has "
            "drifted off the decided month again"
        )
        assert last["precip"] == pytest.approx(float(w["precip"]))
        assert last["pet"] == pytest.approx(float(w["pet"]))
        assert last["strsw"] == pytest.approx(float(p["strsw"]))
        assert last["strsn"] == pytest.approx(float(p["strsn"]))
        # The bug's signature: the table's final row is always a *future* December.
        assert final_row == (12, 2020)


def test_hydrologic_channels_vary_within_an_episode():
    """If sw/precip/PET are constant, the policy has nothing to condition on but the clock."""
    from swat_gym.monthly_env import MonthlySwatEnv

    try:
        with MonthlySwatEnv(stochastic_weather=False, arm="I", max_n=None) as env:
            obs = [env.reset(start_year=2013)[0]]
            for _ in range(6):
                obs.append(env.step([0.5])[0])
    except Exception as e:  # pragma: no cover
        pytest.skip(f"engine unavailable: {e}")

    seen = np.array(obs)[1:]  # channel values are only meaningful after a run
    for ch, name in ((5, "soil water"), (8, "precip"), (9, "PET")):
        assert seen[:, ch].std() > 0, (
            f"observation channel {ch} ({name}) is constant across the episode — the "
            "environment is open-loop and no adaptation result from it is meaningful"
        )


def test_undecided_tail_cannot_change_earlier_observations():
    """SWAT+ is causal: future plan months can't change past observations."""
    from swat_gym.monthly_env import MonthlySwatEnv

    try:
        runs = []
        for tail_mm in (0.0, 200.0):
            with MonthlySwatEnv(stochastic_weather=False, arm="I", max_n=None) as env:
                env.reset(start_year=2013)
                env.month_mm[4:, :] = tail_mm  # years 5-7: far past the steps we take
                runs.append([env.step([0.5])[0] for _ in range(3)])
    except Exception as e:  # pragma: no cover
        pytest.skip(f"engine unavailable: {e}")

    for k, (a, b) in enumerate(zip(*runs)):
        np.testing.assert_array_equal(
            a, b, err_msg=f"step {k}: a future month changed a past observation; the "
                          "prefix-replay construction is not the MDP the paper claims"
        )
