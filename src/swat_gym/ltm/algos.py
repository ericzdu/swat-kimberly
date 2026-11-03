"""Algorithm comparison on one LTM lever: every method gets the same budget in HRU-episode
steps (LtmRunner.n_hru_runs, the unit ES and CMA-ES are matched in) and is selected on the
train windows only.

Closed loop (a policy that reads the soil state before every decision; env.Episode):
  es       OpenAI-ES (es.es_seed), unchanged
  ga       genetic algorithm on the same 64x64 network (Such et al. 2017, arXiv:1712.06567):
           truncation selection, Gaussian mutation, one elite, no crossover
  ppo/sac  stable-baselines3 PPO and SAC on a vectorised env whose 16 copies share one engine
           run (LtmVecEnv); sparse terminal reward = the episode's strategy score
Open loop (one fixed schedule for every window):
  cma      CMA-ES from measured practice (experiments.common.minimise)
  ga_open  real-coded GA on the decision vector
  random   uniform random search on the decision vector

Every job returns the same record: a learning curve (train score of the current pick against
HRU runs spent), the picked solution's train and test episodes, and seconds.
"""
from __future__ import annotations

import time

import numpy as np

from ..engine import EngineError
from .env import OBS_DIM, Episode, plan_from_x
from .es import ES, es_seed, evaluate, forward, init_genome, safe_scores
from .practice import decisions, measured_x
from .runner import LtmRunner
from .score import Reference, episode
from .windows import TEST, TRAIN

#: closed-loop population / vector-env width: one engine run carries this many HRUs
POP = 16
#: snapshots evaluated on all train windows for the final pick (as ES)
CURVE_POINTS = ES["curve_points"]
GA = {"population": POP, "parents": 4, "elite": 1, "sigma": ES["sigma"],
      "init": "independent SB3-actor inits (output gain 0.01: every genome starts at measured practice)"}
GA_OPEN = {"population": POP, "elite": 2, "tournament": 3, "crossover": "BLX-0.5, p 0.9",
           "mutation": "Gaussian sd 0.1 per gene, p 1/n", "init": "measured x + N(0, 0.25), and measured x"}
RANDOM = {"batch": POP, "sampling": "uniform on the unit box; measured x first"}
SB3 = {"n_envs": POP, "net": [64, 64], "gamma": 1.0, "reward": "strategy score at the last step, 0 before",
       "ppo": {"n_steps": 160, "batch_size": 640, "n_epochs": 10, "learning_rate": 3e-4,
               "gae_lambda": 0.95, "log_std_init": -2.0, "activation": "tanh"},
       "sac": {"learning_rate": 3e-4, "buffer_size": 300_000, "batch_size": 256,
               "learning_starts": 1600, "train_freq": 1, "gradient_steps": 4, "tau": 0.005,
               "activation": "relu"},
       "action": "residual in [-1, 1] around measured x (env.Episode.absolute)",
       "windows": "one train window per round of episodes, cycling through a shuffled order"}
CONFIG = {"pop": POP, "curve_points": CURVE_POINTS, "es": ES, "ga": GA, "ga_open": GA_OPEN,
          "random": RANDOM, "sb3": SB3}


def _record(algo, seed, t0, spent, curve, train_eps, test_eps, **extra) -> dict:
    return {"algo": algo, "seed": seed, "seconds": time.time() - t0, "hru_runs": int(spent),
            "curve": curve, "picked_train_score": float(curve[-1]["train_score"]) if curve else None,
            "train": train_eps, "test": test_eps, **extra}


# -- closed loop ------------------------------------------------------------------------------

def run_es(lever, w, prices, ref_key, budget, seed) -> dict:
    t0 = time.time()
    r = es_seed((lever, w, prices, ref_key, budget, seed))
    curve = [{"hru_runs": c["hru_runs"], "train_score": s}
             for c, s in zip(r["curve"], r["snapshot_train_scores"])]
    rec = _record("es", seed, t0, r["hru_runs"], curve, r["train"], r["test"],
                  generations=r["generations"], engine_failures=r["engine_failures"])
    rec["picked_train_score"] = r["picked_train_score"]
    return rec


def run_ga(lever, w, prices, ref_key, budget, seed) -> dict:
    """Neuroevolution of the ES network: each generation keeps the elite (deterministic
    fitness on the same train windows, so it is not re-scored) and fills the population with
    mutated copies of the top ``parents``."""
    t0 = time.time()
    ref = Reference.from_key(ref_key)
    rng = np.random.default_rng(seed)
    T = len(decisions(lever))
    P, E, K, sig = GA["population"], GA["elite"], GA["parents"], GA["sigma"]
    tally = {"planned": 0, "failed": 0, "crashed_batches": 0, "kept": 0, "first_error": None}
    curve = []
    with LtmRunner(P, batched=True) as run_r, LtmRunner(1, batched=True) as test_r:
        pop = np.stack([init_genome(lever, rng) for _ in range(P)])
        tally["planned"] = budget // (len(TRAIN) * T)
        fit = safe_scores(lever, pop, run_r, TRAIN, prices, ref, w, tally).mean(1)
        curve.append({"hru_runs": int(run_r.n_hru_runs), "train_score": float(fit.max()),
                      "generation": 0, "fit_median": float(np.median(fit))})
        gen = 0
        while run_r.n_hru_runs + (P - E) * len(TRAIN) * T <= budget:
            gen += 1
            order = np.argsort(fit)[::-1]
            elite, parents = pop[order[:E]], pop[order[:K]]
            kids = parents[rng.integers(0, K, P - E)] + sig * rng.standard_normal((P - E, pop.shape[1]))
            kfit = safe_scores(lever, kids, run_r, TRAIN, prices, ref, w, tally).mean(1)
            pop = np.concatenate([elite, kids])
            fit = np.concatenate([fit[order[:E]], kfit])
            curve.append({"hru_runs": int(run_r.n_hru_runs), "train_score": float(fit.max()),
                          "generation": gen, "fit_median": float(np.median(fit))})
        best = pop[int(np.argmax(fit))]
        spent = run_r.n_hru_runs
        train_eps = [evaluate(lever, best[None], test_r, s, prices)[0] for s in TRAIN]
        test_eps = [evaluate(lever, best[None], test_r, s, prices)[0] for s in TEST]
    return _record("ga", seed, t0, spent, curve, train_eps, test_eps, generations=gen,
                   engine_failures={k: tally[k] for k in ("failed", "crashed_batches", "first_error")})


class _Rounds:
    """Train windows for successive rounds of episodes: a reshuffled cycle."""

    def __init__(self, rng):
        self.rng, self.queue = rng, []

    def next(self) -> int:
        if not self.queue:
            self.queue = list(self.rng.permutation(TRAIN))
        return int(self.queue.pop())


def make_vec_env(lever, w, prices, ref, runner, rng):
    """SB3 VecEnv of POP closed-loop episodes on one window, all in the same engine runs (the
    run_policy loop, unrolled for SB3). Episodes end together after len(decisions) steps."""
    import gymnasium as gym
    from stable_baselines3.common.vec_env.base_vec_env import VecEnv

    class LtmVecEnv(VecEnv):
        def __init__(self):
            super().__init__(POP, gym.spaces.Box(-np.inf, np.inf, (OBS_DIM,), np.float32),
                             gym.spaces.Box(-1.0, 1.0, (1,), np.float32))
            self.rounds, self.scores = _Rounds(rng), []
            self.actions = None
            self.ds = decisions(lever)

        def reset(self):
            self.start = self.rounds.next()
            self.eps = [Episode(lever) for _ in range(POP)]
            return np.stack([e.reset(self.start) for e in self.eps])

        def step_async(self, actions):
            self.actions = actions

        def step_wait(self):
            plans = [e.write(e.absolute(a)) for e, a in zip(self.eps, self.actions)]
            t = self.eps[0].t
            last = self.start + self.ds[t + 1].k if t + 1 < len(self.ds) else None
            try:
                outs = runner.run(plans, self.start, last)
            except EngineError:              # one retry (a rare transient crash; es.FAILED_SCORE)
                outs = runner.run(plans, self.start, last)
            obs = np.stack([e.observe(o) for e, o in zip(self.eps, outs)])
            if not self.eps[0].done:
                return obs, np.zeros(POP, np.float32), np.zeros(POP, bool), [{} for _ in range(POP)]
            r = np.array([ref.score(episode(p, o, prices, self.start), w)
                          for p, o in zip(plans, outs)], np.float32)
            self.scores.append(float(r.mean()))
            infos = [{"terminal_observation": obs[i], "TimeLimit.truncated": False}
                     for i in range(POP)]
            return self.reset(), r, np.ones(POP, bool), infos

        def close(self):
            pass

        def get_attr(self, attr_name, indices=None):
            return [getattr(self, attr_name)] * POP

        def set_attr(self, attr_name, value, indices=None):
            setattr(self, attr_name, value)

        def env_method(self, method_name, *args, indices=None, **kwargs):
            return [None] * POP

        def env_is_wrapped(self, wrapper_class, indices=None):
            return [False] * POP

        def seed(self, seed=None):
            return [None] * POP

    return LtmVecEnv()


def _policy_fn(model):
    return lambda obs: model.predict(obs, deterministic=True)[0]


def _closed_eval(lever, policy, runner, windows, prices) -> list[dict]:
    from .env import run_policy
    out = []
    for s in windows:
        plans, outs, xs = run_policy(policy, lever, runner, 1, s)
        out.append({**episode(plans[0], outs[0], prices, s), "x": xs[0].tolist()})
    return out


def run_sb3(algo, lever, w, prices, ref_key, budget, seed) -> dict:
    """PPO or SAC until the budget less the snapshot evaluations is spent; the final pick is
    the best of CURVE_POINTS snapshots on all train windows (budgeted, as ES)."""
    import copy

    import torch
    from stable_baselines3 import PPO, SAC
    from stable_baselines3.common.callbacks import BaseCallback

    torch.set_num_threads(1)
    t0 = time.time()
    ref = Reference.from_key(ref_key)
    rng = np.random.default_rng(seed)
    T = len(decisions(lever))
    snap_cost = len(TRAIN) * T
    train_budget = budget - CURVE_POINTS * snap_cost
    marks = list(np.linspace(train_budget / CURVE_POINTS, train_budget, CURVE_POINTS))
    snaps: list = []
    with LtmRunner(POP, batched=True) as run_r, LtmRunner(1, batched=True) as eval_r:
        env = make_vec_env(lever, w, prices, ref, run_r, rng)
        cfg = SB3[algo]
        if algo == "ppo":
            model = PPO("MlpPolicy", env, n_steps=cfg["n_steps"], batch_size=cfg["batch_size"],
                        n_epochs=cfg["n_epochs"], learning_rate=cfg["learning_rate"],
                        gamma=SB3["gamma"], gae_lambda=cfg["gae_lambda"], seed=seed, verbose=0,
                        device="cpu",
                        policy_kwargs={"net_arch": SB3["net"], "log_std_init": cfg["log_std_init"],
                                       "activation_fn": torch.nn.Tanh})
        else:
            model = SAC("MlpPolicy", env, learning_rate=cfg["learning_rate"],
                        buffer_size=cfg["buffer_size"], batch_size=cfg["batch_size"],
                        learning_starts=cfg["learning_starts"], train_freq=cfg["train_freq"],
                        gradient_steps=cfg["gradient_steps"], tau=cfg["tau"], gamma=SB3["gamma"],
                        seed=seed, verbose=0, device="cpu",
                        policy_kwargs={"net_arch": SB3["net"], "activation_fn": torch.nn.ReLU})

        class Stop(BaseCallback):
            def _on_step(self) -> bool:
                while marks and run_r.n_hru_runs >= marks[0]:
                    marks.pop(0)
                    snaps.append((int(run_r.n_hru_runs), copy.deepcopy(model.policy.state_dict())))
                # stop at the end of an episode round once the training budget is spent
                return not (run_r.n_hru_runs + POP * T > train_budget and env.eps[0].t == 0)

        model.learn(total_timesteps=10 ** 9, callback=Stop())
        spent_train = run_r.n_hru_runs
        if not snaps or snaps[-1][0] != spent_train:
            snaps.append((int(spent_train), copy.deepcopy(model.policy.state_dict())))
        snaps = snaps[-CURVE_POINTS:]
        curve, best, best_s = [], None, -np.inf
        for at, sd in snaps:
            model.policy.load_state_dict(sd)
            eps = _closed_eval(lever, _policy_fn(model), eval_r, TRAIN, prices)
            s = float(np.mean([ref.score(e, w) for e in eps]))
            curve.append({"hru_runs": at, "train_score": s})
            if s > best_s:
                best_s, best = s, (sd, eps)
        spent = spent_train + eval_r.n_hru_runs        # training + snapshot selection
        model.policy.load_state_dict(best[0])
        test_eps = _closed_eval(lever, _policy_fn(model), eval_r, TEST, prices)
        episode_scores = env.scores
    rec = _record(algo, seed, t0, spent, curve, best[1], test_eps,
                  episode_curve=episode_scores[::max(1, len(episode_scores) // 200)])
    rec["picked_train_score"] = best_s
    return rec


# -- open loop --------------------------------------------------------------------------------

def _open_scores(lever, w, prices, ref, xs, runners) -> np.ndarray:
    """Mean train score of each decision vector (one batched engine run per window)."""
    k = len(xs)
    if k not in runners:
        runners[k] = LtmRunner(k, batched=True)
    plans = [plan_from_x(lever, np.asarray(x)) for x in xs]
    cols = []
    for s in TRAIN:
        try:
            outs = runners[k].run(plans, s)
        except EngineError:
            outs = runners[k].run(plans, s)
        cols.append([ref.score(episode(p, o, prices, s), w) for p, o in zip(plans, outs)])
    return np.array(cols).mean(0)


def _open_record(algo, seed, t0, lever, x, curve, prices, spent, **extra) -> dict:
    plan = plan_from_x(lever, np.asarray(x))
    with LtmRunner(1, batched=True) as r:
        train_eps = [{**episode(plan, r.run([plan], s)[0], prices, s), "x": list(map(float, x))}
                     for s in TRAIN]
        test_eps = [{**episode(plan, r.run([plan], s)[0], prices, s), "x": list(map(float, x))}
                    for s in TEST]
    return _record(algo, seed, t0, spent, curve, train_eps, test_eps, x=list(map(float, x)), **extra)


def run_cma(lever, w, prices, ref_key, budget, seed) -> dict:
    from ..experiments.common import minimise
    from ..experiments.ltm import _Objective
    t0 = time.time()
    evals = max(10, budget // len(TRAIN))
    x, n, hist = minimise(_Objective(lever, prices, ref_key, w), measured_x(lever), evals=evals,
                          windows=TRAIN, batched=True, seed=seed, workers=1,
                          label=f"cma seed {seed}")
    curve = [{"hru_runs": int(h["evals"]) * len(TRAIN), "train_score": -float(h["best_f"])}
             for h in hist]
    return _open_record("cma", seed, t0, lever, x, curve, prices, n * len(TRAIN), evals=int(n))


def run_ga_open(lever, w, prices, ref_key, budget, seed) -> dict:
    t0 = time.time()
    ref = Reference.from_key(ref_key)
    rng = np.random.default_rng(seed)
    x0 = measured_x(lever)
    n, P, E, cost = len(x0), GA_OPEN["population"], GA_OPEN["elite"], len(TRAIN)
    runners: dict = {}
    pop = np.clip(x0 + 0.25 * rng.standard_normal((P, n)), 0, 1)
    pop[0] = x0
    fit = _open_scores(lever, w, prices, ref, pop, runners)
    spent, curve, gen = P * cost, [], 0
    try:
        while spent + (P - E) * cost <= budget:
            gen += 1
            order = np.argsort(fit)[::-1]

            def pick():
                c = rng.integers(0, P, GA_OPEN["tournament"])
                return pop[c[np.argmax(fit[c])]]

            kids = []
            for _ in range(P - E):
                a, b = pick(), pick()
                if rng.random() < 0.9:          # BLX-0.5
                    lo, hi = np.minimum(a, b), np.maximum(a, b)
                    d = hi - lo
                    c = rng.uniform(lo - 0.5 * d, hi + 0.5 * d)
                else:
                    c = a.copy()
                mut = rng.random(n) < 1.0 / n
                c[mut] += 0.1 * rng.standard_normal(mut.sum())
                kids.append(np.clip(c, 0, 1))
            kids = np.array(kids)
            kfit = _open_scores(lever, w, prices, ref, kids, runners)
            spent += len(kids) * cost
            pop = np.concatenate([pop[order[:E]], kids])
            fit = np.concatenate([fit[order[:E]], kfit])
            curve.append({"hru_runs": int(spent), "train_score": float(fit.max()), "generation": gen})
    finally:
        for r in runners.values():
            r.close()
    return _open_record("ga_open", seed, t0, lever, pop[int(np.argmax(fit))], curve, prices, spent,
                        generations=gen)


def run_random(lever, w, prices, ref_key, budget, seed) -> dict:
    t0 = time.time()
    ref = Reference.from_key(ref_key)
    rng = np.random.default_rng(seed)
    x0 = measured_x(lever)
    n, B, cost = len(x0), RANDOM["batch"], len(TRAIN)
    runners: dict = {}
    best_x, best_f, spent, curve = None, -np.inf, 0, []
    try:
        first = True
        while spent + B * cost <= budget:
            xs = rng.random((B, n))
            if first:
                xs[0], first = x0, False
            f = _open_scores(lever, w, prices, ref, xs, runners)
            spent += B * cost
            i = int(np.argmax(f))
            if f[i] > best_f:
                best_f, best_x = float(f[i]), xs[i].copy()
            curve.append({"hru_runs": int(spent), "train_score": best_f})
    finally:
        for r in runners.values():
            r.close()
    return _open_record("random", seed, t0, lever, best_x, curve[:: max(1, len(curve) // 400)]
                        + curve[-1:], prices, spent)


RUNNERS = {"es": run_es, "ga": run_ga, "ppo": lambda *a: run_sb3("ppo", *a),
           "sac": lambda *a: run_sb3("sac", *a), "cma": run_cma, "ga_open": run_ga_open,
           "random": run_random}
CLOSED = ("es", "ga", "ppo", "sac")
OPEN = ("cma", "ga_open", "random")


def run_job(args) -> dict:
    """Pool job: (algo, lever, w, prices, ref_key, budget, seed) -> record, or the error."""
    import traceback
    algo, *rest = args
    try:
        return RUNNERS[algo](*rest)
    except Exception:
        return {"algo": algo, "seed": rest[-1], "error": traceback.format_exc()}
