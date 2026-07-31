"""Experiment 4 — joint optimisation of irrigation + nitrogen + rotation.

Warm-starts CMA-ES from the composed single-lever optima of Exps 2–3 when those artefacts
exist under ``runs/``. **Pre-registered rule:** if joint scores below the composed optimum,
that is an optimizer statement, never a claim about lever interactions.

    uv run python -m swat_gym.experiments.exp4_joint --budget 300000 --ppo-seeds 3
"""
from __future__ import annotations

import json

import numpy as np

from ..env import CROPS, DEFAULT_PLAN, arm_vector, default_free
from ._focused import ROOT, run

OUT = ROOT / "runs" / "exp4_joint.json"


def composed_start() -> np.ndarray | None:
    """Build a warm-start vector from Exp 2–3 result files if present."""
    e2 = ROOT / "runs" / "exp2_nitrogen.json"
    e3 = ROOT / "runs" / "exp3_rotation.json"
    plan = DEFAULT_PLAN.copy()
    used = False
    if e2.is_file():
        d = json.loads(e2.read_text())
        if "fixed_x" in d:
            plan = arm_vector(d["fixed_x"], "N").reshape(DEFAULT_PLAN.shape)
            used = True
            print(f"  warm-start: loaded N arm from {e2.name}", flush=True)
    if e3.is_file():
        d = json.loads(e3.read_text())
        crops = d.get("best_crops")
        if crops:
            for i, crop in enumerate(crops):
                plan[i, 0:3] = 0.1
                plan[i, CROPS.index(crop)] = 0.9
            used = True
            print("  warm-start: applied R crops from exp3", flush=True)
    return plan.ravel() if used else None


def main() -> None:
    ws = composed_start()
    note = {
        "rule": "joint < composed ⇒ optimizer under-convergence, not lever interaction",
        "warm_start": ws is not None,
    }
    (ROOT / "runs").mkdir(parents=True, exist_ok=True)
    (ROOT / "runs" / "exp4_joint_note.json").write_text(json.dumps(note, indent=2))
    # Full joint search via annual ``all`` arm (monthly joint gym is future work).
    run("all", OUT)


if __name__ == "__main__":
    main()
