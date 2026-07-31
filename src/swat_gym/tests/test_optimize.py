"""Tests for the CMA-ES driver, on cheap analytic objectives rather than the engine.

The property that matters is the one a killed run depends on: a resumed search must be the
search it would have been. Exp 1's fixed row was produced by a warm start that restored only
the incumbent point, so it carried a caveat that it was not equivalent to an uninterrupted
6,250-evaluation search. Restoring the strategy object removes the caveat — but only if it
actually holds, which is what this pins.
"""
from __future__ import annotations

import numpy as np

from swat_gym.experiments._optimize import minimise


def _rosen(x) -> float:
    x = np.asarray(x) * 4.0 - 2.0
    return float(np.sum(100.0 * (x[1:] - x[:-1] ** 2) ** 2 + (1.0 - x[:-1]) ** 2))


def test_resume_is_identical_to_an_uninterrupted_search():
    x0 = np.full(6, 0.5)
    whole, n_whole, _ = minimise(_rosen, x0, evals=400, seed=7)

    saved: dict = {}

    def grab(blob, n, best_x, best_f):
        if "state" not in saved and n >= 200:
            saved.update(state=blob, n=n)

    minimise(_rosen, x0, evals=400, seed=7, on_generation=grab)
    assert saved, "no checkpoint was offered at a generation boundary"

    resumed, n_resumed, _ = minimise(_rosen, x0, evals=400, seed=7, state=saved["state"])

    assert n_resumed == n_whole, "a resume must finish on the same total evaluation budget"
    assert np.allclose(whole, resumed, atol=1e-12), (
        "resume diverged: the covariance matrix or step size was not restored"
    )


def test_checkpoint_reports_monotone_progress():
    seen: list[tuple[int, float]] = []
    minimise(_rosen, np.full(4, 0.5), evals=200, seed=1,
             on_generation=lambda blob, n, bx, bf: seen.append((n, bf)))
    assert len(seen) > 1
    counts, bests = zip(*seen)
    assert list(counts) == sorted(counts), "evaluation count must not go backwards"
    assert list(bests) == sorted(bests, reverse=True), "best-so-far must never worsen"


def test_history_tracks_best_so_far():
    _, _, hist = minimise(_rosen, np.full(4, 0.5), evals=150, seed=2)
    assert hist, "history must record at least one generation"
    assert hist[-1]["evals"] >= hist[0]["evals"]
    fs = [h["best_f"] for h in hist]
    assert fs == sorted(fs, reverse=True)


def test_empty_arm_is_a_no_op():
    """The ``baseline`` arm owns no dimensions; optimising it must not call the engine."""
    calls = []
    x, n, hist = minimise(lambda v: calls.append(v) or 0.0, np.zeros(0), evals=100)
    assert n == 0 and x.size == 0 and not calls and hist == []
