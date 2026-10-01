"""Monthly Gymnasium env for either lever. One step = one growing-season month.

Lever I: 42 steps (all years), action = [depth / MONTH_DEPTH_MAX].
Lever N: 24 steps (annual-crop years only), action = [mineral N / MONTH_N_MAX,
         manure / MANURE_MAX (used in April only)].

Each step re-simulates the whole window with decisions so far (undecided months = 0; SWAT+
has no restart), so episode profit == plan.evaluate(lever, env.x). Observations read only
the month just decided (no future weather).
"""
from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from .fastrunner import EDITABLE, FastRunner
from .plan import (ANNUAL_YEARS, DIMS, MEASURED_ROTATION, N_GROWING, N_YEARS, SPINUP,
                   evaluate)
from .rewarders import Prices, nass
from .schedule import CROPS, GROWING_MONTHS
from .windows import TRAIN_YEARS

OBS_DIM = 13
REWARD_SCALE = 1e-3
#: State before any month is simulated.
INITIAL_STATE = {"sw": 250.0, "strsn": 0.0, "strsw": 0.0, "precip": 20.0, "pet": 100.0}


class SwatEnv:
    def __init__(self, lever: str, *, prices: Prices | None = None, no3_price: float = 0.0,
                 train_years: Sequence[int] = TRAIN_YEARS, seed: int | None = None,
                 runner: FastRunner | None = None) -> None:
        self.lever = lever
        self.prices = prices or nass(2024)
        self.no3_price = no3_price
        self.train_years = list(train_years)
        self.rng = np.random.default_rng(seed)
        self._own = runner is None
        self.runner = runner or FastRunner(editable=EDITABLE)
        years = range(N_YEARS) if lever == "I" else ANNUAL_YEARS
        #: (year, month index) for each step.
        self.steps = [(y, m) for y in years for m in range(N_GROWING)]
        self.action_dim = 1 if lever == "I" else 2
        self.reset(start_year=self.train_years[0])

    def reset(self, *, seed: int | None = None, start_year: int | None = None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        self.start_year = (start_year if start_year is not None
                           else int(self.rng.choice(self.train_years)))
        self.t = 0
        self.x = np.zeros(DIMS[self.lever])
        self.cum_profit = 0.0
        self.last = dict(INITIAL_STATE)
        return self._obs(), {}

    def _write_action(self, action) -> None:
        a = np.clip(np.asarray(action, dtype=float).ravel(), 0.0, 1.0)
        y, m = self.steps[self.t]
        if self.lever == "I":
            self.x[y * N_GROWING + m] = a[0]
        else:
            row = ANNUAL_YEARS.index(y) * (N_GROWING + 1)
            self.x[row + m] = a[0]
            if m == 0:
                self.x[row + N_GROWING] = a[1]

    def step(self, action):
        y, m = self.steps[self.t]
        self._write_action(action)
        d = evaluate(self.lever, self.x, self.runner, prices=self.prices,
                     start_year=self.start_year, no3_price=self.no3_price)
        reward = (d["profit"] - self.cum_profit) * REWARD_SCALE
        self.cum_profit = d["profit"]
        self.last = self._read_state(y, m)
        self.t += 1
        done = self.t >= len(self.steps)
        return self._obs(), reward, done, False, d

    def _read_state(self, y: int, m: int) -> dict:
        """State at the end of the month just decided (by year and month, not last row)."""
        out = dict(INITIAL_STATE)
        yr, mon = self.start_year + SPINUP + y, GROWING_MONTHS[m]
        for table, keys in (("hru_wb_mon.txt", ("sw_final", "precip", "pet")),
                            ("hru_pw_mon.txt", ("strsn", "strsw"))):
            df = self.runner.read(table)
            hit = df[(df["yr"] == yr) & (df["mon"] == mon)]
            if len(hit):
                for k in keys:
                    out["sw" if k == "sw_final" else k] = float(hit.iloc[0][k])
        return out

    def _obs(self) -> np.ndarray:
        y, m = self.steps[min(self.t, len(self.steps) - 1)]
        crop = MEASURED_ROTATION[y]
        stand = 0
        for c in reversed(MEASURED_ROTATION[:y + 1]):
            if c != "alfa":
                break
            stand += 1
        n_year = 0.0
        if self.lever == "N":
            row = ANNUAL_YEARS.index(y) * (N_GROWING + 1)
            n_year = float(self.x[row:row + N_GROWING].sum()) / N_GROWING
        s = self.last
        return np.array([self.t / len(self.steps),
                         *[1.0 if crop == c else 0.0 for c in CROPS],
                         stand / N_YEARS, s["sw"] / 300.0, s["strsn"] / 50.0,
                         s["strsw"] / 50.0, s["precip"] / 50.0, s["pet"] / 200.0,
                         n_year, m / N_GROWING, y / N_YEARS], dtype=np.float32)

    def close(self) -> None:
        if self._own:
            self.runner.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def to_gym(self):
        import gymnasium as gym
        from gymnasium import spaces

        outer = self

        class _Gym(gym.Env):
            observation_space = spaces.Box(-np.inf, np.inf, (OBS_DIM,), np.float32)
            action_space = spaces.Box(0.0, 1.0, (outer.action_dim,), np.float32)

            def reset(self, *, seed=None, options=None):
                return outer.reset(seed=seed)

            def step(self, action):
                return outer.step(action)

            def close(self):
                outer.close()

        return _Gym()


def rollout(env: SwatEnv, policy: Callable[[SwatEnv, np.ndarray], Sequence[float]],
            start_year: int) -> dict:
    """Run one episode; ``policy(env, obs) -> action``. Returns final profit terms + x."""
    obs, _ = env.reset(start_year=start_year)
    done = False
    while not done:
        obs, _, done, _, info = env.step(policy(env, obs))
    return {**info, "x": env.x.copy()}
