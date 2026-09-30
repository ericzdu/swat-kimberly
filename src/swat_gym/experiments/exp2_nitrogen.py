"""Exp 2: nitrogen (manure + mineral, one cap). Irrigation/rotation at measured practice.

    uv run python -m swat_gym.experiments.exp2_nitrogen --budget 300000 --max-n none --ppo-seeds 3
"""
from __future__ import annotations

from ._focused import ROOT, run

OUT = ROOT / "runs" / "exp2_nitrogen.json"


def main() -> None:
    run("N", OUT)


if __name__ == "__main__":
    main()
