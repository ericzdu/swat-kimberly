"""Calibration engine layer for the Kimberly, ID SWAT+ field model.

Formerly the hot path under a management-optimisation gym; the RL layer was removed when
this became AI-SWAT+'s calibration project (2026-09-04). What remains is the fast
edit-run-read loop every calibration script is priced off:
:class:`~swat_gym.fastrunner.FastRunner`.
"""
from .engine import EngineError, find_engine, run_engine
from .fastrunner import EDITABLE, TXTINOUT, FastRunner
from .manifest import input_files

__all__ = [
    "EDITABLE",
    "EngineError",
    "FastRunner",
    "TXTINOUT",
    "find_engine",
    "input_files",
]
