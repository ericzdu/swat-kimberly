"""CMA-ES driver: deterministic, monotone history, parallel == serial."""
from __future__ import annotations

import numpy as np

from swat_gym.experiments.common import minimise


def rosen(x) -> float:
    x = np.asarray(x) * 4.0 - 2.0
    return float(np.sum(100.0 * (x[1:] - x[:-1] ** 2) ** 2 + (1.0 - x[:-1]) ** 2))


def test_deterministic_and_parallel_matches_serial():
    a = minimise(rosen, np.full(5, 0.5), evals=120, seed=3)
    b = minimise(rosen, np.full(5, 0.5), evals=120, seed=3, workers=2)
    assert np.allclose(a[0], b[0]) and a[1] == b[1]


def test_history_is_monotone():
    _, _, hist = minimise(rosen, np.full(4, 0.5), evals=150, seed=2)
    fs = [h["best_f"] for h in hist]
    assert fs == sorted(fs, reverse=True)
