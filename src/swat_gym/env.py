"""Env: action vector -> profit via SWAT+.

evaluate(): open-loop, one engine run per full-rotation plan.
SwatEnv: annual gym env; state at year t = re-run years 0..t (no SWAT+ restart).
Episodes sample an 8-yr weather window from 1995-2025 via time.sim.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from .constrainers import MAX_N_LOADING, repair, violations
from .fastrunner import EDITABLE, FastRunner
from .rewarders import Prices, nass, profit
from .schedule import CROPS, MANURE_SOURCES, YearAction, build

#: 7 scored years + 1 spin-up year.
N_YEARS = 7
SPINUP = 1

#: Per-year action dimensions, all in [0, 1].
#: 0-2 crop scores (argmax) | 3 manure rate | 4 manure day | 5 manure source (binned)
#: 6 mineral rate 1 | 7 mineral day 1 | 8 mineral rate 2 | 9 mineral day 2
#: 10 irrigation start | 11 irrigation interval | 12 irrigation depth
#: Two mineral applications (k>=3 measured worse; k=1 reachable by zeroing one).
ACTION_DIM = 13

#: Dims each arm may move; the rest stay at DEFAULT_PLAN. Rotation is fixed (not a lever).
ARMS = {
    "baseline": (),
    "N": (3, 4, 5, 6, 7, 8, 9),
    "I": (10, 11, 12),
}

#: Measured-practice baseline all arms are scored against. Irrigation depth 32.82 mm/event
#: reproduces the measured 3,938.8 mm; mineral N = 0 (measured practice is manure-only).
DEFAULT_ACTION = np.array([
    0.9, 0.1, 0.1,   # crop scores -> corn
    0.50,            # manure 45 Mg/ha
    0.4595,          # manure day 100 (10 April, the measured date)
    0.00,            # manure source gn2013
    0.00,            # mineral rate 1 — 0 kg/ha, measured practice applies none
    0.4231,          # mineral day 1 — 120
    0.00,            # mineral rate 2 — 0 kg/ha
    0.5385,          # mineral day 2 — 152
    0.375,           # irrigation start day 130
    0.2222,          # irrigation interval 7 d
    0.8206,          # irrigation depth 32.82 mm -> 3,938.8 mm/rotation, the measured total
])

MEASURED_ROTATION = ("corn", "barl", "alfa", "alfa", "alfa", "corn", "barl")


#: Measured GRACEnet manure per rotation year (Mg/ha, source), so DEFAULT_PLAN nests measured N.
MEASURED_MANURE: tuple[tuple[float, str | None], ...] = (
    (43.8, "gn2013"),   # 2013 corn
    (48.0, "gn2014"),   # 2014 barley
    (0.0, None),        # 2015 alfalfa
    (0.0, None),        # 2016 alfalfa
    (0.0, None),        # 2017 alfalfa
    (88.3, "gn2018"),   # 2018 corn
    (54.3, "gn2019"),   # 2019 barley
)


def _encode_manure(mass_mg: float, source: str | None) -> tuple[float, float]:
    """(mass, source) -> genes v[3], v[5]."""
    lo, hi = _RANGES[3]
    v3 = (mass_mg - lo) / (hi - lo)
    # Aim at bucket centre so float error can't change the source.
    idx = MANURE_SOURCES.index(source) if source else 0
    return v3, (idx + 0.5) / len(MANURE_SOURCES)


def _default_plan() -> np.ndarray:
    plan = np.tile(DEFAULT_ACTION, (N_YEARS, 1))
    for i, crop in enumerate(MEASURED_ROTATION):
        plan[i, 0:3] = 0.1
        plan[i, CROPS.index(crop)] = 0.9
        mass, src = MEASURED_MANURE[i]
        plan[i, 3], plan[i, 5] = _encode_manure(mass, src)
    return plan


#: Earliest application DOY. If optima pin here, it's a model artefact, not agronomy.
TIMING_FLOOR = 32.0

_RANGES = {
    3: (0.0, 90.0),               # manure Mg/ha
    4: (TIMING_FLOOR, 180.0),     # manure day of year
    # Mineral top = MAX_N_LOADING so the cap, not the range, binds.
    6: (0.0, 400.0),              # mineral application 1, kg N/ha
    7: (TIMING_FLOOR, 240.0),     # mineral application 1, day of year
    8: (0.0, 400.0),              # mineral application 2, kg N/ha
    9: (TIMING_FLOOR, 240.0),     # mineral application 2, day of year
    10: (100.0, 180.0),           # irrigation start day of year
    11: (3.0, 21.0),              # irrigation interval, days
    12: (0.0, 40.0),              # irrigation depth, mm/event
}

DEFAULT_PLAN = _default_plan()

WEATHER_YEARS = (1995, 2025)

#: Obs: t, prev-crop one-hot(3), stand age, last yield, last NO3, strsn, strsw, sw_final,
#: n_surplus (balance residual, not a soil test). No future weather.
OBS_DIM = 11


def _lerp(x: float, lo: float, hi: float) -> float:
    return lo + float(np.clip(x, 0.0, 1.0)) * (hi - lo)


def decode_year(vec: Sequence[float]) -> YearAction:
    v = np.asarray(vec, dtype=float)
    src_i = min(int(np.clip(v[5], 0.0, 0.999) * len(MANURE_SOURCES)), len(MANURE_SOURCES) - 1)
    # Zero-rate splits are skipped by the schedule (no pass charged).
    splits = tuple(
        (int(round(_lerp(v[doy_i], *_RANGES[doy_i]))), _lerp(v[rate_i], *_RANGES[rate_i]))
        for rate_i, doy_i in ((6, 7), (8, 9))
    )
    return YearAction(
        crop=CROPS[int(np.argmax(v[0:3]))],
        manure_mg=_lerp(v[3], *_RANGES[3]),
        manure_doy=int(round(_lerp(v[4], *_RANGES[4]))),
        manure_src=MANURE_SOURCES[src_i],
        fert_splits=splits,
        irr_start_doy=int(round(_lerp(v[10], *_RANGES[10]))),
        irr_interval=int(round(_lerp(v[11], *_RANGES[11]))),
        irr_depth=_lerp(v[12], *_RANGES[12]),
    )


def decode(flat: Sequence[float], *, constrain: bool = True,
           max_n: float | None = MAX_N_LOADING) -> list[YearAction]:
    """Flat vector -> feasible plan. ``max_n=None`` disables the N cap."""
    a = np.asarray(flat, dtype=float).reshape(N_YEARS, ACTION_DIM)
    plan = [decode_year(row) for row in a]
    return repair(plan, max_n=max_n) if constrain else plan


def arm_dims(arm: str) -> tuple[int, ...]:
    """Dimensions an arm owns."""
    if arm not in ARMS:
        raise KeyError(f"unknown arm {arm!r}; expected one of {sorted(ARMS)}")
    return ARMS[arm]


def arm_vector(free: Sequence[float], arm: str) -> np.ndarray:
    """Expand an arm's free params into a full vector; other dims stay at DEFAULT_PLAN."""
    dims = arm_dims(arm)
    full = DEFAULT_PLAN.copy()
    if dims:
        full[:, list(dims)] = np.asarray(free, dtype=float).reshape(N_YEARS, len(dims))
    return full.ravel()


def default_free(arm: str) -> np.ndarray:
    """The arm's free parameters at their default values — its optimisation start point."""
    dims = arm_dims(arm)
    return DEFAULT_PLAN[:, list(dims)].ravel() if dims else np.zeros(0)


def time_sim(start_year: int, n_years: int = N_YEARS + SPINUP) -> str:
    """A ``time.sim`` selecting one weather window out of the ported record."""
    return (
        "time.sim: written by swat_gym.env\n"
        "day_start  yrc_start   day_end   yrc_end      step  \n"
        f"{0:>10}{start_year:>11}{0:>10}{start_year + n_years - 1:>10}{0:>10}  \n"
    )


def _edits(plan: list[YearAction], start_year: int) -> dict[str, str]:
    e = build(plan)
    e["time.sim"] = time_sim(start_year, len(plan) + SPINUP)
    return e


def evaluate(flat: Sequence[float], runner: FastRunner, *, prices: Prices | None = None,
             start_year: int = 2012, constrain: bool = True, no3_price: float = 0.0,
             max_n: float | None = MAX_N_LOADING) -> dict:
    """Open-loop: score one complete rotation plan with a single engine run."""
    prices = prices or nass(2024)
    plan = decode(flat, constrain=constrain, max_n=max_n)
    runner.run(_edits(plan, start_year))
    out = profit(runner, prices, no3_price=no3_price)
    out["plan"] = [(a.crop, round(a.manure_mg, 1),
                    [(d, round(kg, 1)) for d, kg in a.fert_splits], a.irr_depth)
                   for a in plan]
    out["start_year"] = start_year
    out["infeasible"] = violations(plan, max_n=max_n)
    return out


class SwatEnv:
    """Annual-cadence gymnasium-style env (no gymnasium import; see to_gym)."""

    #: Scales the PPO learning signal only; info['cum_profit'] stays in $.
    REWARD_SCALE = 1e-3

    def __init__(self, runner: FastRunner | None = None, *, prices: Prices | None = None,
                 stochastic_weather: bool = True, train_years: Sequence[int] | None = None,
                 no3_price: float = 0.0, seed: int | None = None,
                 reward_scale: float | None = None, arm: str,
                 max_n: float | None = MAX_N_LOADING) -> None:
        self._own = runner is None
        self.runner = runner or FastRunner(editable=EDITABLE)
        self.prices = prices or nass(2024)
        self.max_n = max_n
        #: Policy only moves its arm's dims; rest stay at DEFAULT_PLAN.
        self.free_dims = arm_dims(arm)
        self.arm = arm
        self.stochastic_weather = stochastic_weather
        self.no3_price = no3_price
        self.reward_scale = self.REWARD_SCALE if reward_scale is None else reward_scale
        lo, hi = WEATHER_YEARS
        self.train_years = list(train_years) if train_years is not None else list(
            range(lo, hi - N_YEARS - SPINUP + 2)
        )
        self.rng = np.random.default_rng(seed)
        self.reset()

    # -- gymnasium-ish API ---------------------------------------------------------------

    def reset(self, *, seed: int | None = None, start_year: int | None = None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        if start_year is not None:
            self.start_year = start_year
        elif self.stochastic_weather:
            self.start_year = int(self.rng.choice(self.train_years))
        else:
            self.start_year = 2012
        self.plan: list[YearAction] = []
        self.cum_profit = 0.0
        self.last = dict.fromkeys(
            ("yield", "no3", "strsn", "strsw", "sw", "n_surplus"), 0.0)
        return self._obs(), {}

    def expand(self, action: Sequence[float]) -> np.ndarray:
        """Policy free params -> full year vector, defaults from DEFAULT_PLAN[t]."""
        a = np.asarray(action, dtype=float)
        t = min(len(self.plan), N_YEARS - 1)
        full = DEFAULT_PLAN[t].copy()
        full[list(self.free_dims)] = a
        return full

    def step(self, action: Sequence[float]):
        self.plan.append(decode_year(self.expand(action)))
        # Repair the whole prefix: alfalfa stand constraints span years.
        plan = repair(self.plan, max_n=self.max_n)
        self.runner.run(_edits(plan, self.start_year))
        d = profit(self.runner, self.prices, no3_price=self.no3_price)

        reward = (d["profit"] - self.cum_profit) * self.reward_scale
        self.cum_profit = d["profit"]
        self.last = self._carryover(d)
        self.plan = plan
        terminated = len(self.plan) >= N_YEARS
        return self._obs(), reward, terminated, False, {"cum_profit": self.cum_profit, **d}

    def _carryover(self, d: dict) -> dict:
        """Last-year state the next decision may see (see OBS_DIM)."""
        y = self.runner.yields()
        pw = self.runner.read("hru_pw_yr.txt")
        wb = self.runner.read("hru_wb_yr.txt")
        nb = self.runner.read("basin_nb_yr.txt")
        # Cumulative over the rotation.
        surplus = float(
            (nb["fertn"] + nb["fixn"] + nb["act_nit_n"] + nb["no3atmo"] + nb["nh4atmo"]
             - nb["nuptake"] - nb["denit"]).sum() - pw["percn"].sum()
        )
        return {
            "yield": float(y["yld(t)"].iloc[-1]) if len(y) else 0.0,
            "no3": d["no3_leached_kg"],
            "strsn": float(pw["strsn"].iloc[-1]),
            "strsw": float(pw["strsw"].iloc[-1]),
            "sw": float(wb["sw_final"].iloc[-1]),
            "n_surplus": surplus,
        }

    def _obs(self) -> np.ndarray:
        t = len(self.plan)
        prev = self.plan[-1].crop if self.plan else None
        onehot = [1.0 if prev == c else 0.0 for c in CROPS]
        stand = 0
        for a in reversed(self.plan):
            if a.crop == "alfa":
                stand += 1
            else:
                break
        # Rough scaling to ~[0, 1].
        return np.array(
            [t / N_YEARS, *onehot, stand / N_YEARS,
             self.last["yield"] / 30.0,
             self.last["no3"] / 10.0,
             self.last["strsn"] / 50.0,
             self.last["strsw"] / 50.0,
             self.last["sw"] / 300.0,
             self.last["n_surplus"] / 200.0],
            dtype=np.float32,
        )

    def close(self) -> None:
        if self._own:
            self.runner.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # -- gymnasium adapter ---------------------------------------------------------------

    def to_gym(self):
        """Wrap as a real ``gymnasium.Env`` (requires the ``rl`` extra)."""
        import gymnasium as gym
        from gymnasium import spaces

        outer = self

        class _Gym(gym.Env):
            metadata = {"render_modes": []}
            observation_space = spaces.Box(-np.inf, np.inf, (OBS_DIM,), dtype=np.float32)
            # Expose only the arm's dims.
            action_space = spaces.Box(0.0, 1.0, (len(outer.free_dims),), dtype=np.float32)

            def reset(self, *, seed=None, options=None):
                return outer.reset(seed=seed)

            def step(self, action):
                return outer.step(action)

            def close(self):
                outer.close()

        return _Gym()
