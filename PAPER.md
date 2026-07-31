# A calibrated SWAT+ field environment for reinforcement-learning management optimization

Eric Du *[co-authors and affiliations to confirm]*

---

## Abstract

Adaptive management is widely advocated for irrigated systems under water and nitrogen stress, and
reinforcement learning (RL) is increasingly proposed as the means of designing it. Learning such
policies requires a simulator, and two questions about that simulator are routinely left unasked:
whether it is accurate enough for the learned policy to carry meaning, and whether any advantage it
produces comes from adapting at all. We address both in a SWAT+ environment built for a measured
1-ha irrigated corn–barley–alfalfa field at Kimberly, Idaho (2012–2019), assembled entirely from
text inputs so that every calibrated value is a versioned edit. Reconciling carried-over template
inputs reduced potential-evapotranspiration bias from −10.0 % to −1.4 %, and correcting a crop-type
misassignment and a resident-perennial artefact reduced per-crop yield bias against measurement to
+0.5 % (alfalfa), −17.9 % (barley) and −24.7 % (corn). The residual is signed and crop-specific, so
an aggregate goodness-of-fit statistic reflects cancellation rather than agreement; we show that
this licenses within-crop levers while leaving the between-crop lever weakly identified. Rotation
dominated a six-arm lever ablation (+2,669 $ ha⁻¹ over measured practice), but the alfalfa–annuals
profitability crossover falls within three years of observed price history, so the ranking is a
price artefact rather than an agronomic finding. That ablation also exposed a failure mode we
report as a result in its own right: a defect in the generated baseline under-irrigated every
optimized arm by 22 % relative to the measured practice it was compared against, which did not
present as a defect but as a finding about whichever lever it suppressed — inverting the sign of
the nitrogen result. Corrected, the baseline falls within −127 ± 226 $ ha⁻¹ of measured practice,
and nitrogen management is worth +3,900 to +4,500 $ ha⁻¹, with an optimum that is a shelf rather
than a peak: tripling applied nitrogen buys 2.6 %. A PPO policy exceeded an optimized fixed schedule
by 12.9 % on held-out weather, yet freezing the policy's own action sequence scored as well or
better: the advantage was optimizer budget, not adaptivity. Re-run at matched engine budgets and
with carryover soil state restored to the observation, the policy loses to the fixed schedule by
664 ± 64 $ ha⁻¹ and is improved by freezing its own plan, so the value of adapting is negative
rather than merely absent. Irrigation scheduling is worth +2,397 ± 250 $ ha⁻¹ on 2.6 % more water,
earned by aligning irrigation onset with each crop's planting date rather than a fixed calendar
day. On that arm a single seed — the default seed — returns a policy advantage of +199 $ ha⁻¹ while
three seeds return −47 ± 123, so the headline is not separable from initialisation noise; the
frozen-plan control, by contrast, is negative in every seed of every arm we ran. We therefore argue
that an adaptivity claim should rest on a control that is stable under nuisance variation rather
than on a margin that is not. Because externalities were kept
separable from profit, the trade-offs remain visible — the profit-maximising rotations leached
15.1–17.5 kg N ha⁻¹ against 10.9 for measured practice, and the policy's advantage was bought with
56 % more applied water and disappeared at a plausible pumping cost. We conclude that an adaptivity
claim must be demonstrated against a frozen-plan control and an equal-budget baseline rather than
inferred from a policy's score.

**Keywords:** reinforcement learning; SWAT+; crop model calibration; irrigation management;
nitrogen management; dairy-forage systems; agricultural decision support

---

## 1. Introduction

### 1.1 The joint water–nitrogen constraint

Southern Idaho's irrigated agriculture faces three pressures acting on the same finite water:
population growth converting into municipal demand against senior agricultural rights, a declining
and earlier snowpack that shifts *when* Snake River water is available relative to when crops need
it, and dairy expansion that has moved cropland toward forage while loading it with manure nitrogen
beyond crop removal. The Magic Valley concentrates roughly 500,000 of the state's 660,000 dairy
cows within six counties, and cropland there receives dairy manure at rates near 52 Mg ha⁻¹ yr⁻¹
(Richards et al.). The field studied here, a corn–barley–alfalfa rotation receiving dairy manure,
is an instance of that system at plot scale.

Both resources are management decisions at this site. Kimberly receives approximately 267 mm of
annual precipitation against approximately 1400 mm of potential evapotranspiration, so essentially
all crop water is applied — the measured record averages 563 mm yr⁻¹ — and curtailment of junior
groundwater rights on the over-appropriated Eastern Snake Plain Aquifer makes applied depth an
allocation-constrained variable rather than a purely agronomic one. Nitrogen arrives principally as
manure, placed by hauling distance rather than agronomy; regional dairy density makes it the
cheapest nitrogen available and is simultaneously why nitrate is a designated groundwater concern,
so the economically optimal manure rate and the environmentally acceptable one are set by different
constraints. The two are coupled through a single process — nitrate reaches groundwater by
percolation, so an irrigation decision is also a leaching decision — and the results below show
this directly: the arms that irrigate least leach almost no nitrogen, not because they manage
nitrogen well but because nothing percolates. A simulator without a hydrological transport pathway
cannot represent that coupling.

### 1.2 Adaptive management and the problem of attribution

Management at this site follows a fixed calendar. Where a constraint binds in some years and not
others, such a calendar must be conservative enough to survive the unfavourable years and is
therefore misallocated in the remainder; the standard argument for adaptive management, and the
explicit motivation for much of the agricultural machine-learning literature, is that a policy
conditioned on observed state recovers that loss without relaxing the constraint.

That argument is seldom tested against the control that would falsify it. A policy which ignores
its observations still emits an action sequence, and that sequence may simply occupy a better point
in action space than the baseline optimizer located; where this is the case the reported advantage
reflects search rather than adaptation, and none of it transfers to unseen conditions. Nor is an
advantage automatically an environmental gain: a policy free to spend additional water will do so,
and will be scored favourably for it whenever water is priced too cheaply. We therefore adopt three
reporting requirements in advance of any comparison — an equal engine-budget comparison against an
optimized fixed schedule, a frozen-plan control separating adaptation from search, and resource use
and nitrate leaching reported alongside profit rather than folded into it. Under these requirements
the adaptivity gain at this site is zero, which we treat as the informative outcome rather than a
failed experiment.

### 1.3 Simulator dependence and the calibration problem

Reinforcement learning requires far more trajectories than field experimentation can supply, so
agricultural applications learn inside mechanistic crop models. The resulting environments —
CropGym, gym-DSSAT, CyclesGym, WOFOSTGym — trend steadily toward longer horizons and more crops,
but two gaps remain. The first is process coverage: they wrap crop models with limited or absent
hydrological routing, so the externality an agent should be penalised for is either missing or
crudely represented. Each motivates itself on sustainability, yet none carries the transport
process that determines it; SWAT+ carries it natively, which is the reason to accept its
computational cost.

The second gap is evidential. An agent optimizes whatever the simulator rewards, including the
simulator's errors. A simulator carrying signed, crop-specific yield bias does not merely displace
the objective; it distorts the relative return of the alternatives among which the agent chooses,
so the learned policy encodes model error as preference. Prior work generally reports environment
fidelity briefly or not at all, and reports RL improvements over baseline management without a
control separating adaptation from search. We argue that calibration state is a first-class result
bounding which action dimensions may be interpreted, and that an attribution protocol should
precede any claimed advantage. This paper accordingly contributes a calibrated, fully versioned
SWAT+ field environment; a calibration protocol that separates measured targets from another
model's simulated output and identifies the structural limit beyond which the present engine cannot
be improved; a lever ablation reported with the price sensitivity that determines whether its
ranking survives; and an attribution protocol that converts a nominal 12.9 % RL improvement into a
null.
---

## 2. Materials and methods

### 2.1 Study site, reference data and model

The study field is a 1-ha plot at the USDA-ARS GRACEnet site near Kimberly, Idaho, on Portneuf silt
loam, under a corn–barley–alfalfa rotation. The simulation window is 2012–2019: a 2012 barley
spin-up year excluded from scoring, followed by the seven-year 2013–2019 rotation, every year of
which carries a measured annual dry-matter yield. Measured management comprises 158 daily
irrigation events totalling 3,938.8 mm and four dairy manure applications of measured composition,
disked to 15 cm. A calibrated ArcSWAT (SWAT2012) model of the same field, with identical rotation
and irrigation record, reproduces the measured yields to +5.1 % PBIAS and serves as a secondary
reference, supplying annual evapotranspiration, percolation, nitrogen uptake and nitrate leaching,
none of which is measured at the site. Because agreement with it is model-to-model rather than
model-to-measurement, it is weighted below the measured targets and reported separately throughout.

The model runs on SWAT+ rev 60.5.7, built from a single-HRU demonstration template by idempotent
scripted edits rather than through a graphical editor, so that every calibrated value is a
differenceable, versioned change. Per-file provenance for all 65 engine inputs is in the
supplementary material.

### 2.2 Calibration

Calibration proceeded in three stages, ordered so that input errors were corrected before any
parameter was fitted; a parameter tuned to compensate for an incorrect input cannot subsequently be
recovered. **Stage 1** audited primary site records against the assembled model, taking the source
to govern wherever it disagreed with the reference model, and corrected ten inputs — corrections,
not calibrated values, the most consequential being a humus mineralisation rate left at zero by the
template so that organic nitrogen never mineralised. **Stage 2** screened 17 candidate parameters
by Morris elementary effects (SALib, 270 runs), analysed per objective rather than pooled: the
residuals point in opposite directions by crop, so a parameter that raises all three crops equally
is of no use and a pooled score would conceal that. **Stage 3** estimated the survivors by
differential evolution against a weighted sum-of-squared-PBIAS objective, measured yield terms
carrying unit weight and reference-derived terms 0.25–0.5, with errors squared so that
opposite-signed residuals could not offset one another. Full tables for all three stages are in the
supplementary material.

One Stage-1 correction is reported here for what it implies about the reward. The HRU had been
resized to 1 ha but its containing objects retained the template catchment's 1431.72 ha, so every
table SWAT+ normalises by basin area was diluted roughly 1,432-fold: nitrate reaching groundwater
read approximately 0.1 kg ha⁻¹ against an actual 114.9. Nothing was mis-simulated, but that
quantity is the environmental term in the RL reward, where it would have appeared as a constant
zero and rendered every leaching comparison in this paper meaningless.

### 2.3 Environment

Decisions for irrigation and nitrogen are monthly over the April–September growing season
(42 steps per seven-year episode). Rotation remains an annual crop choice. SWAT+ has no
checkpoint-restart, so sequential decisions use full-horizon replay. Mid-season observations
are soil water, cumulative stress, and recent precip/PET from monthly output tables already
simulated — not future weather. Carryover nitrogen is exposed as a remaining annual loading
allowance that clips the current month forward-only.

Reward is farm profit; nitrate leaching is reported alongside it. Train and test weather
windows share zero calendar years (train starts 1995–2004, test starts 2013–2017).

### 2.4 Experiments

Four experiments, numbered in run order. **Exp 1 (irrigation)** is the primary adaptivity
test: monthly open-loop CMA-ES, a CMA-ES parametric feedback controller, PPO, and a frozen-plan
control selected on training windows. A perfect-foresight ceiling (per-window open-loop versus
one shared schedule) gates whether cluster PPO is warranted. **Exp 2 (nitrogen)** frees manure
and mineral N under one loading cap. **Exp 3 (rotation)** enumerates feasible crop sequences
rather than searching them; the alfalfa:corn price sweep is the bias sensitivity. **Exp 4
(joint)** warm-starts from single-lever optima; scoring below the composed optimum is
pre-registered as an optimizer statement, not an interaction finding.

Every comparison that claims adaptivity uses matched engine-run budgets, the five-row protocol
(measured / generated default / fixed / policy / frozen), and ≥3 PPO seeds on Exp 1 and Exp 4.

---

## 3. Results

### 3.1 Calibration

**Input reconciliation and screening.** Replacing the template weather-generator station resolved
most of the potential-evapotranspiration discrepancy, moving PET from −10.0 % against the reference
to −1.4 %, and corrected the nitrate-leaching artefact from −99.9 % to +30.5 %. Evapotranspiration
improved only from −13.6 % to −11.2 %, and the Morris screen explains why: ET was insensitive to
every parameter screened, at a maximum μ\* of 5.5 PBIAS points, so the residual gap cannot be
closed from this parameter set and requires a separate explanation. The screen also found alfalfa
to have a nearly orthogonal lever — its biomass–energy ratio moves alfalfa yield by 112 points
while moving every other objective by less than 1.5 — so the over-predicted crop could be corrected
without disturbing the others.

**Two structural corrections.** Parameter estimation was preceded by two corrections that account
for more of the final agreement than the fitted values do.

Barley had been typed as a cold annual, which SWAT+ treats as fall-sown and heat-unit-banking; on
an April-sown crop this collapsed the heat-unit target to approximately 530 degree-days, so barley
matured 46 days after planting and then stood in the field for a further 66–85 days with biomass
frozen and every stress term at exactly zero. Re-typing it as a warm annual, with no other change,
restored growth windows of 97 and 110 days and realised 1,517 and 1,766 heat units against the
1,800 documented for the site — within 6–16 %, untuned — and moved barley from −69.9 % to −56.2 %.
Corn serves as the control: already a warm annual, it already realised 1,889 and 1,888 heat units
against the same target.

The second correction concerns a resident perennial. The plant community declares three plants, and
alfalfa is a perennial, so SWAT+ retains it as resident and competing for light and nitrogen in
every year of the simulation — including the two years before it is ever planted. Removing alfalfa
from the community entirely takes 2018 corn from 15.09 to 24.32 t ha⁻¹ against a measured 22.93,
and its nitrogen uptake from 129 to 321 kg ha⁻¹ against a measured 270.7. This is a diagnostic
rather than a remedy, since it also deletes the alfalfa years, and the engine offers no mechanism
to terminate a perennial's residency. **Per-crop agreement within ±15 % is therefore not reachable
on this engine.**

**Calibration state.** The resulting agreement against measurement is given in Table 1. It should
be read per crop and per year rather than in aggregate.

**Table 1.** Annual dry-matter yield (Mg ha⁻¹) and per-crop bias.

| Year | Crop | SWAT+ | Reference | GRACEnet |
|---|---|---|---|---|
| 2013 | Corn | 19.51 | 21.81 | 22.10 |
| 2014 | Barley | 7.78 | 6.51 | 5.90 |
| 2015 | Alfalfa | 10.84 | 9.87 | 9.00 |
| 2016 | Alfalfa | 14.28 | 15.79 | 14.79 |
| 2017 | Alfalfa | 15.03 | 16.38 | 16.16 |
| 2018 | Corn | 14.38 | 25.44 | 22.93 |
| 2019 | Barley | 4.28 | 6.93 | 8.78 |

| Crop | Initial bias | Final bias vs GRACEnet | vs reference |
|---|---|---|---|
| Alfalfa | +71.6 % | +0.5 % (n = 3) | +0.5 % |
| Corn | −38.5 % | −24.7 % (n = 2) | −34.6 % |
| Barley | −56.2 % | −17.9 % (n = 2) | −12.9 % |

The per-crop figures must not be read as uniform improvement, because they cancel within a crop as
well as across crops. Barley's −17.9 % comprises 2014 at +31.8 % and 2019 at −51.2 %; corn's
−24.7 % comprises 2013 at −11.7 % and 2018 at −37.3 %. Only alfalfa is tight year on year, at
+20.4 %, −3.4 % and −7.0 %. The residual is therefore not a random error term of decreasing
magnitude but a structured one.

### 3.2 Which levers move the objective

Six arms were optimized to approximately 4,000 evaluations each (Table 2). Measured practice scored
16,674 $ ha⁻¹ and is the appropriate anchor; including it changes the reading of one arm entirely.

**Table 2.** Lever ablation. Profit is the full-rotation total.

| Arm | Parameters | Evaluations | Profit ($ ha⁻¹) | vs default | vs measured practice | Irrigation (mm yr⁻¹) | NO₃ (kg ha⁻¹) |
|---|---|---|---|---|---|---|---|
| `MR` | 42 | 4005 | 19,469 | +5,051 | +2,795 | 412 | 17.5 |
| `R` | 21 | 728 | 19,343 | +4,925 | +2,669 | 412 | 15.1 |
| `all` | 63 | 4016 | 19,201 | +4,783 | +2,527 | 593 | 2.7 |
| `I` | 21 | 4004 | 16,932 | +2,513 | +258 | 585 | 0.3 |
| `M` | 21 | 2990 | 14,580 | +162 | −2,094 | 437 | 0.0 |
| Default | 0 | — | 14,418 | 0 | −2,256 | 437 | 0.0 |

Two of the three recorded predictions held. Rotation dominated, worth approximately +2,669 $ ha⁻¹
over measured practice. Irrigation contributed approximately nothing against real practice, but
only once the anchor is correct: against the default it appears worth +2,513 $ ha⁻¹, while against
measured practice it is worth +258, and the optimizer's own irrigation of 585 mm yr⁻¹ falls within
4 % of the measured 563. Almost the entire apparent gain was the recovery of an under-irrigating
default.

The manure prediction failed. Freeing rate, timing and source was worth +162 $ ha⁻¹ over the
default and −2,094 $ ha⁻¹ against measured practice, and this was obtained with manure priced at
zero, the case most favourable to applying it. Under this calibration and this scoring, uptake
rather than supply binds for the manure lever.

The profit-maximising rotations leach more nitrate: the `R` and `MR` arms reached
15.1–17.5 kg N ha⁻¹ against 10.9 for measured practice and approximately zero for the
irrigation-only arms. Because the leaching term is reported separately rather than priced into
profit, this trade-off is visible rather than silently discharged. It also illustrates the coupling
described in Section 1.1: the low-leaching arms achieve that outcome by irrigating too little for
percolation to occur, not by managing nitrogen well.

Two caveats apply. The `all` arm scored below `MR` despite being a strict superset, which reflects
under-convergence at a fixed evaluation budget rather than a finding; arm comparisons at unequal
dimensionality should be read as lower bounds. The `R` arm converged in 728 evaluations against a
4,000 budget, because crop choice is an argmax over three scores and the landscape is therefore
piecewise constant.

### 3.3 Price sensitivity of the rotation result

The optimized rotation eliminates alfalfa. Sweeping the alfalfa-to-corn-silage price ratio with
rotations fixed (Table 3) places the profitability crossover at a ratio of approximately 1.60.

**Table 3.** Full-rotation profit ($ ha⁻¹) against alfalfa:corn-silage price ratio.

| Rotation | 0.6 | 1.0 | 1.18 | 1.4 | 1.63 | 2.0 | 3.0 |
|---|---|---|---|---|---|---|---|
| Measured | 11,390 | 13,503 | 14,453 | 15,615 | 16,829 | 18,783 | 24,064 |
| Optimized (`R`) | 19,343 | 19,343 | 19,343 | 19,343 | 19,343 | 19,343 | 19,343 |
| Continuous alfalfa | 6,824 | 11,811 | 14,055 | 16,797 | 19,665 | 24,277 | 36,744 |
| Corn–barley | 18,903 | 18,903 | 18,903 | 18,903 | 18,903 | 18,903 | 18,903 |

The observed 2022–2024 price range straddles that crossover. The 2024 ratio is 1.18, at which the
annual rotations win by approximately 5,300 $ ha⁻¹; the 2022 and 2023 ratios are both 1.63, at
which continuous alfalfa wins. The optimal rotation therefore reverses within three years of real
price history, and the instruction to eliminate alfalfa is a price artefact rather than an
agronomic finding. Reporting the rotation arm at a single price vector would have presented it as
the latter.

The direction of the calibration bias matters for how much of this survives. Both annual crops are
under-predicted while alfalfa is effectively unbiased, so the model is biased toward alfalfa, and
the optimizer avoided alfalfa in spite of that bias. Correcting the bias would strengthen the
anti-alfalfa conclusion rather than weaken it. The converse conclusion above the crossover enjoys
no such protection and should be treated as the weaker half of the curve.

### 3.4 Does adaptivity pay?

Trained on resampled weather windows and evaluated on held-out years, the PPO policy exceeded the
optimized fixed schedule by 2,245 $ ha⁻¹, or 12.9 %, winning all seven held-out windows with a
per-window advantage of +866 to +3,500 $ ha⁻¹ (Table 4).

**Table 4.** Adaptivity attribution. All values are full-rotation profit in $ ha⁻¹.

| Row | Train | Held-out |
|---|---|---|
| Optimized fixed schedule | 18,029 | 17,460 |
| PPO policy | 20,752 | 19,704 |
| PPO policy's own plan, frozen | — | 19,805 |
| Frozen plans, off-diagonal mean | — | 19,747 |

The frozen-plan control removes the interpretation. Taking the action sequence the policy emits on
one window, freezing it, and replaying it as a fixed schedule on all windows scores 19,805 $ ha⁻¹
— marginally better than the adaptive policy itself. The share of the advantage attributable to
adaptivity is −4 %, that is, none. The policy learned a near-constant program, and the entire
advantage is that this constant is a better schedule than CMA-ES located within its budget. The
mechanism is a compute asymmetry: the policy received 200,000 engine runs while the fixed-schedule
optimizer received 6,528, a factor of thirty. The comparison was unfair to the baseline rather than
favourable to the policy.

The water-price control removes what remains. The policy irrigates 878 mm yr⁻¹ against the fixed
schedule's 541 and measured practice's 563, and its advantage vanishes entirely at a water price of
1.36 $ mm⁻¹ ha⁻¹, approximately $168 per acre-foot, against the 0.41 placeholder used in scoring.
Pumped groundwater in southern Idaho can exceed that figure. Even the optimization advantage, which
is the part that is real, is therefore contingent on an input price rather than on management
skill.

We report no evidence that adaptivity pays in this environment. This is a null result, and it is
consistent with the design: with annual cadence over a seven-step horizon, and an observation
vector that excludes mineral-nitrogen carryover, the policy has little to condition on. What the
experiment establishes is that resampling the weather window is not by itself sufficient to create
something worth adapting to.

### 3.5 Nitrogen response

**Response-curve diagnostic.** Sweeping applied nitrogen directly, with all other dimensions held
at measured practice and a single application per fertilised year, produces a response curve with
an interior maximum. Profit rises from 11,785 $ ha⁻¹ at zero applied nitrogen to a maximum of
20,441 $ ha⁻¹ at 350 kg N ha⁻¹ per fertilised year, and declines thereafter to 18,284 at
800 kg N ha⁻¹ yr⁻¹, while nitrogen stress falls monotonically from 41.7 days to 3.5 days at the
profit optimum and simulated yield saturates. The arm therefore has an interior optimum rather than
being determined by the loading cap, though the cap at 400 kg N ha⁻¹ yr⁻¹ sits close above it.
Simulated corn biomass at the profit optimum reaches 25.8 t ha⁻¹, which exceeds a credible field
response: the direction of the nitrogen-stress mechanism is trustworthy while its magnitude is not,
and the magnitude is consistent with the optimizer exploiting the known corn under-prediction.

**The optimized arm.** The arm was then optimized at the full protocol of Section 2.4 (Table 5),
twice: once at the 400 kg N ha⁻¹ yr⁻¹ loading cap, and once with the cap removed. Both arms were
given 50,000 engine runs per method — 6,255 CMA-ES evaluations over eight training windows, against
50,000 PPO environment steps — and both are scored on the same seven held-out weather windows, so
every difference below is a paired one.

**Table 5.** Nitrogen arm, full-rotation profit ($ ha⁻¹) on held-out weather. Paired standard
errors over the seven held-out windows.

| Row | Capped (400 kg N ha⁻¹ yr⁻¹) | Uncapped |
|---|---|---|
| Measured practice | 17,478 | 17,478 |
| Generated baseline (`DEFAULT_PLAN`) | 17,351 | 19,178 |
| CMA-ES fixed schedule | **21,400** | **21,964** |
| PPO policy | 20,736 | 20,495 |
| PPO policy's own plan, frozen | 20,850 | 20,624 |
| Fixed vs generated baseline | +4,049 ± 297 | +2,786 ± 204 |
| Fixed vs measured practice | +3,922 ± 350 | +4,486 ± 357 |
| Policy vs fixed | −664 ± 64 | −1,469 ± 37 |
| Adaptivity (policy vs its own frozen plan) | −115 ± 31 | −128 ± 35 |

Nitrogen management is worth approximately +3,900 to +4,500 $ ha⁻¹ over measured practice, and the
mechanism is unambiguous: nitrogen-stress days collapse from 41.7 to 3.5 across the response curve,
so under this calibration supply rather than uptake binds for the annual crops. This reverses the
manure result of Section 3.2, and the reversal is explained in Section 3.6 — that arm was scored
against a baseline that was accidentally water-limited, so relieving nitrogen stress could not pay.

**The cap binds but is nearly inconsequential.** Under the cap the optimizer applies 1,589.4 of a
possible 1,600 kg N ha⁻¹, at the cap in three of the four fertilised years — the diagnostic
signature of an experiment measuring its own constraint rather than the agronomy. Removing the cap
raises applied nitrogen threefold, to 4,774.8 kg N ha⁻¹, and buys **+564 ± 13 $ ha⁻¹**, or 2.6 %.
The profit surface is therefore a shelf rather than a slope across a threefold range of applied
nitrogen, which both confirms the response-curve diagnostic at full budget and explains why the
optimizer parks against whatever bound it is given: over 300–400 kg N ha⁻¹ yr⁻¹ the direct sweep
spans only 144 $ ha⁻¹, well inside the between-window noise.

**The uncapped optimum is set by an unsourced price, not by agronomy.** The two arms reach the same
profit by opposite routes. The capped optimizer buys 1,022 kg of mineral nitrogen and hauls
33.4 Mg ha⁻¹ of manure over the rotation; the uncapped optimizer buys **no mineral nitrogen at all**
and hauls 244.8 Mg ha⁻¹. Manure carries nitrogen at approximately 0.38 $ kg⁻¹ N at the haulage
price used here against 1.54 $ kg⁻¹ N for urea, so once the loading cap no longer binds, source
choice is decided entirely by price and the optimizer buys the cheaper source without limit. The
uncapped arm is thus a measurement of the manure haulage price — the one input in the reward that
is explicitly a placeholder (Section 2.3) — rather than of nitrogen response, and 244.8 Mg ha⁻¹
lies far outside the range against which the model was calibrated. Removing a constraint replaced a
dependence on one modelling choice with a dependence on another; we report the response curve
rather than any single optimal rate, and treat the cap as a policy statement rather than a result.

**Adaptivity is negative under a corrected observation.** The policy loses to the optimized fixed
schedule in both arms, by 664 ± 64 and 1,469 ± 37 $ ha⁻¹, at ten and forty standard errors
respectively. Freezing the policy's own emitted plan and replaying it as a fixed schedule *improves*
it in both arms, by 115 ± 31 and 128 ± 35 $ ha⁻¹, so the value of adapting is negative rather than
merely absent. This strengthens the null of Section 3.4 in the two ways that section identified as
its own weaknesses: the engine budgets here are matched by construction rather than differing
thirty-fold, and the observation vector now carries the soil state a fertiliser policy would
condition on — nitrogen-stress and water-stress days, soil water, and a cumulative nitrogen-balance
residual — so "the policy had nothing to condition on" is no longer available as an explanation.

Nitrate leaching rises with applied nitrogen, from 40.3 kg ha⁻¹ in the capped arm to 49.3 in the
uncapped arm, against 10.9 for measured practice. As in Section 3.2 this is visible only because
the externality is reported separately rather than priced into the objective.

### 3.6 A baseline defect and what it invalidates

Sections 3.2 and 3.4 were produced before an error in the schedule generator was found, and are
superseded; they are retained here because the error is instructive and because the corrected
result reverses one of their conclusions.

Two defects compounded in the generated baseline against which every optimized arm was scored. The
generator wrote an irrigation application efficiency of 0.85 into each event it created, while all
158 measured events carry 1.00; and the baseline application depth integrated to 3,060 mm per
rotation against the measured 3,938.8 mm. Together these under-irrigated every generated schedule
by 22 % relative to the measured practice it was compared against. The consequences were not
confined to the water balance: alfalfa water-stress days rose to 65–100 and alfalfa yield fell
14–23 %, and because nitrogen uptake is water-limited, an arm attempting to relieve nitrogen stress
was penalised for it. The manure null reported in Section 3.2 — worth −2,094 $ ha⁻¹ against
measured practice, and interpreted there as uptake rather than supply binding — is an artefact of
this defect, and Section 3.5 shows the opposite once the baseline irrigates correctly.

After correction the generated baseline scores within **−127 ± 226 $ ha⁻¹** of measured practice on
held-out weather, that is, indistinguishable from it. Two regression tests now pin the properties
that failed silently: that a generated irrigation event carries the same efficiency as a measured
one, and that the baseline's applied depth matches the measured record to within 1 %.

The general point is that the baseline of a lever ablation is load-bearing in exactly the way the
levers are, and receives none of the scrutiny. A defect in a baseline does not announce itself as a
defect; it announces itself as a finding about whichever lever it happens to suppress. We report
the corrected comparison in Section 3.5 and recommend that any ablation baseline be validated
against the measurement it claims to reproduce, quantitatively, before arms are scored against it.

**Sections 3.2 and 3.4 require re-running under the corrected baseline.** Their qualitative
conclusions are differently exposed: the frozen-plan finding of Section 3.4 is reproduced and
strengthened by Sections 3.5 and 3.7 and does not depend on the defect, whereas the lever ranking
of Section 3.2 does — the `I` arm's apparent value was measured against a baseline that
under-irrigated, and the `M` arm's null is now known to be reversed.

### 3.7 Irrigation, and a false positive recovered by seed replication

The irrigation arm frees start day, interval and depth, independently for each of the seven years,
with all other dimensions at measured practice. It is the arm with the best a priori case for
adaptivity, since water is the input whose correct amount most obviously depends on weather. It was
run at the same 50,000-engine-run budget per method as Section 3.5 and, unlike that experiment,
with **three PPO seeds** sharing one CMA-ES row (Table 6).

**Table 6.** Irrigation arm, held-out weather. Row-to-row errors are paired across the seven
held-out windows; the seed row is the standard error across three PPO replicates.

| Row | Profit ($ ha⁻¹) | Irrigation (mm rotation⁻¹) | NO₃ (kg ha⁻¹) |
|---|---|---|---|
| Measured practice | 17,478 | 3,938.8 | 15.8 |
| Generated baseline | 17,351 | 3,938.9 | 8.6 |
| CMA-ES fixed schedule | **19,748** | 4,041.4 | 0.7 |
| PPO policy (median seed) | 19,583 | 4,092.5 | 4.7 |
| PPO policy's own plan, frozen | 19,668 | — | — |

| Comparison | Value ($ ha⁻¹) |
|---|---|
| Fixed vs generated baseline | +2,397 ± 250 |
| Fixed vs measured practice | +2,271 ± 395 |
| Policy vs fixed, median seed | −165 ± 83 |
| **Policy vs fixed, across three seeds** | **−47 ± 123** (+199, −177, −165) |
| **Adaptivity, across three seeds** | **−98 ± 27** (−59, −149, −85) |

**The lever pays through timing rather than volume.** The optimized schedule earns +2,397 $ ha⁻¹
over the baseline while applying 4,041 mm against 3,939, an increase of 2.6 % costing 42 $ ha⁻¹ of
water. What it finds is crop-relative scheduling: irrigation begins on day 146–148 for corn, which
is planted on day 136; on day 101–112 for barley, planted on day 99; and on day 100–117 for
alfalfa. The baseline's fixed day-130 start is approximately correct for corn and roughly a month
late for the other two crops, so the gain comes from not starting the barley and alfalfa seasons
dry, together with a redistribution of water toward the alfalfa stand. Because this is a
within-crop lever it falls on the interpretable side of the calibration bound of Section 4.1, and
because total applied water is nearly unchanged the result is close to insensitive to the water
price. Nitrate leaching falls to 0.7 kg ha⁻¹ against 15.8 for measured practice, the reverse of the
rotation arm's trade-off in Section 3.2.

**A single seed would have reported the opposite conclusion.** At seed 0 the policy beats the
optimized fixed schedule by 199 $ ha⁻¹ — a positive adaptivity result, and seed 0 is the seed every
earlier experiment in this study used. The two additional seeds return −177 and −165, and the mean
across three is −47 ± 123 $ ha⁻¹, that is, indistinguishable from zero. The headline is not a
property of the method at this budget; it is a property of the initialisation, and reporting it
from one run would have placed a false positive in the literature by the same mechanism, though not
the same route, as the budget asymmetry of Section 3.4.

**The frozen-plan control is stable where the headline is not.** Adaptivity is negative in every
seed, at −59, −149 and −85 $ ha⁻¹ (mean −98 ± 27), while the headline swings across a range of
376 $ ha⁻¹. Even the seed that beat the fixed schedule is beaten by its own frozen plan: it won by
locating a better constant schedule, not by adapting. Across the six arm-and-seed combinations
measured in Sections 3.5 and 3.7, adaptivity is negative in all six. The claim that survives
replication is therefore about adaptivity specifically, not about the policy's score, and it is the
control rather than the headline that carries it.

**The water price is not load-bearing here.** Because profit is linear in the water price and each
row carries its cost decomposition, the price at which the policy's advantage would vanish is exact
arithmetic on stored results. The policy applies 51 mm more than the fixed schedule while scoring
below it, so that breakeven is negative — approximately −2.82 $ mm⁻¹ ha⁻¹. No physically meaningful
water price makes the policy competitive, and raising the price above the 0.41 placeholder only
widens the gap. The null therefore holds independently of the placeholder that Section 3.4 showed
to be decisive for the earlier result. Absolute profit levels do still depend on it, since the
optimized and measured rows apply different quantities of water.

---

## 4. Discussion

### 4.1 Calibration state as a bound on interpretation

Reporting a single aggregate goodness-of-fit statistic for a multi-crop rotation model is actively
misleading when the errors are signed and crop-specific. At this site the aggregate PBIAS against
measurement is small, but it is small by cancellation: corn and barley are under-predicted while
alfalfa is unbiased. An aggregate figure would have licensed confidence in exactly the lever —
rotation — that the disaggregated figures show to be least trustworthy. Environment papers in this
area should therefore report per-crop and per-variable calibration state, together with the tier of
evidence each target represents: at this site five of the calibration variables exist only as
reference-model output, and treating them as measurements would overstate the supporting evidence
by a wide margin. The structural finding in Section 3.1 sharpens this into a limit rather than a
caveat — because the engine provides no mechanism to end a perennial's residency, per-crop
agreement within ±15 % is unreachable regardless of parameter values — and identifying that floor
is what makes the subsequent optimization results interpretable.

The bound is directional as well as cautionary. Within-crop bias displaces an agent's objective;
between-crop bias changes its ranking, so the rotation lever is the least interpretable under the
present calibration while the irrigation and nutrient levers, which operate within a crop, are
correspondingly safer. In one case this strengthens a result: the model is biased toward alfalfa
and the optimizer avoided alfalfa anyway, so the anti-alfalfa conclusion is robust in the direction
that matters. The nitrogen response illustrates the opposite case — corn is under-predicted, so an
optimizer rewarded for relieving corn nitrogen stress is rewarded partly for correcting the model.

### 4.2 Attributing an advantage

The frozen-plan control is inexpensive — one additional evaluation per window — and it reversed the
interpretation of the headline result in Section 3.4 completely. We suggest it should be standard.
A policy that ignores its observations still emits an action sequence; unless that sequence is
scored as a fixed plan, an advantage over a fixed-schedule baseline cannot be attributed to
adaptation. The budget asymmetry that produced the apparent advantage deserves equal attention
because it is easy to introduce without noticing: training a policy for 200,000 environment steps
and comparing it against a baseline optimizer given a few thousand evaluations compares two search
procedures at a thirty-fold difference in compute, and reports the difference as a difference in
kind.

Section 3.7 supplies a third requirement, and the cheapest of the three to satisfy. At seed 0 the
irrigation policy beats the optimized fixed schedule by 199 $ ha⁻¹; across three seeds the mean is
−47 ± 123. A single-seed comparison at this budget resolves nothing about the method, and seed 0 is
not a neutral choice — it is the default, and therefore the one a study is most likely to report.
Two properties of that episode are worth separating. The first is ordinary: policy-gradient
variance is well known, and the remedy is replication. The second is specific to this design, and
is the reason we report it rather than merely correcting it. The three controls are not
interchangeable, because they differ in how stable they are. The headline swung across 376 $ ha⁻¹
between seeds while adaptivity, measured by the frozen-plan control, was negative in every seed of
every arm we ran — six of six. A control that is stable across nuisance variation is worth more
than a headline that is not, and an experiment should be designed so that its claim rests on the
former. The claim this study can defend is that adaptivity does not pay here; the claim it cannot
defend, in either direction, is any particular margin between a policy and an optimizer.

Replication is also cheap if it is targeted. The fixed-schedule optimizer is the near-deterministic
half of the comparison and the policy is the stochastic half, so replicating only the policy — three
PPO runs against one shared CMA-ES row — buys the variance estimate that matters at roughly a third
of the cost of replicating the whole experiment.

Keeping externalities separable from profit proved to be worth its cost twice: once in Section 3.2,
where the profit-maximising rotations turned out to leach more than measured practice, and once in
Section 3.4, where the policy's advantage proved to rest on irrigating 56 % more than measured
practice at an unsourced water price. Neither would have been visible had both terms been folded
into a single scalar at a shadow price chosen for convenience.

### 4.3 Limitations

The model represents a single hydrologic response unit, one field and one soil, with no spatial
heterogeneity, and its decision cadence is forced to annual by the replay cost a simulator without
checkpoint-restart imposes — a genuine limitation relative to environments that can be stepped.
Barley biomass remains substantially below measured whole-plant dry matter, and the cause is
biomass accumulation rather than harvest index or plant-part definition. Humidity and wind are
generated rather than measured in both this model and the reference. The residual
evapotranspiration gap of approximately 11 % is unexplained and insensitive to every parameter
screened.

The calibration is under-identified: thirteen parameters were fitted against seven measured yield
observations, with the remaining objective terms derived from another model, and no held-out
validation was performed. Post-fit agreement figures are descriptive of the fit rather than
estimates of predictive skill, and a cross-validation design holding out one measured year at a
time is the minimum required before any agreement statistic is reported as skill.

The water and manure haulage prices are placeholders rather than sourced values, and both are now
known to be load-bearing rather than innocuous: Section 3.4 shows the policy's apparent advantage
does not survive a realistic pumping cost, and Section 3.5 shows that the uncapped nitrogen optimum
is determined by the manure haulage price, which sets the cost of nitrogen from manure at roughly a
quarter of the cost from urea and thereby decides source choice outright once the loading cap is
removed. A defensible manure price is a prerequisite for reporting any optimal nitrogen rate from
this environment. The haulage figure also prices only the cost of moving manure, not the agronomic
value of the nitrogen it carries, which is the accounting appropriate to a disposal stream and not
to a purchased input; whether that is the right framing for this region is a modelling choice we
have not defended.

Seed replication is uneven across experiments. The irrigation arm of Section 3.7 was run at three
PPO seeds; the nitrogen arms of Section 3.5 were run at one each, before the seed sensitivity
documented in Section 3.7 was known. The nitrogen null is reproduced across two independent arms at
ten and forty standard errors, and its adaptivity control is negative in both, so it is unlikely to
be a seed artefact of the kind Section 3.7 exhibits — the margins there are an order of magnitude
larger than the between-seed spread observed in the irrigation arm. It nonetheless remains a
single-seed result per arm and should be replicated before the margins, as opposed to the sign, are
quoted.

Three seeds is itself a small number. It is enough to establish that the irrigation headline is not
separable from initialisation noise, which is the claim we make from it, and not enough to estimate
the seed distribution or to support a formal test.

---

## 5. Conclusions

We construct a SWAT+ environment for a measured irrigated dairy-forage field and treat its
calibration as a reportable result rather than a preliminary. Reconciling inputs and correcting a
crop-type misassignment and a resident-perennial artefact brought per-crop yield bias to +0.5 %,
−17.9 % and −24.7 % against measurement, and identified a structural floor below which the present
engine cannot be improved. Because the residual is signed and crop-specific, the aggregate
statistic is cancellation rather than agreement, and the between-crop lever is correspondingly less
interpretable than the within-crop ones.

Within that bound, the levers separate cleanly by how far their results can be carried. The two
within-crop levers are interpretable and both pay. Nitrogen management is worth +3,900 to
+4,500 $ ha⁻¹ over measured practice, though its optimum is a shelf rather than a peak — tripling
applied nitrogen buys 2.6 % — so the defensible output is a response curve and not a rate.
Irrigation scheduling is worth +2,397 ± 250 $ ha⁻¹ on 2.6 % more water, earned by aligning
irrigation onset with each crop's planting date instead of a fixed calendar day, and it reduces
nitrate leaching rather than trading against it. The between-crop lever is the one the calibration
bound restricts, and it behaves accordingly: rotation moves the objective most, but the
profitability crossover between alfalfa and the annual crops falls inside three years of observed
price history, so the ranking is contingent on prices rather than agronomy. Profit-maximising
rotations also leach more nitrate than measured practice, which is visible only because the
externality was kept separable from profit.

On adaptivity the study returns a null and, more usefully, an account of what it takes to trust
one. A policy that appears to beat an optimized fixed schedule by 12.9 % on held-out weather is
shown by a frozen-plan control to have learned a near-constant program: the advantage is optimizer
budget, not adaptivity. Re-run at matched budgets, with carryover soil state in the observation and
across two arms, the policy does not beat the fixed schedule and is improved by freezing its own
plan, so the value of adapting is negative rather than merely absent. Adaptivity in agricultural
management should be treated as a hypothesis requiring a control, not as a property conferred by
using a sequential method.

The attribution protocol needs a third control alongside the frozen plan and the matched budget.
On the irrigation arm the default random seed returns a policy advantage of +199 $ ha⁻¹ and three
seeds return −47 ± 123, so a single-seed comparison at this budget would have reported adaptivity
paying where it does not. The frozen-plan control was negative in every seed of every arm — six of
six — while the headline margin swung across 376 $ ha⁻¹ between seeds of one arm. Where a study
must choose what to rest a claim on, the control that survives nuisance variation is worth more
than the margin that does not.

A final result concerns the baseline rather than the levers. A defect that under-irrigated the
generated baseline by 22 % relative to the measured practice it was scored against did not present
as a defect but as a finding, and specifically as a null for the nitrogen lever whose sign reverses
once corrected. Ablation baselines are load-bearing in exactly the way the levers are and receive
none of the scrutiny; we recommend validating a generated baseline quantitatively against the
practice it claims to reproduce before any arm is scored against it, and reporting it as a row of
the results table rather than as an implicit zero.

Future work should extend the environment to multiple fields and hydrologic response units, source
the water and manure prices that the results are now known to depend on, extend seed replication to
the nitrogen arms and beyond three seeds, re-run the rotation lever under the corrected baseline,
and validate the lever ranking by replaying the winning schedule through an independent simulator.

---

## Acknowledgements

*[to complete]*

## Data and code availability

The model, the environment, the calibration drivers and the experiment scripts are available at
*[repository URL to add]*. Input provenance for all 65 engine input files, the full
input-reconciliation table and the Morris screen results are recorded in the supplementary
material.

## References

*[To assemble in journal format. Core set below.]*

**Agricultural RL environments.** Overweg et al. (2021), *CropGym*, arXiv:2104.04326. Gautron et al.
(2022), *gym-DSSAT*, arXiv:2207.03270. Turchetta et al. (2022), *Learning Long-Term Crop Management
Strategies with CyclesGym*, NeurIPS Datasets & Benchmarks. *WOFOSTGym* (2025), arXiv:2502.19308.
AquaCrop-OSPy.

**Regional context.** U.S. Census Bureau population estimates for Idaho and Twin Falls County,
2020–2024. Snake River and Columbia Basin snowpack and runoff-timing literature *[select a primary
source]*. Richards, Brooks, Schott, Nouwakpo & Strawn, SWAT assessment of crop and nutrient
management in the Twin Falls Canal Company region *[journal version to locate]*. *Cycling
Phosphorus and Nitrogen through Cropping Systems in an Intensive Dairy Production Region*, Agronomy
11(5):1005 (2021). Idaho Department of Water Resources curtailment orders, Eastern Snake Plain
Aquifer. Idaho DEQ nitrate priority areas. Bierer et al. (2022), manure incorporation at the
Kimberly GRACEnet site.

**Models and methods.** Bieger et al. (2017) and Arnold et al. (2012), SWAT+ and SWAT. Herman &
Usher (2017), SALib. Allen et al. (1998), FAO-56 Penman–Monteith. Storn & Price (1997), differential
evolution. Hansen & Ostermeier (2001), CMA-ES. Schulman et al. (2017), PPO. USDA NASS, *Crop Values
2024 Summary*.
