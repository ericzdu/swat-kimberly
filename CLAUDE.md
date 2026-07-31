# swat-kimberly — agent entrypoint (Claude Code / Cursor)

## Goal

Calibrated SWAT+ field environment (Kimberly, ID) for management optimisation. Research
question: **does adaptivity pay** under a protocol that can tell search from adaptation?

## Locked experimental design

| Exp | Lever | How | Module |
|---|---|---|---|
| 1 | Irrigation | Monthly Apr–Sep; CMA open-loop + feedback controller + PPO + frozen | `exp1_irrigation` (+ `exp1_ceiling`, `exp1_controller`) |
| 2 | Nitrogen | Manure + mineral under one cap | `exp2_nitrogen` |
| 3 | Rotation | **Enumerate** feasible sequences (no CMA/PPO) | `exp3_rotation` |
| 4 | Joint | Warm-start from 1–3; joint < composed ⇒ optimizer, not interaction | `exp4_joint` |

**Run order = paper order:** gate → ceiling → controller → Exp 1 → 2 → 3 → 4.

## Hard rules

1. Do **not** fold nitrate leaching into the reward; report it alongside profit.
2. Match PPO and CMA budgets in **engine runs**, not native units.
3. Never report a single PPO seed as the Exp 1 / Exp 4 headline (`--ppo-seeds ≥ 3`).
4. Observation must **not** contain future weather (no oracle forecast).
5. Validate generated baseline irrigation vs measured (3,938.8 mm) within **1 %** before scoring arms.
6. Frozen plans are selected on **train**, scored on **test** (never argmax on test).
7. Train/test windows share **zero** calendar years (`swat_gym.windows`).
8. If Exp 4 joint < composed single-lever optima → optimizer failure, not a science claim.
9. Do not revive superseded modules for new results: `exp1_ablation.py`, annual `exp2_rl.py`.

## Staged build (do not skip)

1. Protocol fixes + monthly open-loop (`monthly.py`) + monthly `print.prt` outputs
2. `exp1_ceiling` — if ceiling ≤ ~$250/ha noise floor, skip cluster PPO; write bounded null
3. `exp1_controller` — CMA feedback row
4. Monthly gym (`monthly_env.py`) + Exp 1 PPO
5. Exp 2 → 3 → 4

## Pointers

- Runbook: [`EXPERIMENTS.md`](EXPERIMENTS.md)
- Manuscript: [`paper.md`](paper.md)
- Pre-submission gaps: [`OPEN_ITEMS.md`](OPEN_ITEMS.md)
- Input provenance: [`PROVENANCE.md`](PROVENANCE.md)

## Cluster (`instgpu-01` … `05`)

SWAT+ is **CPU-bound**. Use CPU cores + `SubprocVecEnv`, not GPUs. Need Linux ELF engine
binary (Mac Mach-O will not run). Prefer one experiment/seed per node.

## Quick commands

```bash
uv sync --extra dev
uv run pytest
uv run pytest -m slow          # includes monthly nesting gate vs measured mm

# Stage 1 gate
uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000
uv run python -m swat_gym.experiments.exp1_controller --budget 5000

# Exp 1 (after ceiling passes)
uv run python -m swat_gym.experiments.exp1_irrigation --budget 300000 --ppo-seeds 3

# Exp 2–4
uv run python -m swat_gym.experiments.exp2_nitrogen --budget 300000
uv run python -m swat_gym.experiments.exp3_rotation
uv run python -m swat_gym.experiments.exp4_joint --budget 300000 --ppo-seeds 3
```
