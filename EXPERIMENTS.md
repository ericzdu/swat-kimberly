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
Do **not** start cluster PPO if `exp1_ceiling` reports `gate_pass: false` — `rerun_exp1.sh`
now exits 2 rather than leaving that to the operator (`FORCE_PPO=1` overrides deliberately).
The gate is **λ_n-independent** (the ceiling scores at `no3_price = 0` by construction), so it
is computed once and reused across frontier points instead of re-run per `OUT_TAG`. The key is
`foresight_test`, not `ceiling_test`: an under-converged oracle biases it *down*, so a policy
can legitimately exceed it. ~~Measured 2026-08-06: +836 ± 68 $/ha.~~ **Stale — re-run before
quoting (2026-08-28):** `runs/exp1_ceiling.json` is not on disk, the ± was a naive SE that rule 7
no longer permits, and the figure predates the rule 11b crop-parameter reconciliation.

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
uv run python -m swat_gym.experiments.exp2_nitrogen --budget 300000 \
    --max-n none --ppo-seeds 3
```

Output: `runs/exp2_nitrogen.json`.

### Exp 3 — Rotation (enumerate)

```bash
uv run python -m swat_gym.experiments.exp3_rotation --max-n none
# smoke:
uv run python -m swat_gym.experiments.exp3_rotation --max-n none --max-seqs 50
```

Output: `runs/exp3_rotation.json`. No PPO.

### Exp 4 — Joint

```bash
uv run python -m swat_gym.experiments.exp4_joint --budget 300000 --ppo-seeds 3 \
    --max-n none
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

- [ ] `uv run python scripts/check_param_state.py` PASS — the model's crop parameters are the
      collaborator's workbook (rule 11b) and no fit has silently reverted them
- [ ] `uv run pytest` green
- [ ] `uv run pytest -m slow` — monthly default irrigation within 1% of 3,938.8 mm
- [ ] `assert_no_leakage()` passes (import `swat_gym.windows`)
- [ ] `exp1_ceiling` written; if `gate_pass` false, skip PPO
- [ ] Water price sourced or breakeven reported (re-optimize under sweep when sourced)
- [ ] **`--max-n` passed explicitly and identical across every experiment being composed.**
      Exp 1 is uncapped, so Exp 2/3/4 need `--max-n none` to compose with it. The runners now
      refuse to start without the flag, and Exp 4 refuses to warm-start across a mismatch.
- [ ] **Intervals quoted as `se_ess`, never `se_naive`.** ESS is 1.25 on the five test windows,
      so anything under a few hundred $/ha is not resolvable by this split — say that rather
      than quoting a tight naive SE.

**Sustainability gates.** Nitrate is the second objective, not an annotation, so an experiment is
not done when the profit column is filled in.

- [ ] **The λ_n frontier is produced, not just the λ_n = 0 arm.** Every experiment ships a sweep,
      never a single price (hard rule 1). `NO3_PRICE=<λ> OUT_TAG=<tag> bash scripts/rerun_exp1.sh`
      gives **one point**; the deliverable is the set. Publishing one interior point as "the"
      answer is the failure rule 1 exists to prevent.
- [ ] **The leaching column is non-degenerate before any sustainability claim.** At measured
      practice the signal is **zero**, not merely sparse: re-measured 2026-08-28, percolation
      and nitrate are 0.00 at the measured and default schedules, and drainage begins only above
      ~×1.2 applied water (OPEN_ITEMS #11). λ_n therefore separates arms only where one
      over-irrigates. If the arms being compared do not separate on leaching, report that as the
      finding; do not report a frontier drawn through zeros.
- [ ] **Both limits restated wherever a sustainability claim is made:** leaching unvalidated on
      site, N₂O Tier 1 accounting and never priced.

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

**Off the path to the goal.** `scripts/n_response.py` (mineral-N sweep; the `max_n` question it
asked is now threaded explicitly through `env.py` and answered by `runs/exp1_nitrogen_uncapped*`),
`scripts/exp1_weekly.py` + `src/swat_gym/weekly.py` (weekly action space — Exp 1 is locked to a
monthly Apr–Sep cadence, and nothing imported the module), and the two ports whose own docstrings
declared them dead: `scripts/port_solar.py` (RETIRED — claimed an ArcSWAT gauge it was not reading)
and `scripts/port_weather.py` (SUPERSEDED by `port_agrimet.py`; the last RuFaS dependency). Neither
port is in `build_model.sh`. Their *findings* survive in PROVENANCE §3 and §5 — only the code is
gone. `scripts/event_size_check.py` had the one import from `weekly.py`; `WEEK_START_DOY` is now
inlined there.

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
