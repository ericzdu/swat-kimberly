"""Grower rule: logged target, renderer volume, rule 5 gate in the loss."""
from __future__ import annotations

import pytest

from swat_gym.experiments import exp1_grower_rule as g
from swat_gym.plan import MONTH_DEPTH_MAX, N_GROWING, N_YEARS


def test_logged_target_is_the_measured_record():
    t = g.logged_monthly_mm()
    assert t.shape == (N_YEARS, N_GROWING)
    assert abs(g.logged_total_mm() - 3938.8) < 0.1
    assert 0 < g.logged_total_mm() - t.sum() < 0.02 * g.logged_total_mm()  # October


def test_renderer_preserves_volume():
    t = g.logged_monthly_mm()
    assert abs(g.rendered_monthly_mm(t / MONTH_DEPTH_MAX).sum() - t.sum()) < 1e-6


def test_fit_loss_penalises_only_beyond_the_gate():
    t = g.logged_monthly_mm()
    inside, outside = t * (1 + 0.5 * g.GATE_TOL), t * (1 + 2 * g.GATE_TOL)
    assert g.fit_loss(t, t, t.sum()) == 0.0
    assert g.fit_loss(inside, t, t.sum()) == pytest.approx(float(((inside - t) ** 2).sum()))
    assert g.fit_loss(outside, t, t.sum()) > float(((outside - t) ** 2).sum())
