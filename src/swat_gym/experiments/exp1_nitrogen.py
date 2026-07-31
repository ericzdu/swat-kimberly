"""Experiment 1 (legacy name) — redirected to Exp 2 nitrogen.

The pivot renumbered experiments so Exp 1 = irrigation. Prefer::

    uv run python -m swat_gym.experiments.exp2_nitrogen
"""
from swat_gym.experiments.exp2_nitrogen import main

if __name__ == "__main__":
    main()
