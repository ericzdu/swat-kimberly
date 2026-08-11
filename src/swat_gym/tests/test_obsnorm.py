"""The observation filter must travel with the policy, exactly."""
from __future__ import annotations

import inspect

import numpy as np
import pytest

from swat_gym.obsnorm import ObsNorm, apply


def _norm(seed=0, dim=13):
    rng = np.random.default_rng(seed)
    return ObsNorm(mean=rng.normal(size=dim), var=rng.uniform(0.5, 2.0, size=dim), clip=10.0)


def test_matches_real_vecnormalize():
    """Checked against SB3's own filter, not against a re-statement of my formula.

    Re-implementing the arithmetic and asserting it equals itself would pass while diverging
    from what PPO actually trained on, which is the only thing that matters here.
    """
    import gymnasium as gym
    from stable_baselines3.common.vec_env import DummyVecEnv, VecNormalize

    class Fake(gym.Env):
        observation_space = gym.spaces.Box(-np.inf, np.inf, (13,), np.float32)
        action_space = gym.spaces.Box(0.0, 1.0, (1,), np.float32)

        def reset(self, *, seed=None, options=None):
            self._r = np.random.default_rng(0)
            return self._r.normal(size=13).astype(np.float32), {}

        def step(self, a):
            return self._r.normal(size=13).astype(np.float32), 0.0, False, False, {}

    venv = VecNormalize(DummyVecEnv([lambda: Fake()]), norm_obs=True,
                        norm_reward=False, clip_obs=10.0)
    try:
        venv.reset()
        for _ in range(50):
            venv.step(np.zeros((1, 1), dtype=np.float32))
        mine = ObsNorm.from_vecnormalize(venv)
        obs = np.linspace(-4, 4, 13).astype(np.float32)
        assert mine(obs) == pytest.approx(venv.normalize_obs(obs), rel=1e-6, abs=1e-6)
        assert mine(obs).dtype == np.float32
    finally:
        venv.close()


def test_clipping_binds():
    n = ObsNorm(mean=np.zeros(3), var=np.ones(3), clip=2.0)
    assert n(np.array([100.0, -100.0, 0.0])) == pytest.approx([2.0, -2.0, 0.0])


def test_round_trips_through_disk(tmp_path):
    n = _norm(1)
    p = tmp_path / "obsnorm.npz"
    n.save(p)
    back = ObsNorm.load(p)
    obs = np.arange(13, dtype=float)
    assert back(obs) == pytest.approx(n(obs), rel=1e-12)
    assert back.clip == n.clip


def test_apply_passes_raw_when_none():
    obs = np.arange(13, dtype=float)
    assert apply(None, obs) is obs


def test_scorers_require_an_explicit_obsnorm():
    """No default, for the same reason ``max_n`` has none.

    A policy trained on normalised observations and scored on raw ones is not degraded, it is
    solving a different problem — and the numbers stay plausible, so nothing warns you. The
    nitrogen-cap version of this mistake inverted Exp 1's headline.
    """
    from swat_gym.experiments.exp1_irrigation import score_policy_monthly

    p = inspect.signature(score_policy_monthly).parameters["obsnorm"]
    assert p.default is inspect.Parameter.empty, (
        "score_policy_monthly gave obsnorm a default; that is how the cap bug happened")


def test_training_config_keys_the_filter():
    """A raw-observation policy must not resume into a normalised run."""
    from swat_gym.experiments import exp1_irrigation as m

    assert m.NORMALISE_OBS is True
    assert m.LOG_STD_INIT == -2.0
    src = inspect.getsource(m.main)
    assert '"normalise_obs"' in src and '"log_std_init"' in src, (
        "cfg must carry the observation filter and exploration scale, or a policy trained "
        "under different settings can be silently reused")
