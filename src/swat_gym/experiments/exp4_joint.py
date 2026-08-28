"""Experiment 4 — joint optimisation of irrigation + nitrogen + rotation.

Warm-starts CMA-ES from the composed single-lever optima of Exps 2–3 when those artefacts
exist under ``runs/``. **Pre-registered rule:** if joint scores below the composed optimum,
that is an optimizer statement, never a claim about lever interactions.

Two things that rule depends on, and that this module now enforces rather than assumes:

* **The warm start must actually reach the optimizer.** It used to be computed, written into
  ``exp4_joint_note.json`` as ``"warm_start": true``, and then dropped on the floor — ``run()``
  took no start point. The search began cold while the artefact said otherwise, which is the
  one way rule 8 can be read wrong: a cold search that lands below the composed point is
  evidence about the budget, not about interactions, and there was no way to tell the two
  apart from the artefact.
* **The composed pieces must come from the same world.** ``--max-n`` and ``--no3-price`` change
  what is simulated and what is priced. Warm-starting from an Exp 2 run at a different cap, or
  at a different nitrate price, silently composes two different experiments; the loaded
  artefacts are checked against this run's settings and the run aborts if they disagree.

    uv run python -m swat_gym.experiments.exp4_joint \\
        --budget 300000 --ppo-seeds 3 --max-n none
"""
from __future__ import annotations

import argparse
import json
import sys

import numpy as np

from ..env import CROPS, DEFAULT_PLAN, arm_vector, default_free
from ._focused import ROOT, run

OUT = ROOT / "runs" / "exp4_joint.json"

#: Rule 3: never a single-seed headline for Exp 1 / Exp 4.
MIN_PPO_SEEDS = 3


def _settings(argv: list[str]) -> tuple[float | None, float, int]:
    """This run's ``max_n`` and ``no3_price``, read the same way :func:`run` reads them."""
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("--max-n", default=None)
    ap.add_argument("--no3-price", type=float, default=0.0)
    ap.add_argument("--ppo-seeds", type=int, default=1)
    known, _ = ap.parse_known_args(argv)
    cap = known.max_n
    if cap is not None:
        cap = None if str(cap).strip().lower() in {"none", "off", "uncapped"} else float(cap)
        if cap is not None and cap <= 0:
            cap = None
    return cap, known.no3_price, known.ppo_seeds


def _check_world(path, d: dict, max_n, no3_price) -> None:
    """Abort rather than compose an artefact optimised under different physics or prices."""
    got_n, got_p = d.get("max_n", "missing"), d.get("no3_price", "missing")
    if got_n != max_n or got_p != no3_price:
        raise SystemExit(
            f"{path.name} was produced at max_n={got_n!r}, no3_price={got_p!r}; this run is "
            f"max_n={max_n!r}, no3_price={no3_price!r}. Composing them would warm-start the "
            f"joint search from an optimum for a different problem. Re-run that experiment at "
            f"these settings, or run Exp 4 at those."
        )


def composed_start(max_n, no3_price) -> np.ndarray | None:
    """Build a warm-start vector from Exp 2–3 result files if present.

    Returns the ``all`` arm's free parameters, which for that arm is the whole flattened plan.
    """
    e2 = ROOT / "runs" / "exp2_nitrogen.json"
    e3 = ROOT / "runs" / "exp3_rotation.json"
    plan = DEFAULT_PLAN.copy()
    used = []
    if e2.is_file():
        d = json.loads(e2.read_text())
        if "fixed_x" in d:
            _check_world(e2, d, max_n, no3_price)
            plan = arm_vector(d["fixed_x"], "N").reshape(DEFAULT_PLAN.shape)
            used.append(f"N arm from {e2.name}")
    if e3.is_file():
        d = json.loads(e3.read_text())
        crops = d.get("best_crops")
        if crops:
            _check_world(e3, d, max_n, no3_price)
            for i, crop in enumerate(crops):
                plan[i, 0:3] = 0.1
                plan[i, CROPS.index(crop)] = 0.9
            used.append(f"R crops from {e3.name}")
    if not used:
        return None
    for line in used:
        print(f"  warm-start: loaded {line}", flush=True)
    ws = plan.ravel()
    expected = default_free("all").shape
    if ws.shape != expected:
        raise SystemExit(f"composed warm start has shape {ws.shape}, arm 'all' expects "
                         f"{expected}")
    return ws


def main(argv=None) -> None:
    argv = list(sys.argv[1:] if argv is None else argv)
    max_n, no3_price, ppo_seeds = _settings(argv)
    if ppo_seeds < MIN_PPO_SEEDS:
        raise SystemExit(
            f"--ppo-seeds {ppo_seeds}: rule 3 forbids a single-seed Exp 4 headline; "
            f"pass --ppo-seeds {MIN_PPO_SEEDS} or more."
        )
    ws = composed_start(max_n, no3_price)
    note = {
        "rule": "joint < composed ⇒ optimizer under-convergence, not lever interaction",
        "warm_start": ws is not None,
        "warm_start_reaches_optimizer": True,
        "max_n": max_n,
        "no3_price": no3_price,
    }
    (ROOT / "runs").mkdir(parents=True, exist_ok=True)
    (ROOT / "runs" / "exp4_joint_note.json").write_text(json.dumps(note, indent=2))
    # Full joint search via annual ``all`` arm (monthly joint gym is future work).
    run("all", OUT, argv, x0=ws)


if __name__ == "__main__":
    main()
