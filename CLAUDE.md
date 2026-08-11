# swat-kimberly — agent entrypoint (Claude Code / Cursor)

## Goal

Calibrated SWAT+ field environment (Kimberly, ID) for management optimisation.

**Final goal:** determine whether a learned policy can maximise farm **profit** without paying for
it in water and nitrate. Profit is the objective the reward maximises; **sustainability is the
second objective**. The levers are taken in order — irrigation (Exp 1), fertiliser (Exp 2),
rotation (Exp 3), then all three jointly (Exp 4).

Revised 2026-08-10 (was "co-equal objectives"). What changed is the **framing only**: profit now
leads the headline. What did **not** change is how the sustainability claim is settled — because no
defensible market price exists for nitrate leaching in Idaho, it is settled by a **profit–leaching
frontier**, never by a blended scalar. The deliverable is still the whole swept-λ_n curve, and the
claim is still *dominance* — at matched profit, which strategy leaches less. Hard rule 1 below
still enforces that; it is a constraint on method, not on framing.

The paper's methodological contributions serve that goal: the **environment** (first Gymnasium env
on the official SWAT+ engine) and an **evaluation protocol that separates optimizer search from
state-dependent adaptation** — without which "the policy is greener" cannot be distinguished from
"the policy was searched harder".

**Two limits bound every sustainability claim and must appear wherever one is made:** leaching is
unvalidated on site (rule 10), and SWAT+ cannot simulate N₂O at all — it is IPCC Tier 1 accounting,
reported and never priced (rule 1). Optimising *for* an unvalidated channel is exactly the regime
in which model error gets exploited invisibly; treating sustainability as a real second objective
raises the stakes on that caveat rather than relieving them.

## Locked experimental design

| Exp | Lever | How | Module |
|---|---|---|---|
| 1 | Irrigation | Monthly Apr–Sep; CMA open-loop + feedback controller + PPO + frozen | `exp1_irrigation` (+ `exp1_ceiling`, `exp1_controller`) |
| 2 | Nitrogen | Manure + mineral under one cap | `exp2_nitrogen` |
| 3 | Rotation | **Enumerate** feasible sequences (no CMA/PPO) | `exp3_rotation` |
| 4 | Joint | Warm-start from 1–3; joint < composed ⇒ optimizer, not interaction | `exp4_joint` |

**Run order = paper order:** gate → ceiling → controller → Exp 1 → 2 → 3 → 4.

## Hard rules

1. **Neither externality may enter the reward at a single fixed price.** Both water and nitrate
   enter only as **swept λ whose whole frontier is reported**, with the market-price arm
   (λ_w = scored water price, λ_n = 0) always alongside.
   Publishing one interior point of a sweep as "the" answer is the failure this rule prevents.
   N₂O is IPCC Tier 1 accounting: **reported, never priced** — it is R² = 1.000 linear in applied
   N, so pricing it is a fertiliser surcharge, not a second objective. Prefer **dominance**
   claims ("at matched profit, X uses less water"), which need no price at all.
   λ_w and λ_n are **not independent** here: leaching responds to over-irrigation, not to
   fertiliser. Say so rather than presenting two orthogonal axes.
2. Match PPO and CMA budgets in **engine runs**, not native units — *and verify the two
   optimise the same objective*. Constraints here are enforced by **repair**, so a cap applied
   on one code path and not another changes what is simulated without changing what is priced,
   and is invisible in the reward. `tests/test_monthly.py::test_openloop_and_policy_paths_agree_
   on_identical_plan` pins this; `max_n` has **no default** on the experiment-level scorers. This
   inverted Exp 1's headline once (PPO −995 reported as +377) — see the memory note.
3. Never report a single PPO seed as the Exp 1 / Exp 4 headline (`--ppo-seeds ≥ 3`).
4. Observation must **not** contain future weather (no oracle forecast).
5. Validate generated baseline irrigation vs measured (3,938.8 mm) within **1 %** before scoring arms.
6. Frozen plans are selected on **train**, scored on **test** (never argmax on test).
7. Train/test windows share **zero** calendar years (`swat_gym.windows`). They *do* overlap
   each other, so report bootstrap intervals and the effective sample size (≈1.5), never a naive
   SE over windows.
8. If Exp 4 joint < composed single-lever optima → optimizer failure, not a science claim.
9. Every module left in `experiments/` is live for the paper — the superseded ones were **deleted**
   2026-08-07 (`EXPERIMENTS.md` lists them and why). Do not restore one from history to answer a
   new question without first checking what it was retired *for*: `exp2_rl.py`/`exp2b_controls.py`
   declared their own pre-`windows` split (1995–2011 / 2012–2018, seven shared years) and never
   called `assert_no_leakage()`. Every live experiment imports `TRAIN_YEARS`/`TEST_YEARS` from
   `swat_gym.windows`; a new experiment must do the same, never redeclare them.
   `runs/exp1b_price_ratio.json` and `runs/exp1c_cadence_e500.json` outlive their generating
   modules and are still cited in `rewarders.py`/`env.py` — `runs/` is gitignored, so those two
   files are unrecoverable. Do not clear them.
10. `pet_co` is **calibrated to measured AgriMet grass-reference ETos** (0.964). Do not retune
    it. **There is no "drainage collapse" to rescue** — re-measured 2026-08-06
    (`scripts/percolation_check.py`), percolation is *threshold-behaved in applied water*: ~0
    below crop demand, then 9 → 162 mm/yr from 3,939 → 5,778 mm applied, at a plausible
    13.6–26.5 mg/L. Leaching remains **unvalidated on site**, so magnitudes are within-model
    only (PROVENANCE §5h, `OPEN_ITEMS` #11).
11. Where REF and a GRACEnet primary measurement disagree, **the measurement wins** — initial
    soil nitrate/labile P, bulk density, 2014/2019 irrigation (PROVENANCE §5g).
11b. **Crop coefficients are the collaborator's workbook values and are NOT ours to fit.**
    Decided 2026-08-07. `bm_e`, `harv_idx`, `lai_pot`, the canopy curve, `rt_dp_max` and the
    temperature pair for corn/barl/alfa come from `Crop Parameters and Plant Harvest dates.xlsx`
    exactly, and the `gn_*` harvest indices are its `HARV_EFF` (0.98 / 0.54 / 0.95). Do **not**
    let `calibrate/optimize.py` move them back — exclude them from the free-parameter set, or
    re-apply the workbook after any `--apply`. Rationale, measured: fitting bought only 2.3
    points of mean |PBIAS| (37.1 % → 34.8 %) and paid for it by making every alfalfa year
    14–17 points *worse*, which is rule 13's incentive showing up as a bad trade. The fitted
    `corn.bm_e` = 64.5 also absorbed the resident-perennial artefact, so it hid a structural
    error inside a parameter instead of leaving it visible. Book values keep the bias legible.
    Domain ownership sits with the collaborator; we own the protocol, not the agronomy.
12. **Parameter values calibrated in SWAT2012 do not transfer to rev 62.** `orgn_min = 0.001`
    was borrowed from a site sweep that hit the measured mineralisation rate to +4.7 % *in
    SWAT2012*; the same value here gives 54.4 kg N/ha/yr against 209.8 measured. Re-fit against
    the measurement, never carry the number across (PROVENANCE §5e, §5i).
13. Do **not** chase the alfalfa soil-nitrate years. SWAT computes legume fixation as the
    soil-supply shortfall, so nitrate and fixation are strict substitutes and the measured pool
    rise under alfalfa is unreachable at any parameter setting (PROVENANCE §5i). The nitrate
    term is down-weighted for that reason; do not re-raise the weight to "fix" it.

## Staged build (do not skip)

1. Protocol fixes + monthly open-loop (`monthly.py`) + monthly `print.prt` outputs
2. `exp1_ceiling` — foresight *estimate*, not a ceiling (a policy can exceed an
   under-converged oracle). If ≤ ~$250/ha noise floor, skip cluster PPO; write bounded null.
   Measured 2026-08-06: **+836 ± 68 $/ha**, so there is real weather-specific value here
3. `exp1_controller` — CMA feedback row
4. Monthly gym (`monthly_env.py`) + Exp 1 PPO
5. Exp 2 → 3 → 4

## Pointers

- Runbook: [`EXPERIMENTS.md`](EXPERIMENTS.md)
- Manuscript: [`PAPER.md`](PAPER.md)
- Pre-submission gaps: [`OPEN_ITEMS.md`](OPEN_ITEMS.md)
- Input provenance: [`PROVENANCE.md`](PROVENANCE.md)

## Cluster (`instgpu-01` … `05`)

SWAT+ is **CPU-bound**. Use CPU cores + `SubprocVecEnv`, not GPUs. Need the Linux ELF
engine (`model/TxtInOut/swatplus_62.0.0.linux`); Mac Mach-O will not run. Prefer one
experiment/seed per node. Engine revision is **62.0.0** (not 60.5.7).

## Quick commands

```bash
uv sync --extra dev
uv run pytest
uv run pytest -m slow          # includes monthly nesting gate vs measured mm

# Model inputs (idempotent; re-run after any SWAT+ editor round-trip)
uv run python scripts/port_reference_params.py    # REF HRU 000140001 -> CN2, OV_N, snow, .gw, P block
uv run python scripts/calibrate_petco.py --apply  # fit pet_co to measured AgriMet ETos
uv run python scripts/compare_reference.py        # yields/irr/ET vs REF and GRACEnet
uv run python scripts/calib_report.py             # tiered scorecard, tier 1 = measured
uv run python scripts/n_trajectory.py             # measured April soil-NO3 vs mass balance

# Fit to the GRACEnet measurements (yield per-year + soil nitrate; PET is a bound)
uv run python scripts/calibrate/optimize.py --maxiter 80          # report only
uv run python scripts/calibrate/optimize.py --maxiter 80 --apply  # then rebaseline + gate

uv run python scripts/percolation_check.py       # is the leaching column usable at all?
uv run python scripts/paper_tables.py            # regenerates PAPER.md Tables 2-5 from runs/*.json
uv run python scripts/exp1_strategy_table.py     # per-strategy profit/yield/water/leaching table

# Stage 1 gate
uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000
uv run python -m swat_gym.experiments.exp1_controller --budget 2200   # 3 params; converges ~220

# Full Exp 1 pipeline, detached (harness reaps process groups at ~30 min)
perl -e 'use POSIX; setsid(); exec @ARGV' -- bash scripts/rerun_exp1.sh
NO3_PRICE=16 OUT_TAG=n16 bash scripts/rerun_exp1.sh    # a frontier point

# Exp 1 (after ceiling passes)
uv run python -m swat_gym.experiments.exp1_irrigation --budget 300000 --ppo-seeds 3

# Exp 2–4
uv run python -m swat_gym.experiments.exp2_nitrogen --budget 300000
uv run python -m swat_gym.experiments.exp3_rotation
uv run python -m swat_gym.experiments.exp4_joint --budget 300000 --ppo-seeds 3
```
