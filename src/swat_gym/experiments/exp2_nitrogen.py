"""Experiment 2 — nitrogen (manure + mineral under one loading cap).

Irrigation and rotation pinned at measured practice. Uses the annual focused protocol in
:mod:`_focused` (monthly N gym is available via :class:`~swat_gym.monthly_env.MonthlySwatEnv`
arm ``N`` when adaptivity on N is re-tested).

    uv run python -m swat_gym.experiments.exp2_nitrogen --budget 300000
"""
from __future__ import annotations

from ._focused import ROOT, run

OUT = ROOT / "runs" / "exp2_nitrogen.json"


def main() -> None:
    run("N", OUT)


if __name__ == "__main__":
    main()
