"""``swat-gym`` — a management-optimization layer over the Kimberly SWAT+ field.

See ``EXPERIMENTS.md`` for the plan. Phase 0 (this code) is the hot path the rest is priced
off: :class:`~swat_gym.fastrunner.FastRunner`.
"""
from .engine import EngineError, find_engine, run_engine
from .fastrunner import EDITABLE, TXTINOUT, FastRunner
from .manifest import input_files
from .rewarders import Prices, manure_applied, nass, profit

__all__ = [
    "EDITABLE",
    "EngineError",
    "FastRunner",
    "Prices",
    "TXTINOUT",
    "find_engine",
    "input_files",
    "manure_applied",
    "nass",
    "profit",
    "run_engine",
]
