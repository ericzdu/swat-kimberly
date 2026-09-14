# `swat-gym` — experiment runbook

**Agent entrypoint:** see [`CLAUDE.md`](CLAUDE.md). This file is the executable how-to.

The agent controls **irrigation and manure/N**; SWAT+ supplies the dynamics. The rotation is a
**fixed property of the environment**, not a lever — it was one until 2026-09-09; see the scope
cut below.
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
| 6. Monthly gym + Exp 1–2 | adaptivity under monthly MDP | `monthly_env.py` + `exp1`, `exp2` |

## Execution order (locked = paper numbering)

```
pytest → exp1_ceiling → exp1_controller → exp1_irrigation → exp2_nitrogen
```

Do **not** start cluster PPO if `exp1_ceiling` reports `gate_pass: false` — `rerun_exp1.sh`
now exits 2 rather than leaving that to the operator (`FORCE_PPO=1` overrides deliberately).
The gate is **λ_n-independent** (the ceiling scores at `no3_price = 0` by construction), so it
is computed once and reused across frontier points instead of re-run per `OUT_TAG`. The key is
`foresight_test`, not `ceiling_test`: an under-converged oracle biases it *down*, so a policy
can legitimately exceed it.

~~Measured 2026-08-06: +836 ± 68 $/ha.~~ Superseded — naive SE, and pre-reconciliation.
**Current, verified on disk 2026-08-28 18:34** (`runs/exp1_ceiling.json`): `gate_pass: true`,
`foresight_test` **+721.5 $/ha**, `se_ess` 278.8, `ci95_boot` [502.9, 999.1], `ci95_ess`
[175.0, 1268.0], n = 5, ESS 1.25. Per-window: 1191.8 / 455.8 / 539.8 / 531.6 / 888.6. The point
estimate and the bootstrap interval clear the 250 noise floor; the ESS interval's lower bound
(175) does not, so quote the interval.

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

`--max-n` has no default and must be passed explicitly. Exp 1 runs **uncapped**, so Exp 2 needs
`--max-n none` to be comparable with it (hard rule 2).

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
2. Then Node A: Exp 2 seeds 0/1/2

With two experiments the frontier points, not the levers, are what parallelise: one node per
`NO3_PRICE`/`OUT_TAG` pair (hard rule 1 wants the whole sweep, not one point).

## Gate checklist before full runs

- [ ] `uv run python scripts/check_param_state.py` PASS — the model's crop parameters are the
      collaborator's workbook (rule 11b) and no fit has silently reverted them
- [ ] `uv run pytest` green
- [ ] `uv run pytest -m slow` — monthly default irrigation within 1% of 3,938.8 mm
- [ ] `assert_no_leakage()` passes (import `swat_gym.windows`)
- [ ] `exp1_ceiling` written; if `gate_pass` false, skip PPO
- [ ] Water price sourced or breakeven reported (re-optimize under sweep when sourced)
- [ ] **`--max-n` passed explicitly and identical across the two experiments being compared.**
      Exp 1 is uncapped, so Exp 2 needs `--max-n none`. The runners refuse to start without the
      flag, and it is recorded in every artefact.
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

## Retired modules (recover from git history if ever needed)

The tree now holds only modules that are live for the paper. **Why a module was retired matters
more than the fact that it was** — the reasons below are not equivalent, and restoring a module
without checking which applies is how a leaky result gets back into the paper.

### Cut for scope, 2026-09-09 — correct when removed, safe to restore verbatim

`src/swat_gym/experiments/exp3_rotation.py` (rotation enumeration; per-sequence separable train
terms and the exact `no3_frontier` re-selection) and `src/swat_gym/experiments/exp4_joint.py`
(joint search warm-started from Exp 2/3, with the `_check_world` guard on `max_n`/`no3_price`).

**Nothing was wrong with them.** Both were tested and both carried the 2026-08-28 methodology
fixes. They were cut because the paper was reduced to two levers:

- Rotation is the lever the rule 11b crop bias most compromises — alfalfa **+49.2 %**, corn
  **−12.1 %** (refit 2026-09-10; was +49.5 / −24.6), alfalfa three of seven rotation years — the
  alfalfa half, which is the half that drives this, is unchanged — so any comparison shifting area between
  alfalfa and the annuals reads a biased price ratio. Fixing the rotation makes that bias
  **common-mode** across arms instead of differential.
- Four experiments on five test windows at **ESS 1.25** is a multiple-comparisons problem, not
  four times the evidence.
- Neither claimed contribution (the environment; the search-vs-adaptation protocol) depends on
  them — Exp 1 demonstrates the protocol in full and Exp 2 shows it is not irrigation-specific.

Hard rule 8 (joint < composed ⇒ optimizer failure) was retired with them and is tombstoned in
`CLAUDE.md` rather than renumbered. If the scope is ever widened, restore the modules **and**
rule 8 together.

### Deleted 2026-08-07

Everything below was removed in one pass; git history is the archive.

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
