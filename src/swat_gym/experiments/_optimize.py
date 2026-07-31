"""CMA-ES over a bounded box, sized for expensive objectives.

Not SciPy's ``differential_evolution``. Its ``popsize`` is a *multiplier on the parameter
count*, so the 63-parameter ``all`` arm gets a 945-member population and burns ~1,900 engine
runs before finishing a single generation. CMA-ES's default population is
``4 + 3 ln(n)`` — about 16 at n=63 — which is the right shape when one evaluation costs an
engine run rather than a flop.
"""
from __future__ import annotations

import pickle
from collections.abc import Callable, Sequence

import numpy as np


def minimise(fn: Callable[[np.ndarray], float], x0: Sequence[float], *,
             evals: int, seed: int = 0, sigma0: float = 0.25,
             state: bytes | None = None,
             on_generation: Callable[[bytes, int, np.ndarray, float], None] | None = None,
             ) -> tuple[np.ndarray, int, list[dict]]:
    """Minimise ``fn`` over ``[0, 1]^n``.

    Returns ``(best_x, n_evaluations, history)`` where ``history`` is a list of
    ``{evals, best_f}`` snapshots after each generation — required to show the open-loop bar
    actually converged rather than under-searched (the ``all`` < ``MR`` artefact).
    """
    import cma

    x0 = np.clip(np.asarray(x0, dtype=float), 0.0, 1.0)
    if x0.size == 0:
        return x0, 0, []

    if state is not None:
        es = pickle.loads(state)
        es.opts.set({"maxfevals": evals})
    else:
        es = cma.CMAEvolutionStrategy(
            list(x0), sigma0,
            {"bounds": [0.0, 1.0], "maxfevals": evals, "seed": seed + 1, "verbose": -9},
        )
    best_x = np.asarray(es.best.x if es.best.x is not None else x0, dtype=float)
    best_f = float(es.best.f) if es.best.f is not None else float("inf")
    history: list[dict] = []

    while not es.stop():
        xs = es.ask()
        fs = []
        for x in xs:
            f = float(fn(np.asarray(x)))
            fs.append(f)
            if f < best_f:
                best_f, best_x = f, np.asarray(x).copy()
        es.tell(xs, fs)
        n = int(es.countevals)
        history.append({"evals": n, "best_f": float(best_f)})
        if on_generation is not None:
            on_generation(pickle.dumps(es), n, best_x, best_f)
    return best_x, int(es.countevals), history
