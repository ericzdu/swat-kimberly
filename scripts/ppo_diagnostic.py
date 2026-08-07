#!/usr/bin/env python3
"""Why did PPO learn a constant? A short, instrumented comparison of training setups.

The headline from Exp 1 is that PPO loses to matched-budget open-loop search, and that its
``adaptivity_value`` is **exactly 0.0 on all three seeds** — the policy emits an identical
schedule on every weather window. Three independent seeds landing on exactly zero is a
systematic cause, not a coincidence, and until we know whether it is a property of the problem
or of the training setup, "RL fails here" is not a finding.

Two suspects, both cheap to test:

* **No observation normalisation.** Raw observations go straight into PPO. The 13 channels are
  scaled by ad-hoc divisors and several sit near zero in practice (``strsn/50``, ``strsw/50``
  when stress is 0-5). A network fed weakly-varying inputs learns to ignore them.
* **Action saturation.** ``log_std_init = -1`` is sigma ~ 0.37 on a unit action box, so sampled
  actions clip at the bounds constantly. The previous policy applied 5,008 mm against a
  measured 3,939 — consistent with a mean pushed high and clipping at the top.

What is measured, per configuration:

1. **Learning curve** — is it still climbing at the end, or plateaued? Decides "undertrained".
2. **Action spread across weather windows** — the direct test of "learned a constant". The
   deterministic policy is rolled out on each test window; if the emitted schedules are
   identical, the observation is being ignored.
3. **Action spread across steps** within a window — a policy emitting one number for all 42
   months is more degenerate still.
4. **Saturation** — fraction of actions at the bounds.

    uv run python scripts/ppo_diagnostic.py --timesteps 30000
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from swat_gym.monthly_env import EPISODE_STEPS, MonthlySwatEnv
from swat_gym.rewarders import average
from swat_gym.windows import TEST_YEARS, TRAIN_YEARS

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "runs" / "ppo_diagnostic.json"
PNG = ROOT / "runs" / "paper_tables" / "ppo_diagnostic.png"

#: (label, use VecNormalize, log_std_init)
CONFIGS = (
    ("current (raw obs, sigma=0.37)", False, -1.0),
    ("+ VecNormalize", True, -1.0),
    ("+ VecNormalize, sigma=0.14", True, -2.0),
)


def _make(seed: int, i: int, prices):
    def _f():
        from stable_baselines3.common.monitor import Monitor
        return Monitor(MonthlySwatEnv(stochastic_weather=True, train_years=TRAIN_YEARS,
                                      prices=prices, no3_price=0.0, seed=seed + i,
                                      arm="I", max_n=None).to_gym())
    return _f


def train_one(label, use_norm, log_std, *, timesteps, n_envs, seed, prices):
    from stable_baselines3 import PPO
    from stable_baselines3.common.callbacks import BaseCallback
    from stable_baselines3.common.vec_env import SubprocVecEnv, VecNormalize

    class Curve(BaseCallback):
        def __init__(self):
            super().__init__()
            self.pts: list[tuple[int, float]] = []

        def _on_step(self) -> bool:
            buf = self.model.ep_info_buffer
            if buf and self.num_timesteps % (EPISODE_STEPS * 4) == 0:
                self.pts.append((int(self.num_timesteps),
                                 float(np.mean([e["r"] for e in buf]))))
            return True

    venv = SubprocVecEnv([_make(seed, i, prices) for i in range(n_envs)])
    if use_norm:
        venv = VecNormalize(venv, norm_obs=True, norm_reward=False, clip_obs=10.0)
    cb = Curve()
    t0 = time.time()
    try:
        model = PPO("MlpPolicy", venv, seed=seed, verbose=0,
                    n_steps=EPISODE_STEPS * 4, batch_size=EPISODE_STEPS * 2,
                    gamma=1.0, policy_kwargs={"log_std_init": log_std})
        model.learn(total_timesteps=timesteps, callback=cb, progress_bar=False)
        secs = time.time() - t0

        # Deterministic rollout on each held-out window: does the schedule change with weather?
        plans, acts = [], []
        env = MonthlySwatEnv(stochastic_weather=False, prices=prices, arm="I", max_n=None)
        try:
            for sy in TEST_YEARS:
                obs, _ = env.reset(start_year=sy)
                done = False
                while not done:
                    o = venv.normalize_obs(obs) if use_norm else obs
                    a, _ = model.predict(o, deterministic=True)
                    acts.append(float(np.clip(a, 0, 1).ravel()[0]))
                    obs, _, term, trunc, info = env.step(a)
                    done = bool(term or trunc)
                plans.append(env.month_mm.copy())
        finally:
            env.close()
    finally:
        venv.close()

    P = np.stack(plans)                       # (windows, years, months)
    across_windows = float(P.std(axis=0).mean())
    within_window = float(P.reshape(len(P), -1).std(axis=1).mean())
    acts = np.asarray(acts)
    sat = float(((acts <= 1e-3) | (acts >= 1 - 1e-3)).mean())
    return {
        "label": label, "vecnormalize": use_norm, "log_std_init": log_std,
        "curve": cb.pts, "seconds": round(secs, 1),
        "mean_water_mm": float(P.sum(axis=(1, 2)).mean()),
        "action_std_across_windows_mm": across_windows,
        "action_std_within_window_mm": within_window,
        "saturated_frac": sat,
        "final_return": cb.pts[-1][1] if cb.pts else None,
    }


def plot(rows, png: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 2, figsize=(12, 8))
    colors = ["#4C72B0", "#DD8452", "#55A868"]

    a = ax[0, 0]
    for r, c in zip(rows, colors):
        if r["curve"]:
            x, y = zip(*r["curve"])
            a.plot(x, np.asarray(y) * 1000.0, color=c, label=r["label"], lw=1.6)
    a.set_xlabel("timesteps (engine runs)"); a.set_ylabel("episode return ($/ha)")
    a.set_title("Learning curve — is it still climbing?"); a.legend(fontsize=8)
    a.grid(alpha=.3)

    a = ax[0, 1]
    x = np.arange(len(rows))
    a.bar(x - .2, [r["action_std_across_windows_mm"] for r in rows], .4,
          label="across weather windows", color="#C44E52")
    a.bar(x + .2, [r["action_std_within_window_mm"] for r in rows], .4,
          label="across months", color="#8172B3")
    a.set_xticks(x); a.set_xticklabels([r["label"] for r in rows], fontsize=7, rotation=12)
    a.set_ylabel("std of applied depth (mm)")
    a.set_title("Does the policy vary?  ~0 across windows = ignores observation")
    a.legend(fontsize=8); a.grid(alpha=.3, axis="y")

    a = ax[1, 0]
    a.bar(x, [100 * r["saturated_frac"] for r in rows], .5, color="#937860")
    a.set_xticks(x); a.set_xticklabels([r["label"] for r in rows], fontsize=7, rotation=12)
    a.set_ylabel("% of actions at a bound")
    a.set_title("Action saturation (0 or 200 mm)"); a.grid(alpha=.3, axis="y")

    a = ax[1, 1]
    a.bar(x, [r["mean_water_mm"] for r in rows], .5, color="#4C72B0")
    for ref, lbl, c in ((3938.8, "measured practice", "k"),
                        (3930.8, "CMA-ES optimum", "#55A868")):
        a.axhline(ref, ls="--", lw=1.2, color=c, label=f"{lbl} ({ref:.0f} mm)")
    a.set_xticks(x); a.set_xticklabels([r["label"] for r in rows], fontsize=7, rotation=12)
    a.set_ylabel("applied water over rotation (mm)")
    a.set_title("Water applied vs references"); a.legend(fontsize=8); a.grid(alpha=.3, axis="y")

    fig.suptitle("PPO training diagnostic — monthly irrigation arm", fontsize=13)
    fig.tight_layout()
    png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png, dpi=150)
    print(f"-> {png}")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--timesteps", type=int, default=30_000, help="per configuration")
    ap.add_argument("--n-envs", type=int, default=4)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args(argv)

    prices = average()
    rows = []
    for label, use_norm, log_std in CONFIGS:
        print(f"\n=== {label} : {args.timesteps} timesteps ===", flush=True)
        r = train_one(label, use_norm, log_std, timesteps=args.timesteps,
                      n_envs=args.n_envs, seed=args.seed, prices=prices)
        rows.append(r)
        print(f"  {r['seconds']:.0f}s  return {r['final_return']}  "
              f"water {r['mean_water_mm']:.0f} mm  "
              f"std across windows {r['action_std_across_windows_mm']:.3f} mm  "
              f"saturated {100 * r['saturated_frac']:.0f}%", flush=True)

    hdr = (f"{'configuration':<32}{'return':>10}{'water mm':>10}"
           f"{'std/wins':>10}{'std/mon':>9}{'sat %':>7}")
    print("\n" + hdr); print("-" * len(hdr))
    for r in rows:
        print(f"{r['label']:<32}{(r['final_return'] or 0) * 1000:>10.0f}"
              f"{r['mean_water_mm']:>10.0f}{r['action_std_across_windows_mm']:>10.3f}"
              f"{r['action_std_within_window_mm']:>9.1f}{100 * r['saturated_frac']:>7.0f}")
    print("\nstd across windows ~0 => the policy ignores its observation (a constant schedule)")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, indent=2))
    print(f"-> {OUT}")
    plot(rows, PNG)
    return rows


if __name__ == "__main__":
    main()
