# `swat-gym` — experiment runbook

Agent entrypoint: [`CLAUDE.md`](CLAUDE.md). Code: `src/swat_gym/`. The agent controls irrigation
and manure/N; the rotation is fixed (not a lever since 2026-09-09).

## Execution order (= paper order)

```
pytest → exp1_ceiling → exp1_controller → exp1_grower_rule → exp1_irrigation → exp2_nitrogen
```

- Skip PPO if `exp1_ceiling` reports `gate_pass: false`. `rerun_exp1.sh` exits 2 in that case
  (`FORCE_PPO=1` overrides).
- The gate is λ_n-independent, so it is computed once and reused across frontier points.
- Current gate: see CLAUDE.md "Status" (+360.8 $/ha, ESS CI [220, 502]).

## Rows

| Row | Meaning |
|---|---|
| `measured` | shipped `management.sch` (2013–19 log) replayed verbatim on each window |
| `grower` | controller (a, b, c) fitted to logged monthly depths; responds to weather |
| `default` | `DEFAULT_PLAN` through the same generator (quote lever gains vs this) |
| `fixed` | CMA-ES open-loop (monthly for Exp 1) |
| `policy` | PPO |
| `frozen` | policy's plan, selected on train, replayed on test |

Exp 1 extras: `ceiling` (per-window foresight) and `controller` (CMA feedback rule).

`grower` is fitted on 2013–19 weather (overlaps test years), never on profit, gated at 1 % of
3,938.8 mm. It is a reference row, not a learned arm. Exp 2 re-scores the same fit, so
`runs/exp1_grower_rule.json` must exist first.

## Commands

### Exp 1 — irrigation (monthly)

```bash
uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000
uv run python -m swat_gym.experiments.exp1_controller --budget 2200
uv run python -m swat_gym.experiments.exp1_grower_rule --evals 220
uv run python -m swat_gym.experiments.exp1_irrigation --budget 300000 --ppo-seeds 3
uv run python -m swat_gym.experiments.exp1_irrigation --budget 300000 --skip-ppo  # failed gate
# or all of it, detached, with the objective-parity preflight:
perl -e 'use POSIX; setsid(); exec @ARGV' -- bash scripts/rerun_exp1.sh
```

Outputs: `runs/exp1_{ceiling,controller,grower_rule,irrigation}.json`.

### Exp 2 — nitrogen

```bash
uv run python -m swat_gym.experiments.exp2_nitrogen --budget 300000 --max-n none --ppo-seeds 3
```

Output: `runs/exp2_nitrogen.json`. `--max-n` is required; use `none` to match uncapped Exp 1.

## Windows (`src/swat_gym/windows.py`)

Train starts 1995–2004 (10 windows, end ≤ 2011). Test starts 2013–2017 (5 windows). Zero shared
calendar years; 2012 is a buffer.

## Cluster (`instgpu-01`…`05`)

CPU-bound; Linux ELF engine; 8–16 `SubprocVecEnv` workers; one seed/experiment per node; `tmux`,
write under `runs/`. Parallelise over frontier points: one node per `NO3_PRICE`/`OUT_TAG`.

## Checklist before full runs

- [ ] `scripts/check_param_state.py` passes (rule 11b)
- [ ] `uv run pytest` and `uv run pytest -m slow` pass (irrigation within 1 % of 3,938.8 mm)
- [ ] `assert_no_leakage()` passes
- [ ] `exp1_ceiling` written; skip PPO if `gate_pass` is false
- [ ] Water price sourced, or breakeven reported
- [ ] `--max-n` explicit and identical across compared experiments (Exp 2: `none`)
- [ ] Intervals quoted as `se_ess`; differences under a few hundred $/ha are not resolvable
- [ ] Full λ_n frontier produced (one `rerun_exp1.sh` call = one point)
- [ ] Leaching column non-degenerate (zero at measured practice; only over-irrigation separates
      arms). If arms don't separate, report that
- [ ] Sustainability claims state: leaching unvalidated on site; N₂O is Tier 1, unpriced

## Retired modules (recover from git history)

- **Cut for scope, 2026-09-09 (correct; safe to restore):** `exp3_rotation.py`,
  `exp4_joint.py`. Restore rule 8 with them.
- **Leaky split, 2026-08-07 (re-point to `swat_gym.windows` before restoring):**
  `exp2_rl.py`, `exp2b_controls.py`, `scripts/run_overnight.sh`.
- **Superseded, 2026-08-07:** `exp1_ablation.py`, `exp1_nitrogen.py`, `exp2_irrigation.py`,
  `scripts/n_response.py`, `scripts/exp1_weekly.py`, `src/swat_gym/weekly.py`,
  `scripts/port_solar.py`, `scripts/port_weather.py`.
- **Retired sweeps with live results:** `exp1b_price_ratio.py`, `exp1c_cadence.py`. Their
  outputs `runs/exp1b_price_ratio.json` and `runs/exp1c_cadence_e500.json` are git-tracked and
  cited in code; keep them.

## Engine cost

| Cadence | Steps/episode | Cost |
|---|---|---|
| Open-loop | 1 | 0.17 s |
| Annual | 7 | ~1.5 s |
| Monthly | 42 | ~7 s |
| Weekly | ~230 | ~40 s (infeasible) |
