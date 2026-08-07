# `swat-gym` — experiment runbook

**Agent entrypoint:** see [`CLAUDE.md`](CLAUDE.md). This file is the executable how-to.

The agent controls **irrigation, manure/N, and rotation**; SWAT+ supplies the dynamics.
Lives in `src/swat_gym/`. Sibling to `../rufas-gym` and `../aquaswat-gym`.

## Staging

| Stage | What | State |
|---|---|---|
| 0. Fast environment | engine call cheap enough for RL | done (`FastRunner` ~0.17 s) |
| 1. Calibration | response trustworthy within named bounds | closed as far as engine allows |
| 2. Protocol fixes | zero year-leakage; freeze on train; CMA history | done (`windows.py`, `_focused.py`) |
| 3. Monthly open-loop | Apr–Sep depths; nest annual default | `monthly.py` |
| 4. Foresight gate | perfect foresight vs shared schedule (an *estimate*, not a ceiling) | `exp1_ceiling` |
| 5. Feedback controller | CMA closed-loop row | `exp1_controller` |
| 6. Monthly gym + Exp 1–4 | adaptivity under monthly MDP | `monthly_env.py` + `exp1`…`exp4` |

## Execution order (locked = paper numbering)

```
pytest → exp1_ceiling → exp1_controller → exp1_irrigation → exp2_nitrogen → exp3_rotation → exp4_joint
```

Do **not** start Exp 4 until Exp 1’s frozen-plan sign is stable across seeds.
Do **not** start cluster PPO if `exp1_ceiling` reports `gate_pass: false`. The key is
`foresight_test`, not `ceiling_test`: an under-converged oracle biases it *down*, so a policy
can legitimately exceed it. Measured 2026-08-06: **+836 ± 68 $/ha**.

## Five-row protocol

| Row | Meaning |
|---|---|
| `measured` | shipped `management.sch` — human bar |
| `default` | `DEFAULT_PLAN` through the same generator |
| `fixed` | CMA-ES open-loop (monthly for Exp 1) |
| `policy` | PPO |
| `frozen` | policy’s plan selected on **train**, replayed on **test** |

Plus Exp 1 extras: **ceiling** (perfect foresight) and **controller** (CMA feedback).

## Experiments

### Exp 1 — Irrigation (monthly)

```bash
uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000
# or the whole Exp 1 pipeline, detached, with the objective-parity preflight:
#   perl -e 'use POSIX; setsid(); exec @ARGV' -- bash scripts/rerun_exp1.sh
uv run python -m swat_gym.experiments.exp1_controller --budget 5000
uv run python -m swat_gym.experiments.exp1_irrigation --budget 300000 --ppo-seeds 3
# open-loop only after failed gate:
uv run python -m swat_gym.experiments.exp1_irrigation --budget 300000 --skip-ppo
```

Outputs: `runs/exp1_ceiling.json`, `runs/exp1_controller.json`, `runs/exp1_irrigation.json`.

### Exp 2 — Nitrogen

```bash
uv run python -m swat_gym.experiments.exp2_nitrogen --budget 300000
```

Output: `runs/exp2_nitrogen.json`.

### Exp 3 — Rotation (enumerate)

```bash
uv run python -m swat_gym.experiments.exp3_rotation
# smoke:
uv run python -m swat_gym.experiments.exp3_rotation --max-seqs 50
```

Output: `runs/exp3_rotation.json`. No PPO.

### Exp 4 — Joint

```bash
uv run python -m swat_gym.experiments.exp4_joint --budget 300000 --ppo-seeds 3
```

Warm-starts from Exp 2/3 artefacts when present. Rule: joint < composed ⇒ optimizer, not interaction.

## Train / test windows

Defined in `src/swat_gym/windows.py`:

- Train starts: 1995–2004 (10 windows; spans end ≤ 2011)
- Test starts: 2013–2017 (5 windows; spans ≥ 2013)
- **Zero shared calendar years**

## Cluster (UW–Madison CS `instgpu-01`…`05`)

- Workload is **CPU-bound** (SWAT+ processes). GPUs idle.
- Linux ELF SWAT+ binary required.
- 8–16 `SubprocVecEnv` workers; one seed/experiment per node.
- `tmux` + write under `runs/exp{N}_*`.

Suggested map after Exp 1 smoke is green:

1. Node A: Exp 1 seeds 0/1/2
2. Then Node A: Exp 2; Node B: Exp 3; both → Exp 4

## Gate checklist before full runs

- [ ] `uv run pytest` green
- [ ] `uv run pytest -m slow` — monthly default irrigation within 1% of 3,938.8 mm
- [ ] `assert_no_leakage()` passes (import `swat_gym.windows`)
- [ ] `exp1_ceiling` written; if `gate_pass` false, skip PPO
- [ ] Water price sourced or breakeven reported (re-optimize under sweep when sourced)

## Deleted 2026-08-07 (recover from git history if ever needed)

The tree now holds only modules that are live for the paper. Everything below was removed in one
pass; git history is the archive.

**Leaky split — do not restore without re-pointing it.** `exp2_rl.py` (annual-cadence PPO with
budget asymmetry), `exp2b_controls.py` (its frozen-plan controls), `scripts/run_overnight.sh`
(their driver). These carried a private `TRAIN_YEARS`/`TEST_YEARS` pair — 1995–2011 / 2012–2018 —
predating `swat_gym.windows` and overlapping by seven of eight calendar years. They never imported
`windows`, so `assert_no_leakage()` never ran and they produced leaky numbers without failing.

**Superseded by the monthly pivot.** `exp1_ablation.py` (six-arm combination ablation) and the
old-numbering redirects `exp1_nitrogen.py` / `exp2_irrigation.py` (thin shims to Exp 2 / Exp 1 —
pre-pivot command lines no longer resolve).

**Retired sweeps whose *results* remain load-bearing.** `exp1b_price_ratio.py` and
`exp1c_cadence.py`, plus `tests/test_cadence.py` which imported the latter. The code is gone but
the evidence is not: `rewarders.py:247` still cites `runs/exp1b_price_ratio.json` for the price
curve, and `env.py:45` still cites `runs/exp1c_cadence_e500.json` for the constant-dimensionality
result (k ≥ 3 lost 310–835 $/ha). **Those JSONs are retained in `runs/` and must not be deleted** —
they are the only surviving record, since `runs/` is gitignored. Regenerating either curve means
restoring the module from history first.

## Engine cost

| Cadence | Steps / episode | Approx. cost |
|---|---|---|
| Open-loop (full rotation) | 1 | 0.17 s |
| Annual | 7 | ~1.5 s |
| Monthly growing season | 42 | ~7 s |
| Weekly | ~230 | ~40 s (infeasible) |
