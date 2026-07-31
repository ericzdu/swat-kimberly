"""Monthly growing-season Gymnasium environment (Stage 2).

One decision per growing-season month (Apr–Sep) × 7 years = 42 steps. Each step appends that
month's irrigation (and optional mineral N), re-runs the full rotation with ops decided so
far, and reads mid-season state from monthly ``hru_wb`` / ``hru_pw`` tables.

**No future weather in the observation.** The policy sees soil water, cumulative stress, and
recent precip/PET from months already simulated — a nowcast, not a forecast.

**N cap is forward-only.** A remaining annual allowance is part of the observation and clips
the current month's mineral application; past months are never rewritten (unlike prefix
``repair`` on the whole plan).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

import numpy as np

from .constrainers import MANURE_N_FRAC, MAX_N_LOADING, mineral_n, manure_n, repair
from .env import (DEFAULT_PLAN, N_YEARS, SPINUP, WEATHER_YEARS, arm_dims, decode_year,
                  time_sim)
from .fastrunner import EDITABLE, FastRunner
from .monthly import MONTH_DEPTH_MAX, N_GROWING, plan_from_monthly_i
from .rewarders import Prices, nass, profit
from .schedule import CROPS, GROWING_MONTHS, YearAction, build

#: Observation: [step_frac, crop one-hot (3), stand_frac, sw, strsn, strsw,
#:               precip_30, pet_30, remaining_n_frac, month_of_season, year_frac]
OBS_DIM_MONTHLY = 14

EPISODE_STEPS = N_YEARS * N_GROWING  # 42


class MonthlySwatEnv:
    """Monthly-cadence irrigation (and optional N) environment."""

    REWARD_SCALE = 1e-3

    def __init__(self, runner: FastRunner | None = None, *, prices: Prices | None = None,
                 stochastic_weather: bool = True, train_years: Sequence[int] | None = None,
                 no3_price: float = 0.0, seed: int | None = None,
                 reward_scale: float | None = None, arm: str = "I",
                 max_n: float | None = MAX_N_LOADING) -> None:
        self._own = runner is None
        self.runner = runner or FastRunner(editable=EDITABLE)
        self.prices = prices or nass(2024)
        self.max_n = max_n
        self.arm = arm
        self.stochastic_weather = stochastic_weather
        self.no3_price = no3_price
        self.reward_scale = self.REWARD_SCALE if reward_scale is None else reward_scale
        lo, hi = WEATHER_YEARS
        self.train_years = list(train_years) if train_years is not None else list(
            range(lo, hi - N_YEARS - SPINUP + 2)
        )
        self.rng = np.random.default_rng(seed)
        # Free action width: I → 1 (depth); N → 2 (mineral kg + manure flag); all → more.
        self.action_dim = {"I": 1, "N": 2, "R": 3, "all": 4}.get(arm, 1)
        self.reset()

    def reset(self, *, seed: int | None = None, start_year: int | None = None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        if start_year is not None:
            self.start_year = start_year
        elif self.stochastic_weather:
            self.start_year = int(self.rng.choice(self.train_years))
        else:
            self.start_year = 2013
        self.t = 0
        self.month_mm = np.zeros((N_YEARS, N_GROWING), dtype=float)
        self.mineral_mm = np.zeros((N_YEARS, N_GROWING), dtype=float)  # kg N per month
        self.manure_year = np.zeros(N_YEARS, dtype=float)  # Mg/ha, applied in month 0 if >0
        self.cum_profit = 0.0
        self.last = dict(sw=200.0, strsn=0.0, strsw=0.0, precip=20.0, pet=100.0,
                         remaining_n=float(self.max_n or MAX_N_LOADING))
        # Year crop sequence from DEFAULT_PLAN (measured rotation) unless arm R/all.
        self.crops = [decode_year(DEFAULT_PLAN[y]).crop for y in range(N_YEARS)]
        return self._obs(), {}

    @property
    def year_idx(self) -> int:
        return min(self.t // N_GROWING, N_YEARS - 1)

    @property
    def month_idx(self) -> int:
        return self.t % N_GROWING

    def _remaining_n(self, year: int) -> float:
        if self.max_n is None:
            return 1e9
        used = float(self.mineral_mm[year].sum())
        if self.manure_year[year] > 0:
            src = decode_year(DEFAULT_PLAN[year]).manure_src
            used += self.manure_year[year] * MANURE_N_FRAC[src] * 1000.0
        return max(0.0, float(self.max_n) - used)

    def _apply_action(self, action: Sequence[float]) -> None:
        a = np.asarray(action, dtype=float).ravel()
        y, m = self.year_idx, self.month_idx
        if self.arm in ("I", "all"):
            depth = float(np.clip(a[0], 0.0, 1.0)) * MONTH_DEPTH_MAX
            self.month_mm[y, m] = depth
        if self.arm in ("N", "all"):
            # a[0] or a[1]: mineral fraction of remaining allowance this month.
            idx = 0 if self.arm == "N" else 1
            frac = float(np.clip(a[idx], 0.0, 1.0))
            rem = self._remaining_n(y)
            self.mineral_mm[y, m] = frac * rem
            # Manure once in April (month index 0) if arm N and second dim high.
            if self.arm == "N" and m == 0 and len(a) > 1:
                base = decode_year(DEFAULT_PLAN[y])
                self.manure_year[y] = float(np.clip(a[1], 0.0, 1.0)) * 90.0
            elif self.arm == "all" and m == 0 and len(a) > 2:
                self.manure_year[y] = float(np.clip(a[2], 0.0, 1.0)) * 90.0
        if self.arm in ("R", "all") and m == 0:
            # Crop chosen at year start only.
            scores = a[-3:] if self.arm == "R" else a[-3:]
            if len(a) >= 3:
                scores = a[:3] if self.arm == "R" else a[-3:]
                self.crops[y] = CROPS[int(np.argmax(scores))]

    def _build_plan(self) -> list[YearAction]:
        plan: list[YearAction] = []
        for y in range(N_YEARS):
            base = decode_year(DEFAULT_PLAN[y])
            if self.arm == "I":
                act = replace(
                    base,
                    irr_depth=0.0,
                    irr_interval=0,
                    irr_month_depths=tuple(float(v) for v in self.month_mm[y]),
                )
            else:
                splits = tuple(
                    (_doy_mid(GROWING_MONTHS[mi]), float(self.mineral_mm[y, mi]))
                    for mi in range(N_GROWING) if self.mineral_mm[y, mi] > 0
                )
                act = replace(
                    base,
                    crop=self.crops[y],
                    manure_mg=(float(self.manure_year[y])
                               if self.manure_year[y] > 0 else base.manure_mg),
                    fert_splits=splits if splits else (),
                    fert_n_kg=0.0,
                    irr_depth=0.0,
                    irr_interval=0,
                    irr_month_depths=tuple(float(v) for v in self.month_mm[y]),
                )
            plan.append(act)
        # Rotation constraints only — do NOT rescale past N applications.
        return repair(plan, max_n=None)

    def step(self, action: Sequence[float]):
        self._apply_action(action)
        plan = self._build_plan()
        edits = build(plan)
        edits["time.sim"] = time_sim(self.start_year, N_YEARS + SPINUP)
        self.runner.run(edits)
        d = profit(self.runner, self.prices, no3_price=self.no3_price)
        reward = (d["profit"] - self.cum_profit) * self.reward_scale
        self.cum_profit = d["profit"]
        self.last = self._read_state()
        self.last["remaining_n"] = self._remaining_n(self.year_idx)
        self.t += 1
        terminated = self.t >= EPISODE_STEPS
        return self._obs(), reward, terminated, False, {"cum_profit": self.cum_profit, **d}

    def _read_state(self) -> dict:
        out = dict(sw=200.0, strsn=0.0, strsw=0.0, precip=20.0, pet=100.0)
        try:
            wb = self.runner.read("hru_wb_mon.txt")
            pw = self.runner.read("hru_pw_mon.txt")
        except Exception:
            return out
        if wb is not None and len(wb):
            row = wb.iloc[-1]
            for key, candidates in (("sw", ("sw_final", "sw")), ("precip", ("precip", "rain")),
                                    ("pet", ("pet",))):
                for c in candidates:
                    if c in row.index:
                        out[key] = float(row[c])
                        break
        if pw is not None and len(pw):
            row = pw.iloc[-1]
            for key in ("strsn", "strsw"):
                if key in row.index:
                    out[key] = float(row[key])
        return out

    def _obs(self) -> np.ndarray:
        y, m = self.year_idx, self.month_idx
        crop = self.crops[y]
        onehot = [1.0 if crop == c else 0.0 for c in CROPS]
        stand = 0
        for yy in range(y, -1, -1):
            if self.crops[yy] == "alfa":
                stand += 1
            else:
                break
        rem = self.last.get("remaining_n", float(self.max_n or MAX_N_LOADING))
        cap = float(self.max_n or MAX_N_LOADING) or 1.0
        return np.array([
            self.t / EPISODE_STEPS,
            *onehot,
            stand / N_YEARS,
            self.last["sw"] / 300.0,
            self.last["strsn"] / 50.0,
            self.last["strsw"] / 50.0,
            self.last["precip"] / 50.0,
            self.last["pet"] / 200.0,
            rem / cap,
            m / N_GROWING,
            y / N_YEARS,
        ], dtype=np.float32)

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
            metadata = {"render_modes": []}
            observation_space = spaces.Box(-np.inf, np.inf, (OBS_DIM_MONTHLY,), np.float32)
            action_space = spaces.Box(0.0, 1.0, (outer.action_dim,), np.float32)

            def reset(self, *, seed=None, options=None):
                return outer.reset(seed=seed)

            def step(self, action):
                return outer.step(action)

            def close(self):
                outer.close()

        return _Gym()


def _doy_mid(month: int) -> int:
    from .schedule import _doy
    return _doy(month, 15)
