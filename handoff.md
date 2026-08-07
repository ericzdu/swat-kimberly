# Handoff: SWAT+ 62 model → instgpu experiments

Two phases, in order. **Do not start full cluster Exp 1–4 until Phase 1 is closed** (baseline credible vs GRACEnet, gates green on both Mac and Linux).

| | |
|---|---|
| Repo | `/Users/ericdu/Desktop/projects/swat-kimberly` (local) → `edu@instgpu-0X.cs.wisc.edu:~/swat-kimberly` |
| NetID | `edu` |
| Nodes | `instgpu-01` … `instgpu-05` (CPU-bound; GPUs idle) |
| Engine | **SWAT+ rev 62.0.0** — Mac Mach-O `swatplus_rev62.0.0`, Linux ELF `swatplus_62.0.0.linux` |
| Retired | `swatplus_rev60.5.7.bak` (do not use for new runs) |
| Design | Monthly adaptivity pivot — see `CLAUDE.md` / `EXPERIMENTS.md` |

---

## Phase 1 — Finish changing the SWAT model (local Mac)

### Already done (2026-07-31)

1. **Engine upgrade** 60.5.7 → 62.0.0; `find_engine` prefers native rev-62, ignores `*.bak` / wrong-OS siblings.
2. **`plants.plt` format fix (load-bearing):**
   - Rev 62 reads `days_mat` / `yrs_mat` as **Fortran integers**.
   - Values like `120.00000` are mis-parsed by gfortran list-directed I/O and **shift every later column** on that row → fake temperature stress, collapsed yields (~3.5 t/ha corn).
   - Fix: write integers (`120`, `0`) and add `avg_lig_frac` / `ab_lig_frac` / `bg_lig_frac`.
   - `swat_gym.params.set_value` now keeps those columns integer-formatted (`test_params.py`).
3. ~~**Drainage signal:** `pet_co` 1.0 → 0.81 as a provisional restore.~~ **Superseded** — see the reconciliation pass below. Old `alfa.lai_min` drainage trade is **inert** under 62.
4. Baseline fixture regenerated (`scripts/rebaseline.py`). Local: **`uv run pytest` → 119 passed**.
5. Docs touched: `PAPER.md`, `README.md`, `CLAUDE.md`, `OPEN_ITEMS.md` #10.

### Reconciliation pass (2026-07-31, later the same day)

6. **Inputs re-audited against REF HRU `000140001`** — `scripts/port_reference_params.py`
   (new, idempotent). Sixteen parameters that no port had ever claimed were still A10
   template defaults: `CN2` 81→**75**, `OV_N` 0.19→**0.14**, `USLE_P` 0.75→**1.00**, the snow
   block (`SMFMN` was off by 45×), the entire `000140001.gw` groundwater block, the
   `basins.bsn` phosphorus block, and `SDNCO`/`SPCON`/`SPEXP`/`CN_FROZ`/`SOL_P_MODEL`.
   Full table and the mapping notes: **PROVENANCE §5g**.
   Effect on fit: essentially none (yield −5.9 % → −6.7 % vs GRACEnet). It buys audit
   completeness, not accuracy.
7. **`pet_co` calibrated, not guessed** — `scripts/calibrate_petco.py` (new). Target is the
   AgriMet TWFI **grass**-reference ET series (`ETOS`), the definition SWAT+ PET matches.
   PET is exactly linear in `pet_co`, so the optimum is closed-form: **`pet_co = 0.964`**,
   PET bias **+0.0 %**. The incumbent 0.81 was −16.0 %. **PROVENANCE §5h.**
8. **The finding that matters.** At the PET-matched value, percolation is ~1 mm/yr against
   the reference's 72, and `no3_rchg` ~0.02 kg/ha/yr. `perco` is inert across its full range;
   `esco`, `epco` and the soil profile all already match REF. So the model's ET/PET ratio
   (~0.86 vs the reference's ~0.51) is an **engine difference**, rev 62 vs SWAT2012 rev 693 —
   not an input error. It is `OPEN_ITEMS.md` **#11** and it gates Exp 2's leaching column.

### Calibration to measurement (2026-07-31, later still)

9. **A seventh measured target was found and wired in** — `GraceNet Soil and Nutrient
   Properties.xlsx::Soil N & P` holds a **seven-year April soil-nitrate profile on this field**
   (4 plots × 5 depths, 2013–2019). Only its 2013 column had been used. Now extracted
   (`data/soil_no3_gracenet.csv`) and scored (`scripts/n_trajectory.py`). It is the only
   measured constraint on the N cycle here. **PROVENANCE §5i.**
   Rev 62 prints no soil nitrate pool — checked across all ~24 output tables and the whole
   `hru_cb_*` family — so the model side is a mass balance that *brackets* the one unreported
   term (applied ammonium) rather than assuming it.
10. **The model is now calibrated to the GRACEnet measurements** —
    `scripts/calibrate/optimize.py`, 15,616 evaluations, applied. Objective is **per-year**
    yield error over all seven years plus the nitrate trajectory, PET held as a bound.
    Yield RMS per-year **25.5 % → 13.6 %**, PBIAS −9.8 % → **−3.0 %**, PET unchanged at +0.0 %.
    Per crop: corn −7.0, alfalfa +2.2, barley −4.9. **PROVENANCE §6.**
11. **Three knobs turned out to be dead**, which matters for how bound-pinning is read.
    `plants.plt:harv_idx` is inert for this whole rotation — the engine reads the harvest index
    from `harv.ops` (`gn_corn`/`gn_barl`/`gn_alfa`) — and so are `latq_co` and (near enough)
    `cn3_swf`. A first fit had parked `corn.harv_idx` against a bound where it looked like a
    meaningful pin. **PROVENANCE §5j.**

### Still to do before calling the model “done”

1. **Decide #11 — but the choice is now narrower.** The measured nitrate trajectory confirms
   the leaching column cannot be rescued by refitting the nitrogen cycle: SWAT makes soil
   nitrate and legume fixation strict substitutes, so the measured pool rise under alfalfa is
   unreachable at any parameter setting (PROVENANCE §5i). Remaining unexamined ET levers are
   `soil_plant.ini:sw_frac = 0.0` and the rev-62 plant-community ET code path — `cn3_swf` and
   `latq_co` have since been swept and are inert. Otherwise state in the paper that leaching is
   unresolvable here under rev 62. Do **not** re-absorb it into `pet_co`.
1a. **Re-run the stage-1 ceiling gate before starting Exp 1.** `runs/exp1_ceiling.json` currently
   holds **+481 $/ha test** (train +653), which passed the 250 $/ha noise floor — but that was
   measured on the **pre-calibration** model. Calibration moved corn +3.9 and alfalfa +15.1
   points, i.e. it changed the relative price between the crops the rotation lever chooses
   among, which is exactly what the ceiling measures. Treat +481 as stale:
   ```bash
   uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000   # ~60 min
   ```
   A partial re-run after calibration reached shared test 21023 against per-window oracles of
   ~22300, so the gap looks at least as wide as before — but it was stopped before it reported.
1b. **Two honest caveats to carry into the manuscript.** `corn.bm_e` is fitted to 64.5 against
   a literature ~39–45 and is absorbing the resident-perennial artefact, so corn's agreement is
   fitted rather than validated; and barley is still ±24 % year-to-year even though its
   per-crop bias reads −4.9 %.
2. If recalibrating further: use `scripts/calibrate/` + `params.set_value`; **never** write
   `days_mat` as `*.5f` floats.
3. Re-run gates after any input change:
   ```bash
   uv run pytest
   uv run pytest -m slow          # monthly irr within 1% of 3,938.8 mm
   uv run python scripts/rebaseline.py --why "…"
   uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000
   ```
4. Commit the Phase 1 tree (model inputs, engines, fixture, code). There is **no git remote** yet — sync to cluster is rsync/scp until a remote exists.

### Do not reopen without cause

- Monthly experiment design (Exp 1–4, train 1995–2004 / test 2013–2017).
- Protocol: freeze on train, matched engine-run budgets, no leach term inside reward.
- Barley remains `warm_annual` (60.5.7 cold-annual phenology bug; still the shipped choice).

---

## Phase 2 — Get it working on instgpu

Only after Phase 1 gates are green locally.

### 2a. Sync code + Linux engine

```bash
# from laptop — example node; repeat or rsync once then hop nodes
rsync -avz --exclude '.venv' --exclude 'runs/' --exclude '__pycache__' \
  /Users/ericdu/Desktop/projects/swat-kimberly/ \
  edu@instgpu-04.cs.wisc.edu:~/swat-kimberly/
```

Confirm on the node:

```bash
ssh edu@instgpu-04.cs.wisc.edu
cd ~/swat-kimberly
file model/TxtInOut/swatplus_62.0.0.linux   # must be ELF x86-64
# Mach-O Mac binary must NOT be the one find_engine picks on Linux
uv sync --extra dev
uv run python -c "from swat_gym.engine import find_engine; from swat_gym.fastrunner import TXTINOUT; print(find_engine(TXTINOUT))"
# expect: .../swatplus_62.0.0.linux
```

### 2b. Linux parity gate (must match Mac science, not Mac binary)

```bash
uv run pytest
uv run pytest -m slow
uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000
```

- Fixture was cut on **Mac arm64**. A Linux yield mismatch is **build disagreement**, not a flaky test — see `baseline.json` provenance. If ELF ≠ Mac within tolerance, stop and diagnose before PPO.
- Irrigation nesting must still hit measured **3,938.8 mm** within 1%.

### 2c. Smoke then production map

Workload is **CPU-bound**; use `SubprocVecEnv` workers (8–16), one experiment/seed per node, `tmux`, outputs under `runs/exp{N}_*`.

```bash
# smoke
uv run python -m swat_gym.experiments.exp1_ceiling --budget 5000
uv run python -m swat_gym.experiments.exp1_controller --budget 5000

# production (after ceiling gate_pass)
uv run python -m swat_gym.experiments.exp1_irrigation --budget 300000 --ppo-seeds 3
uv run python -m swat_gym.experiments.exp2_nitrogen --budget 300000
uv run python -m swat_gym.experiments.exp3_rotation
uv run python -m swat_gym.experiments.exp4_joint --budget 300000 --ppo-seeds 3
```

Suggested node map (from `EXPERIMENTS.md`): Exp 1 seeds on one node → Exp 2 / Exp 3 in parallel → Exp 4.

`--budget` = matched **engine runs** (PPO timesteps; CMA evals = budget / n_train_windows).

---

## Gotchas (read once)

| Symptom | Cause | Fix |
|---|---|---|
| Corn ~3–5 t/ha, huge `strstmp` | `days_mat` written as `120.00000` | Integer token; use `set_value` |
| `no3_rchg ≈ 0`, leach tests uninformative | ET/PET ratio under 62, **not** PET level | Known and open — `OPEN_ITEMS` #11. Do **not** "fix" it with `pet_co`; that was tried and it costs 16 % PET bias against measurement |
| pySWATPlus “multiple executables” | Mac + Linux + `.bak` in TxtInOut | `runner.py` keeps native family only |
| Cluster picks Mac binary / won’t run | Wrong OS binary | Only ELF on Linux; `find_engine` |
| Staying on 60.5.7 “because calibrated” | Rejected — 2.3/60.5.7 too old | Stay on 62 |

---

## Pointers

- Agent entry: `CLAUDE.md`
- Runbook: `EXPERIMENTS.md`
- Pre-submission: `OPEN_ITEMS.md` (esp. #9 cluster, #10 rev-62 bias)
- Manuscript: `PAPER.md` (methods say rev 62.0.0)
- Regenerate fixture: `uv run python scripts/rebaseline.py --why "…"`
