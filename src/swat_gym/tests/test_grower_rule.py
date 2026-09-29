"""The grower rule: logged target, shared renderer, and the rule 5 gate on its own weather."""
from __future__ import annotations

import json

import numpy as np
import pytest

from swat_gym.env import N_YEARS
from swat_gym.experiments import exp1_grower_rule as g
from swat_gym.monthly import N_GROWING


def test_logged_target_is_the_measured_record():
    t = g.logged_monthly_mm()
    assert t.shape == (N_YEARS, N_GROWING)
    # Rule 5's figure. October's ~43 mm is in the total but outside the April-September target.
    assert abs(g.logged_total_mm() - 3938.8) < 0.1
    assert 0 < g.logged_total_mm() - t.sum() < 0.02 * g.logged_total_mm()
    assert g.FIT_YEARS == list(range(2013, 2020))


def test_renderer_preserves_volume():
    """Carry-back moves water between months; it must never create or lose it."""
    t = g.logged_monthly_mm()
    assert abs(g.rendered_monthly_mm(t).sum() - t.sum()) < 1e-6


def test_fit_loss_penalises_only_beyond_the_gate():
    t = g.logged_monthly_mm()
    total = t.sum()
    assert g.fit_loss(t, t, total) == 0.0
    inside = t * (1 + 0.5 * g.GATE_TOL)
    outside = t * (1 + 2.0 * g.GATE_TOL)
    sse_out = float(((outside - t) ** 2).sum())
    assert g.fit_loss(inside, t, total) == pytest.approx(float(((inside - t) ** 2).sum()))
    assert g.fit_loss(outside, t, total) > sse_out


@pytest.mark.slow
def test_fitted_rule_reproduces_logged_total_on_its_own_weather():
    """Rule 5 for the grower row: re-simulate the stored fit and check it, not the artefact's say-so."""
    if not g.OUT.is_file():
        pytest.skip("runs/exp1_grower_rule.json not produced yet")
    from swat_gym.fastrunner import FastRunner
    from swat_gym.rewarders import average
    from swat_gym.experiments.exp1_controller import rollout_controller

    abc = json.loads(g.OUT.read_text())["abc"]
    with FastRunner() as runner:
        sim = rollout_controller(abc, runner, start_year=g.FIT_START, prices=average(),
                                 max_n=None)
    err = abs(sim["irrigation_mm"] - g.logged_total_mm()) / g.logged_total_mm()
    assert err <= g.GATE_TOL, f"{sim['irrigation_mm']:.1f} mm ({err:.2%})"
    assert np.isfinite(sim["profit"])
