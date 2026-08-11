"""Observation normalisation statistics that travel with a trained policy.

**Why this exists.** Without observation normalisation, PPO here learns an *exactly constant*
schedule: measured 2026-08-07, the standard deviation of applied depth across held-out weather
windows is **0.000 mm** on raw observations and **6.4 mm** with :class:`~stable_baselines3.common.
vec_env.VecNormalize`. The 13 observation channels are scaled by order-of-magnitude divisors
rather than statistically, and several sit near zero in practice (``strsn/50``, ``strsw/50`` when
stress is 0-5), so a network fed them learns to ignore them. Normalising also raised return by
1,320 $/ha and cut applied water 6,116 -> 5,352 mm.

**Why the statistics are saved separately from the policy.** A policy trained on normalised
observations *must* be scored on normalised observations. Scoring it on raw ones is not a
degradation, it is a different objective — the same class of silent divergence as applying a
nitrogen cap on one code path and not another, which inverted this experiment's headline once.
SB3 keeps the running statistics inside a ``VecNormalize`` wrapper around the training vector
env, but scoring runs a single un-vectorised environment, so the statistics are extracted here
and carried alongside the policy file.

The scorers take the normaliser as a **required** argument. ``None`` means "this policy was
trained on raw observations" and must be stated, never defaulted.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class ObsNorm:
    """Frozen copy of a ``VecNormalize`` observation filter."""

    mean: np.ndarray
    var: np.ndarray
    clip: float = 10.0
    epsilon: float = 1e-8

    def __call__(self, obs: np.ndarray) -> np.ndarray:
        """Apply exactly ``VecNormalize.normalize_obs``."""
        z = (np.asarray(obs, dtype=np.float64) - self.mean) / np.sqrt(self.var + self.epsilon)
        return np.clip(z, -self.clip, self.clip).astype(np.float32)

    def save(self, path: str | Path) -> None:
        np.savez(Path(path), mean=self.mean, var=self.var,
                 clip=self.clip, epsilon=self.epsilon)

    @classmethod
    def load(cls, path: str | Path) -> ObsNorm:
        d = np.load(Path(path))
        return cls(mean=d["mean"], var=d["var"],
                   clip=float(d["clip"]), epsilon=float(d["epsilon"]))

    @classmethod
    def from_vecnormalize(cls, venv) -> ObsNorm:
        rms = venv.obs_rms
        return cls(mean=np.array(rms.mean, dtype=np.float64),
                   var=np.array(rms.var, dtype=np.float64),
                   clip=float(venv.clip_obs), epsilon=float(venv.epsilon))


def apply(obsnorm: ObsNorm | None, obs: np.ndarray) -> np.ndarray:
    """``obsnorm(obs)`` when normalising, the raw observation when not."""
    return obs if obsnorm is None else obsnorm(obs)
