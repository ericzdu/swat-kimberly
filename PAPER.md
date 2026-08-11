# Profit and nitrate together: a reinforcement-learning environment on official SWAT+, and a protocol for telling search from adaptation

Eric Du *[co-authors and affiliations to confirm]*

---

## Abstract

Southern Idaho's irrigated forage systems face simultaneous pressure on water and nitrogen.
Precipitation at Kimberly falls far below potential evapotranspiration, so nearly all crop water is
applied, while dairy manure supplies cheap nitrogen and raises nitrate concern in groundwater. The
two decisions couple through percolation: an irrigation schedule is also a leaching schedule.
Whether a *learned* policy manages that coupling better than a well-searched fixed schedule is
unsettled, because the comparisons that exist run against weak baselines, without matched search
effort, and against single-objective rewards that make resource use invisible. We present a
Gymnasium environment driven by official SWAT+ rev 62.0.0 on practitioner text inputs and a
measured field — to our knowledge the first RL-capable stack that wraps the SWAT+ engine itself
rather than a crop-only model or a Python reimplementation inspired by classic SWAT. Around it we
specify an evaluation protocol whose purpose is to separate what an optimizer *searched* from what
a policy *adapted* to: engine-run budgets matched across methods, verified objective parity between
those methods, weather windows sharing no calendar years with training, a perfect-foresight
reference, a parametric feedback controller as a third policy class, and plans frozen from a
learned policy as a control on whether it conditions on state at all. **The optimized objective is
farm profit; sustainability is the second objective and is settled without pricing it.** Because no
defensible market price for nitrate leaching exists in Idaho, we never fold it into a scalar at a
fixed price: instead every strategy is re-scored across a swept nitrate price λ_n — exact
arithmetic on stored cost terms, requiring no further simulation — and the **profit–leaching
frontier** is reported whole, with the profit-only arm (λ_n = 0) always alongside. The
sustainability claim this supports is *dominance at matched profit* — which strategy leaches less,
and uses less water, for the same money — which needs no price at all. Applied water is reported
with its breakeven price.
*[TODO: headline finding — where each method's frontier lies, whether the learned policy dominates
matched-budget open-loop search across λ_n or only within part of the range; from the corrected
`runs/exp1_*.json`.]*
Weather-specific scheduling is worth +836 ± 68 $ ha⁻¹ at this site, so a null result for
closed-loop control cannot be attributed to there being nothing to adapt to. Calibration bounds
what may be read from the ranking: signed, crop-specific yield bias makes within-crop levers more
interpretable than rotation, and while the model's percolation pathway responds correctly to
applied water, it is unvalidated on site, so leaching ranks strategies within the model and is not
a field claim.

**Keywords:** SWAT+; reinforcement learning; irrigation; nitrogen; nitrate leaching; multi-objective
optimization; sustainable intensification; evaluation protocol; CMA-ES; dairy-forage systems

---

## 1. Introduction

Southern Idaho's irrigated forage systems face simultaneous pressure on water and nitrogen. At
Kimberly, precipitation is far below potential evapotranspiration, so nearly all crop water is
applied, while dairy manure supplies cheap nitrogen and elevates nitrate concern in groundwater.
The two decisions couple through percolation: an irrigation schedule is also a leaching schedule.
Models without hydrological transport cannot represent that coupling.

What managers need is a strategy that performs well — higher profit where the model is
trustworthy, with resource use and leaching visible — whether that strategy is a fixed calendar, a
simple feedback rule, or a learned policy. Fixed calendars are easy to implement; state-dependent
rules and reinforcement learning can in principle respond to mid-season conditions.

Two problems make the existing evidence hard to read. First, **baselines are rarely matched**. A
learned policy compared against a default schedule, or against a search given a fraction of the
compute, will win for reasons that have nothing to do with adaptation. Establishing that a policy
adapts requires a baseline that has been searched as hard as the policy was trained, on *the same
objective* — and objective parity between two code paths is a property to be tested, not assumed.
Second, **the objective is usually single-valued**. A profit-only reward makes water and nitrate
invisible to the optimizer, so a policy can post a headline gain while applying more water and
leaching more nitrogen than the practice it replaces. Whether such a policy is an improvement
depends entirely on prices the study did not state.

We therefore treat the *protocol* as a first-class contribution rather than housekeeping, and
report the resource consequences of every strategy alongside its profit.

**Contributions.**

1. **A Gymnasium environment driven by official SWAT+ rev 62.0.0** on practitioner `TxtInOut`
   inputs and a measured field — to our knowledge the first. Strategies act through the same text
   management files and the same native water and nitrate routing used in field studies.
2. **An evaluation protocol that separates search from adaptation**: budgets matched in engine
   runs rather than native units, verified objective parity across methods, year-disjoint weather
   windows, a perfect-foresight reference, a parametric feedback controller as a third policy
   class, and train-selected frozen plans as a control on state-dependence.
3. **Profit as the optimized objective, sustainability as a second objective settled by a
   frontier rather than a price.** Profit is what the reward maximizes and what the headline
   reports. Nitrate and water are not annotations beneath it: each strategy is re-scored across a
   swept λ_n and the whole profit–leaching frontier is published, with the profit-only arm always
   alongside, so no sustainability conclusion depends on a shadow price we would have to defend.
   Where a method's frontier lies wholly inside another's, that is a dominance result; where the
   frontiers cross, we report the crossing rather than choosing the λ_n that favours our preferred
   arm.
4. **A calibration statement that treats per-crop bias, and an unvalidated percolation pathway, as
   bounds on interpretation** rather than as caveats appended to a conclusion.

---

## 2. Related work

**Agricultural RL.** CropGym, gym-DSSAT, CyclesGym, WOFOSTGym and related environments wrap
process-based crop models for sequential management (Overweg et al., 2021; Gautron et al., 2022;
Turchetta et al., 2022). Most emphasize crop physiology; hydrological nitrate transport is often
missing or crude. The literature applying RL to agricultural simulators remains small — on the
order of a dozen papers — so strong claims about when closed-loop policies beat fixed schedules are
not yet well supported. Most report a single scalar reward, usually profit or yield, with resource
use reported after the fact if at all.

**SWATgym and SWAT+.** Madondo et al. (2023) introduced SWATgym, an OpenAI Gym environment for
joint fertilizer and irrigation management whose dynamics are a Python reimplementation modeled
after classic SWAT (Arnold et al., 2012) — not the shipped Fortran executable or a practitioner
`TxtInOut` tree. SWATgym established that SWAT-style hydrology–crop coupling is a useful RL
testbed; our contribution is complementary: wrap **official SWAT+** rev 62.0.0 so strategies act
through the same text inputs and the engine's own water and nitrate routing. We are not aware of a
prior Gymnasium environment driven by the SWAT+ engine (Table A).

**Table A.** Crop-management RL environments (selected).

| Environment | Dynamics engine | Fertilizer / N | Irrigation | Hydrologic N routing |
|---|---|---|---|---|
| CropGym (Overweg et al., 2021) | WOFOST / PCSE | ✓ | — | limited |
| gym-DSSAT (Gautron et al., 2022) | DSSAT | ✓ | ✓ | crop-centric |
| CyclesGym (Turchetta et al., 2022) | Cycles | ✓ | ✓ | limited |
| SWATgym (Madondo et al., 2023) | Python reimplementation modeled after classic SWAT | ✓ | ✓ | as reimplemented |
| **This work** | **Official SWAT+ rev 62.0.0** (`TxtInOut`) | ✓ | ✓ | **present in engine** (validation bounded, §5.2) |

Table A states that routing is *present in the engine*, not that it is validated at this site; §5.2
and §6.5 give the bound.

**Comparison protocol.** Agricultural optimization and ML papers often report gains over weak
baselines without equalizing search effort or publishing the full candidate set. Frozen plans — a
policy's train-selected schedule replayed without further conditioning — appear occasionally as a
diagnostic. We treat them as an object of study: a frozen plan is only a valid measure of
adaptation if it is also a *well-searched* schedule, and §4 explains why it usually is not.

---

## 3. Reinforcement-learning formulation

Constants below are the values used in the released code.

### 3.1 Decision problem

Management is a finite-horizon, undiscounted Markov decision process. An episode covers a
seven-year rotation preceded by one spin-up year that `print.prt`'s `nyskip` discards, so a window
spans eight calendar years. A step is one growing-season month, April–September, giving
**42 steps per episode** (7 years × 6 months). The discount factor is **γ = 1**: the objective is
total rotation profit over a fixed horizon, so discounting would distort it.

SWAT+ has no checkpoint-restart. A step therefore **re-runs the entire eight-year simulation** with
every operation decided so far, and reads the state of the month just simulated. One episode costs
**42 engine runs**. This is the single most consequential implementation fact in the paper: it is
what makes budget matching meaningful across methods that otherwise count effort in incompatible
units, and it is what makes evaluation expensive enough that sample efficiency matters.

### 3.2 Observation

The observation is 13-dimensional, `float32`. All channels describe months already simulated.

| # | Channel | Scaling |
|---|---|---|
| 0 | Episode progress | `t / 42` |
| 1–3 | Current crop, one-hot (corn, barley, alfalfa) | — |
| 4 | Alfalfa stand age | `/ 7` |
| 5 | Soil water at end of last month (mm) | `/ 300` |
| 6 | Cumulative nitrogen-stress days | `/ 50` |
| 7 | Cumulative water-stress days | `/ 50` |
| 8 | Last month's precipitation (mm) | `/ 50` |
| 9 | Last month's PET (mm) | `/ 200` |
| 10 | Remaining annual N allowance | `/ cap` |
| 11 | Month within season | `/ 6` |
| 12 | Year within rotation | `/ 7` |

Divisors are order-of-magnitude scalings chosen to put channels near unit range, not statistical
normalization from a data pass — and that turned out to be insufficient on its own, which §3.7
treats as a finding rather than an implementation note. Hydrologic state comes from `hru_wb_mon`,
stress from `hru_pw_mon`.

**No future weather is observable.** The policy is a nowcast, not a forecast. This is deliberate
and it is what makes the perfect-foresight reference in §4 a meaningful contrast rather than a
trivial one: the gap between the two quantifies what anticipation would be worth to a manager who
cannot anticipate.

### 3.3 Action

For the irrigation arm the action is a scalar in [0, 1], scaled by `MONTH_DEPTH_MAX = 200` mm, giving
the depth applied in the current month. Depths become SWAT+ management operations directly: one
`irrm` operation per non-zero month, placed mid-month at day 15, or on the last day before harvest
when day 15 falls at or after it, written to `irrigation.ops` with `IRR_EFF = 1.0`.

**Constraints are enforced by repair, not by reward penalty.** An infeasible plan — a rotation
violation, or nitrogen above a loading cap when one is imposed — is rewritten to the nearest
feasible plan before simulation. This keeps the reward interpretable as money, but it has a cost
that §4 makes into a protocol requirement: repair silently changes what was requested, so a repair
applied on one code path and not another changes the objective invisibly.

Repair is therefore applied *asymmetrically by design*, and the asymmetry is stated rather than
inherited. Rotation feasibility is repaired over the whole plan, since it is a property of the
sequence. A nitrogen cap is **not**: rewriting the whole plan each step would let month t revise
months already simulated and reported to the agent, so the cap instead enters as observation
channel 10 (remaining annual allowance) and clips only the current month's application. The agent
sees the constraint and acts inside it; the past is never rewritten. In the irrigation experiment
the cap is disabled on every arm (`max_n = None`), and the experiment-level scorers give it **no
default value** — it must be passed explicitly — because a silent default once applied a
400 kg N ha⁻¹ cap to the open-loop objective while the policy ran uncapped, which inverted the
sign of the headline comparison.

### 3.4 Reward

**The full reward function, in one place.** The scored quantity is rotation-total profit, in
$ ha⁻¹ over the seven scored years:

  Π(λ_n) = Σ_c Y_c · p_c − mm_irr · p_w − Mg_manure · p_m − kg_N · p_N − n_events · p_op − λ_n · NO₃

Every term is read from a completed engine run rather than assumed:

| Term | Symbol | Source | Price (§3.6) |
|---|---|---|---|
| Crop revenue | Σ_c Y_c · p_c | `basin_crop_yld_yr`, Mg DM by plant name | $/Mg DM, NASS 2022–24 mean |
| Irrigation | mm_irr · p_w | `hru_wb_yr.irr` | $0.41 mm⁻¹ ha⁻¹ *(placeholder)* |
| Manure | Mg_manure · p_m | `management.sch` fert ops, manure products | $5.00 Mg⁻¹ *(representative)* |
| Mineral N | kg_N · p_N | same, non-manure products, × `fertilizer.frt` N fraction | $1.54 kg⁻¹ N |
| Application passes | n_events · p_op | count of fert operations | $5.00 ha⁻¹ event⁻¹ |
| Nitrate leaching | λ_n · NO₃ | `basin_aqu_yr.no3_rchg` | **swept, λ_n = 0 by default** |

Three details matter for reproducing the number. Manure is charged by **mass**, not by nitrogen
content, because dairy manure here is a disposal stream whose real cost is haul-and-spread; its N
content enters only the emissions accounting (§3.8). Passes are charged per operation for either
source, because without a per-event charge splitting nitrogen is free and "how many passes are
worth it" has no answer. And λ_n defaults to **zero**: leaching is always *reported* as
`no3_leached_kg`, and enters Π only when a sweep sets a price (§3.5). N₂O never enters Π at all.

Per step,

  r_t = (Π_t − Π_{t−1}) × 10⁻³

where Π_t is the profit of the whole rotation re-simulated with operations decided through step t.
Two properties follow. The sum telescopes and γ = 1, so **the episode return is exactly 10⁻³ × total
rotation profit** — the decomposition is a credit-assignment device, not a change of objective, and
it is what lets PPO and CMA-ES be checked for optimizing the same quantity (§4). And a step's reward
is not that month's profit but the whole-rotation change caused by that month's water, which is
non-local: April water can move September yield. This is the direct consequence of SWAT+ having no
checkpoint-restart, and it is why credit assignment here is harder than the 42-step horizon
suggests. The 10⁻³ scale exists because unscaled $ ha⁻¹ returns put the value target near 10⁷.

### 3.5 Multi-objective formulation

**Profit is the objective the policy maximizes; sustainability is the second objective, and it is
settled by a frontier rather than by a price.** The distinction is operational, not rhetorical: a
sustainability claim that depends on a number we cannot source is not a claim. Because neither
externality has a defensible market price at this site, both enter as *swept* prices rather than
as fixed costs inside the headline objective:

  Π(λ_w, λ_n) = Π₀ − λ_w · mm_irr − λ_n · NO₃

where Π₀ is revenue net of the agronomic input costs. The grid is evaluated with the
market-price arm (λ_w at the scored water price, λ_n = 0) always reported alongside, and we
publish the whole curve rather than selecting a point, so no conclusion rests on a shadow price
we would have to defend.

**Why both axes are swept, and why water is the sharper one.** The farmer's water price is
precisely what *fails* to reflect aquifer scarcity — which is why depletion is a problem in the
Eastern Snake Plain at all — so treating it as a fixed cost would build the sustainability
question out of the model. Applied water is measured, gate-verified against practice to within
0.01 %, and strongly responsive to management; it is the strongest sustainability axis available
here.

**The two axes are not independent, and we say so rather than presenting them as orthogonal.**
In this model leaching is driven by over-irrigation, not by fertilization: holding irrigation at
the measured rate, nitrogen dose produces zero leaching at every rate tested up to 4,490 kg N ha⁻¹,
while raising applied water by 20 % produces 32 kg N ha⁻¹. Both prices therefore act through the
same lever, and a two-dimensional grid shows correlated rather than independent movement.

**Claims are stated as dominance wherever possible** — *at matched profit, strategy X uses Y % less
water* — because a dominance claim requires no price at all and survives a reader's disagreement
about what water or nitrate is worth.

**Re-scoring is exact; re-optimizing is not.** Profit is linear in every price and the cost terms
are stored separably, so a schedule's profit at any price vector is arithmetic on stored rows with
no further simulation. That answers *how would this schedule fare if water were dearer*. It does
not answer *what schedule would you choose if it were* — that requires re-running the search, and
the two are reported separately rather than conflated.

**What "leaching" means here.** NO₃ is `no3_rchg` summed over the scored years — nitrate reaching
the aquifer in recharge. It excludes surface, lateral and tile pathways. This is the quantity of
interest for groundwater loading, and it is also the quantity most exposed to the percolation
limitation in §5.2.

### 3.6 Prices

| Term | Value | Basis |
|---|---|---|
| Crop prices | Idaho marketing-year averages, 2022–24 | USDA NASS *Crop Values 2024 Summary*; alfalfa:corn ratio 1.489 |
| Alfalfa hay | `$/ton ÷ (0.907185 × 0.88)` | dry-matter conversion |
| Barley | 48 lb/bu, 13.5 % moisture | grain-to-DM conversion |
| Corn silage | `$/bu × 9.0 ÷ (0.907185 × 0.35)` | **derived — no NASS silage series** |
| Mineral N | **$1.54 / kg N** | USDA AMS urea, Inter-Mountain West, w/e 2025-04-04 |
| Water | **$0.41 / mm / ha** | **placeholder**, ≈ $50/acre-ft; breakeven reported instead |
| Manure | **$5.00 / Mg** | **representative, not sourced** — haul-and-spread |
| Application pass | $5.00 / ha | after CyclesGym 2.0 §2.5; without it, splitting N is free |

Profit is linear in every price and the cost terms are stored separably, so the price at which any
advantage vanishes is exact arithmetic on stored rows with no further simulation. We report those
breakevens wherever a placeholder price is load-bearing, which converts a result that depends on an
unsourced number into a statement of the form *this holds for any price below X*.

### 3.7 Learning algorithm, and why it is configured this way

The policy is PPO (`MlpPolicy`, Stable-Baselines3) over the continuous action box, trained on four
`SubprocVecEnv` workers — parallelism is across CPU cores because SWAT+ is CPU-bound and the
engine, not the network, is the cost. Three configuration choices are not defaults and are
load-bearing enough to belong in the method rather than in a config file.

**γ = 1, and rollout lengths keyed to the episode.** The objective is total rotation profit over a
fixed 42-step horizon, so discounting would optimize something else. `n_steps` is 4 episodes (168)
and `batch_size` 2 episodes (84): both are set *by formula from the episode length* rather than
tuned. This is deliberate and §4 relies on it — hyperparameters that were searched would need a
validation split the weather record cannot support.

**Observations are statistically normalized, and the statistics travel with the policy.** With the
order-of-magnitude divisors of §3.2 alone, PPO learns an *exactly constant* schedule: the standard
deviation of applied depth across held-out weather windows is **0.000 mm**. Several channels sit
near zero in practice — nitrogen and water stress divided by 50 when stress runs 0–5 — and a
network fed them learns to ignore them, which is a failure of input scaling masquerading as a
finding about adaptivity. Running observations through a `VecNormalize` filter (clip 10) raises
that standard deviation to **6.4 mm**, raises return by **1,320 $ ha⁻¹**, and *cuts* applied water
from 6,116 to 5,352 mm. We report this because a paper whose question is "does the policy condition
on state" can be answered negatively by this bug alone, and the negative result would look
substantive. The filter's mean and variance are saved beside the policy weights and are a
**required** argument to every scorer: a policy trained on normalized observations and scored on
raw ones is not a degraded policy but a different objective — the same class of silent divergence
as the nitrogen-cap mismatch in §3.3, and the reason §4 makes objective parity a tested property.

**Initial exploration scale.** `log_std_init = −2.0` (σ ≈ 0.14 on the unit action box), against the
SB3 default of 0. At σ ≈ 0.37 the policy applied 6,116 mm against a measured 3,939 and saturated
10 % of its actions at the box boundary; at σ ≈ 0.14 it applied 4,533 mm, earned more, and saturated
2 %. A wide initial Gaussian on a bounded action that is *already* generous — 200 mm in a single
month — spends the budget in a region no manager would irrigate in.

Both the observation filter and the exploration scale are hashed into the key that identifies a
saved policy, alongside the price vector, the nitrate price, the cap and the pinned baseline plan,
so a checkpoint cannot silently resume into a run asking a different question.

### 3.8 Emissions accounting

Nitrous oxide is computed by IPCC (2019 Refinement) Tier 1 accounting from quantities the
simulation already produces — direct `EF1 × N_applied`, indirect `EF5 × NO₃` from leaching, and
indirect `EF4 × FracGASF × N_applied` from volatilization — and reported beside profit. It is
**accounting over simulated nitrogen flows, not a simulated N₂O flux**, and is labelled as such
throughout.

We do not use the engine's denitrification output as an N₂O proxy. It is available and would cost
nothing to read, but at this model's calibrated parameters denitrification is effectively switched
off (`denit_exp` = 0.001 against a SWAT default near 1.4; `denit_frac` = 1.0, firing only at
saturation), and all nitrate loss terms together come to under 5 kg N ha⁻¹ in the worst year.
Re-enabling it would mean re-fitting a nitrogen cycle that is calibrated against a measured soil
nitrate trajectory, trading a validated quantity for an unvalidated one.

In the irrigation experiment nitrogen is pinned, so the direct term is constant across arms and
only the indirect leaching term varies; emissions is therefore reported but not given its own
swept axis, where it would be a rescaled copy of the nitrate axis. It becomes an independent lever
in the nitrogen experiment.

---

## 4. Evaluation protocol

Each element exists to prevent a specific way of being wrong.

**Budgets matched in engine runs.** Timesteps and CMA-ES evaluations are not comparable units, but
both reduce to engine runs: one per environment step, one per window per open-loop evaluation. Both
methods are held to the same total, and the realized counts are read back off the runner and
reported rather than assumed.

**Objective parity, tested rather than assumed.** Two methods can consume identical budgets and
still optimize different problems if a constraint, price, or repair rule is applied on one code
path and not the other. Because constraints here are enforced by repair (§3.3), such a divergence
is invisible in the reward — it changes what was simulated, not what was priced. We therefore treat
parity as a testable property: an identical plan scored through the open-loop path and through the
environment rollout must agree on profit, applied water, applied nitrogen, yield and leaching, and
this is asserted in the test suite. We recommend the check generally; a constraint that binds on
one arm and not another can invert a headline without producing any visible anomaly.

**Year-disjoint weather windows.** Training windows start 1995–2004 and test windows start
2013–2017; the eight-year spans share no calendar year, and 2012 is left unused as a buffer. An
assertion enforces this at import. The rule is not cosmetic: an earlier split placed a training
window and a test window seven calendar years apart out of eight, so the optimizer was tuned and
evaluated on largely the same weather.

**Reported uncertainty accounts for window overlap.** Test windows begin in consecutive years, so
adjacent windows share seven of eight calendar years and the paired differences are strongly
correlated. A naive standard error over windows understates uncertainty. We report intervals from a
moving-block bootstrap and state the effective independent sample size, which for a 12-year test
span and 8-year windows is approximately 1.5 — considerably smaller than the number of windows
suggests. This is structural: with rotation-length windows and a three-decade weather record, no
split yields many independent test windows.

**Seed replication with a median representative.** Learned policies are trained at three or more
seeds and the *median* performer is reported. Reporting the best of N is selection on the
evaluation set.

**Frozen plans selected on train.** A policy is rolled out on each training window, each rollout
yielding a concrete fixed schedule; the schedule with the best training mean is replayed on the
test windows. Selecting the best of N on test would bias the adaptation estimate negative by
construction, as the expected maximum of N noisy estimates.

**No validation split, by design rather than by omission.** The training block carries both roles a
validation set would otherwise divide: it is where the optimizers search, and it is where every
selection the protocol makes is resolved — frozen plans are chosen on their training means, and the
matched-budget open-loop optimum that a policy is measured against is itself searched on the
training windows. We do not carve a third block out of it. The record cannot support one: eight-year
windows over a 1995–2025 weather series yield 10 training and 5 test starts once the buffer year is
removed, and a validation block could only be taken from one of the two, each of which already sits
near an effective independent sample size of 1.5. Selecting a configuration on two or three
overlapping windows is close to selecting at random, so a validation split of this size would buy
the appearance of a safeguard rather than the safeguard. Nor does the protocol need one: PPO's
hyperparameters are fixed by formula from the episode length rather than searched, seeds are
summarized by their median rather than their best, and CMA-ES and PPO are held to a common budget
rather than each tuned to its own most favourable configuration. A validation set exists to
adjudicate a choice among candidates; we have removed the choices instead. This argument covers
policy training only. It does not extend to calibration, whose parameters were fit against
measurements falling inside both blocks, so the environment itself is not year-held-out from the
evaluation — a limitation we state in §6.5 rather than one this split resolves.

**Frozen plans are a state-dependence control, not an adaptation metric.** If a policy scores no
better than its own frozen schedule, it has learned a constant and any "adaptivity" is nominal.
But the converse does not follow. A policy's emitted schedule is not a *searched* schedule, so the
gap between policy and frozen plan mixes two effects: how much the policy gains by conditioning on
state, and how much worse its emitted schedule is than a well-optimized one. Where the frozen plan
falls below the matched-budget open-loop optimum, that gap is dominated by search quality and
overstates adaptation. The defensible measure of adaptation is the policy against the
matched-budget open-loop optimum; the frozen plan answers only whether the policy is a constant.

**A perfect-foresight reference, reported as an estimate.** Optimizing a separate open-loop
schedule per window and comparing against one shared schedule bounds what weather-specific
information is worth in this action space. It is an *estimate*, not an upper bound: each per-window
optimization is itself a finite-budget search over 42 dimensions and can be under-converged, and we
have observed a learned policy exceed it. We report it as `foresight_estimate` and never as a
ceiling.

**A parametric feedback controller as a third policy class.** A three-parameter rule —
`depth = clip(a + b · soil-water deficit + c · precipitation deficit)` — uses the same action space,
the same observations, and the same full-horizon replay, hence the same engine cost per rollout as
the learned policy. It separates two very different conclusions: that adaptation has little value
in this system, or that a particular learning method failed to capture it.

---

## 5. Case study

### 5.1 Site

The field is a 1-ha Portneuf silt-loam plot at the USDA-ARS GRACEnet site near Kimberly, Idaho,
under a corn–barley–alfalfa rotation. The scored window is 2013–2019 with 2012 as spin-up.
Management comprises 158 measured irrigation events totalling 3,938.8 mm and dairy manure of
measured composition, applied in the corn and barley years. Dry-matter yield is measured in every
scored year. A calibrated ArcSWAT model of the same field supplies secondary references — ET,
percolation, uptake, leaching — that are not measured on site and are weighted below measurement.

The generated monthly baseline reproduces measured applied depth to within 0.01 % (3,938.9 vs
3,938.8 mm), which is asserted before any arm is scored. Without that gate an irrigation experiment
can report gains that are simply a different amount of water than practice.

### 5.2 Calibration as a bound

Measured targets outrank reference-model outputs. Three structural limits bound interpretation.

**Barley phenology.** Typed as a cold annual, an April-sown crop collapses; re-typing it as a warm
annual restores a credible heat-unit trajectory.

**Alfalfa residency.** Declared perennial, alfalfa remains resident and competing in years when it
is not the intended crop, and the engine provides no clean end to that residency. Per-crop
agreement within roughly ±15 % is therefore not simultaneously reachable for all crops, which makes
within-crop levers more interpretable than rotation.

**Percolation behaves correctly but is not validated here.** Potential evapotranspiration is
calibrated against the site's measured grass-reference ET series, and actual ET runs at 0.66–0.70
of it under measured practice. Percolation is **threshold-behaved in applied water**, which is the
agronomically correct response: below crop demand essentially nothing drains, and above it drainage
and nitrate rise together (Table 2).

**Table 2.** Percolation and nitrate response to applied water, monthly baseline scaled.

| Applied (mm, 7 yr) | Percolation (mm yr⁻¹) | NO₃ (kg N ha⁻¹ yr⁻¹) | Implied leachate (mg L⁻¹) |
|---|---|---|---|
| 2,363 | 0.00 | 0.00 | — |
| 3,151 | 0.00 | 0.00 | — |
| 3,939 *(measured depth)* | 9.40 | 1.69 | 17.9 |
| 4,727 | 96.54 | 14.08 | 14.6 |
| 5,366 | 141.17 | 29.08 | 20.6 |
| 5,778 | 162.17 | 42.94 | 26.5 |

Implied leachate concentration stays within 13.6–26.5 mg L⁻¹ wherever drainage occurs — physically
plausible, and above the 10 mg L⁻¹ drinking-water standard that motivates regional nitrate concern.
The water and nitrogen pathways are therefore telling a consistent story, which is what the
frontier in §6.3 requires.

Two limits remain. The ET *level* runs above the reference model of the same field, a difference
between SWAT+ rev 62 and the SWAT2012 lineage that reference was built in rather than an input
error. And there is **no on-site measurement of leaching or percolation to validate against**, so
reported kg N ha⁻¹ rank strategies *within the model* and should not be read as measurements of
what this field loses. A further caveat matters for uncertainty: under measured practice the
leaching signal is **sparse across weather windows** — one of five test windows carries almost all
of it — so between-window variance on leaching differences is large.

---

## 6. Results

### 6.1 Calibration state

Agreement must be read per crop and year (Table 3). Aggregate goodness-of-fit is misleading when
errors are signed, because they cancel across crops and within barley and corn years.

**Table 3.** Annual dry-matter yield (Mg ha⁻¹).

| Year | Crop | SWAT+ | Reference | GRACEnet |
|---|---|---|---|---|
| 2013 | Corn | 21.46 | 21.81 | 22.10 |
| 2014 | Barley | 7.29 | 6.51 | 5.90 |
| 2015 | Alfalfa | 8.82 | 9.87 | 9.00 |
| 2016 | Alfalfa | 15.26 | 15.79 | 14.79 |
| 2017 | Alfalfa | 16.74 | 16.38 | 16.16 |
| 2018 | Corn | 20.42 | 25.44 | 22.93 |
| 2019 | Barley | 6.67 | 6.93 | 8.78 |

| Crop | Bias vs GRACEnet | vs reference |
|---|---|---|
| Alfalfa | +2.2 % (n = 3) | −2.9 % |
| Corn | −7.0 % (n = 2) | −11.4 % |
| Barley | −4.9 % (n = 2) | +3.9 % |

Barley's crop-mean bias masks opposite year signs; corn's shortfall is driven especially by 2018.
Only alfalfa is tight year on year. The residual is structured, so irrigation and nitrogen rankings
should be read under within-crop bias, and rotation rankings remain provisional on price.

### 6.2 Experiment 1 — irrigation

**How much is there to adapt to?** Before ranking strategies, the perfect-foresight reference
bounds the question. Optimizing a separate 42-parameter schedule per weather window beats one
shared schedule by **+836 ± 68 $ ha⁻¹** on the held-out windows (n = 5, per-window range
+651 to +1,062), far above the 250 $ ha⁻¹ noise floor. Weather-specific scheduling is therefore
worth a substantial amount at this site: a null result for closed-loop control here cannot be
explained by there being nothing to adapt to. Per §4 this is an estimate and not an upper bound —
each per-window oracle is a finite-budget search over 42 dimensions and may be under-converged,
which biases the figure down.

*[Pending: the remaining strategy rows are being regenerated under verified objective parity (§4).
The previously computed table applied a nitrogen loading cap to the open-loop arms — including the
CMA-ES objective — but not to the learned-policy arm, so the two methods optimized different
problems at matched budget and the rows were not comparable. Only measured practice, which builds
no plan, is unaffected at 20,925 $ ha⁻¹.]*

**Table 4.** Exp 1 test profit ($ ha⁻¹), window starts 2013–2017, λ_n = 0.

| Strategy | Test profit | vs measured | vs open-loop | Water (mm) | NO₃ (kg N/ha) | N₂O (kg/ha) |
|---|---|---|---|---|---|---|
| Measured practice | 20,925 | 0 | — | 3,939 | — | — |
| Generated monthly default | — | — | — | 3,939 | — | — |
| CMA-ES open-loop | — | — | 0 | — | — | — |
| CMA feedback controller | — | — | — | — | — | — |
| PPO policy (median seed) | — | — | — | — | — | — |
| Frozen plan (train-selected) | — | — | — | — | — | — |
| *Foresight estimate (oracle − shared)* | **+836 ± 68** | — | — | — | — | — |

**Table 5.** Exp 1 across PPO seeds. *[Pending.]*

### 6.3 The profit–leaching frontier

*[Pending the λ_n sweep. Grid points are anchored on breakevens computed from the λ_n = 0 results
rather than chosen a priori: the nitrate price at which the learned policy's advantage over
open-loop search vanishes, and the price at which its advantage over measured practice vanishes.
Report both, the full frontier, and the cross-scoring matrix in which every strategy optimized at
one price is re-scored at every other — exact arithmetic requiring no further simulation.]*

The frontier answers the second question, once §6.2 has answered the first. Given a strategy that
earns more, does it also reach lower leaching at matched profit than a schedule searched to the
same budget — that is, does closed-loop control still pay once the objective becomes
timing-sensitive rather than volume-sensitive? A profit gain bought with more water and more
nitrate is not an improvement, and the frontier is what makes that visible without our having to
price either.

### 6.4 Adaptation and its baseline

*[Pending. Report the policy against the matched-budget open-loop optimum as the adaptation
measure, and the policy against its own train-selected frozen plan as the state-dependence control,
with the gap between the two interpretations made explicit per §4. Report bootstrap intervals and
the effective sample size, not naive standard errors over overlapping windows.]*

### 6.5 Limitations

A single HRU and soil. Full-horizon replay makes every evaluation cost 42 engine runs, which bounds
achievable budgets. Water and manure prices are placeholders; breakevens are reported wherever they
are load-bearing. Calibration mixes measured and reference-model targets without year hold-out, and
measured yield, crop identity and manure records end in 2019, so no independent hold-out period is
available. **Leaching is reported, and priced in the frontier, but not validated** — the percolation
pathway is a known rev-62 divergence (§5.2), so a policy optimized against leaching may be
exploiting model error, and that failure would not be visible in the results. N₂O is accounting over
simulated nitrogen flows, not a simulated flux. Test windows overlap, so the effective independent
sample size is far below the number of windows. Rebalancing the split to widen the test span, and
wiring the site's measured seasonal water-balance series as an independent check on the model's
soil-water storage, are both available and are left to future work.

---

## 7. Future work

Source water and manure prices. Extend beyond one HRU. Complete the nitrogen, rotation and joint
levers under the same protocol, where emissions becomes an independent axis rather than a rescaled
copy of leaching. Resolve or bound the rev-62 percolation divergence so that leaching magnitudes
can carry field meaning. Validate winning schedules in an independent simulator.

---

## 8. Conclusion

We set out to ask whether a learned policy can raise farm profit without paying for it in water and
nitrate, and we have built the two things that question needs before it can be answered honestly: a
Gymnasium environment driven by official SWAT+ on a measured Kimberly field — to our knowledge the
first such stack — and a protocol that makes a comparison between a learned policy and a searched
schedule mean what it appears to mean. The protocol's requirements are unglamorous: match budgets
in engine runs, verify that competing methods optimize the same objective rather than assuming it,
keep training and evaluation weather disjoint, report uncertainty that accounts for overlapping
windows, and treat a policy's own frozen schedule as a control on state-dependence rather than as a
measure of adaptation. Without them, "the policy is greener" cannot be told apart from "the policy
was searched harder."

Profit is what the reward maximizes; sustainability is the second objective, and refusing to price
it is what makes the frontier rather than a scalar the deliverable. We report where each method's
curve lies and where curves cross, never an optimum at a chosen λ_n, so a reader who disagrees with
us about what nitrate is worth can still read the result.
*[TODO: state the empirical finding once the corrected runs land.]*

Two limits bound how far any of this reaches beyond the model, and both grow rather than shrink the
moment sustainability is treated as a real objective. Leaching ranks strategies within the model
and does not measure what the field loses; optimizing *for* an unvalidated channel is precisely the
regime in which model error is exploited without becoming visible. And N₂O is not simulated by
SWAT+ at all — what we report is IPCC Tier 1 accounting over simulated nitrogen flows, never
priced. A greener policy in these results is a greener policy *in this model*, which is a claim
worth making only because the protocol makes it checkable.

---

## Acknowledgements

*[to complete]*

## Data and code availability

Code, model inputs, and experiment scripts: *[repository URL]*. Input provenance and build notes:
`PROVENANCE.md` (supplement).

## References

*[To assemble in journal format.]*

**Agricultural RL.** Overweg et al. (2021), CropGym, arXiv:2104.04326. Gautron et al. (2022),
gym-DSSAT, arXiv:2207.03270. Turchetta et al. (2022), CyclesGym, NeurIPS Datasets & Benchmarks.
WOFOSTGym (2025), arXiv:2502.19308. Madondo et al. (2023), *A SWAT-based Reinforcement Learning
Framework for Crop Management* (SWATgym), arXiv:2302.04988.

**Site and region.** Bierer et al. (2022), Kimberly GRACEnet manure incorporation. Richards et al.,
Twin Falls Canal Company SWAT assessment *[locate]*. Agronomy 11(5):1005 (2021), nutrient cycling in
intensive dairy regions. Idaho IDWR / DEQ nitrate and curtailment materials.

**Models and methods.** Arnold et al. (2012), SWAT; Bieger et al. (2017), SWAT+. Hansen & Ostermeier
(2001), CMA-ES. Schulman et al. (2017), PPO. USDA NASS Crop Values 2024 Summary. IPCC (2019),
*2019 Refinement to the 2006 IPCC Guidelines for National Greenhouse Gas Inventories*, Vol. 4 Ch. 11.
