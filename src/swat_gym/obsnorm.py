"""VecNormalize stats saved beside a policy so scoring uses the same obs normalisation.

Without it PPO learns a constant schedule. Scorers require the normaliser; None = raw obs.
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
