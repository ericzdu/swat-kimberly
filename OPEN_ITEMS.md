# Open items before submission

Working checklist for PAPER.md. Not part of the manuscript.

1. Replace Section 3.5 with the completed nitrogen-arm result.
2. Locate the journal version of the Richards et al. Magic Valley SWAT study; the regional figures
   in Section 1.1 are presently cited from a summary rather than the paper.
3. Replace the population and snowpack claims in Section 1.1 with primary citations — the Census
   release and a peer-reviewed streamflow-timing source.
4. Source the water and manure haulage prices. Section 3.4 shows the water price is load-bearing.
5. Trace the provenance of the GRACEnet nitrogen-uptake figures: 2015 alfalfa reads 147 kg ha⁻¹
   against 607–667 from both models, suggesting the quantity is not comparable and should not be
   used as a target until resolved.
6. Confirm whether the reference model's barley yield is grain or whole-plant.
7. ~~Explain or bound the residual −11 % evapotranspiration gap.~~ **Superseded 2026-07-31.**
   Under rev 62 with `pet_co` calibrated to measured ETos the gap has changed sign and grown:
   actual ET is now **+17 %** against the reference model (835 vs 711 mm). See #11.
8. Confirm co-authors and affiliations.
9. Full cluster runs for Exp 1–4 at production budgets (see EXPERIMENTS.md / CLAUDE.md).
   **2026-08-28: `runs/exp1_ceiling.json` is not on disk.** The +836 ± 68 quoted below and in
   PAPER.md §6.2 has no surviving artefact — `runs/` is gitignored and only
   `exp1_ceiling_smoke.json` (+45, `gate_pass: false`, tiny budget) remains. The figure is
   currently unreproducible and must be regenerated before it is quoted; its ± was also a naive
   SE, which rule 7 no longer permits (re-run it and quote `se_ess`).
   Foresight gate at full budget, uncapped, 2026-08-06: **+836 ± 68 $/ha** on test
   (`runs/exp1_ceiling.json`), well clear of the 250 noise floor — proceed to PPO is
   justified, and a null for closed-loop control cannot be blamed on there being nothing
   to adapt to. (Superseded: the old +2,042 smoke figure, and the +713 capped figure.)
10. ~~**SWAT+ rev 62.0.0 port (2026-07-31):**~~ **Closed 2026-07-31.** Inputs reconciled
    against REF HRU `000140001` (`scripts/port_reference_params.py`, PROVENANCE §5g) and the
    provisional `pet_co = 0.81` replaced by **0.964**, calibrated against measured AgriMet
    grass-reference ETos (`scripts/calibrate_petco.py`, PROVENANCE §5h). PET bias +0.0 %;
    yield −9.8 % vs GRACEnet. What the pass exposed is now #11.

11. **The ET/PET ratio, and what it does to the leaching term.**
    > ⚠️ **Read the 2026-08-06 update below first — the percolation and `no3_rchg` figures in
    > this opening paragraph are superseded, and "`perco` is inert" is wrong.**

    With PET matched to
    measurement, the model evaporates 835 mm/yr against the reference model's 711, deep
    percolation is ~1 mm/yr against 72, and `no3_rchg` is ~0.02 kg/ha/yr. `perco` is inert
    across its full range, and `esco`/`epco`/the soil profile all already match REF exactly —
    so this is a **SWAT+ rev 62 vs SWAT2012 rev 693 engine difference**, not an input error
    (PROVENANCE §5h). Two things follow, and both need a decision before Exp 2:
    - The manuscript needs this stated as a port finding, with the ET/PET ratios (0.86 vs
      0.51) and the evidence that inputs are excluded as the cause.
    - `CLAUDE.md` rule 1 requires nitrate leaching reported alongside profit. At 0.02
      kg/ha/yr that column is zeros. Either resolve the ET gap first, or say explicitly in
      the paper that the model cannot resolve leaching at this site under rev 62.

    **Update 2026-08-06 — re-measured after the nitrogen refit; the second bullet is resolved,
    and the numbers above are stale.** `scripts/percolation_check.py`, artefact
    `runs/percolation_check.json`. The column is **not** zeros and `perco` is **not** inert:
    percolation is *threshold-behaved* in applied water, which is correct agronomy, not a
    broken pathway. Scaling the measured schedule:

    | applied mm | perc mm/yr | NO₃ kg/ha/yr | implied mg/L |
    |---|---|---|---|
    | 2,363 (×0.6) | 0.00 | 0.00 | — |
    | 3,151 (×0.8) | 0.00 | 0.00 | — |
    | 3,939 (×1.0) | 9.40 | 1.69 | 17.9 |
    | 4,727 (×1.2) | 96.54 | 14.08 | 14.6 |
    | 5,366 (×1.4) | 141.17 | 29.08 | 20.6 |
    | 5,778 (×1.6) | 162.17 | 42.94 | 26.5 |

    Below ET demand nothing drains; above it, drainage and nitrate rise together at a
    **physically plausible 13.6–26.5 mg/L** in every row that drained — above the 10 mg/L
    drinking-water standard, which is the concern motivating the paper. ET/PET is **0.66–0.70**
    at measured practice against the 0.86 recorded above, and PET is 1,165 mm/yr.

    > ⚠️ **Re-measured 2026-08-28 and the table above no longer reproduces.** Same script,
    > same command, current model (`runs/percolation_check.json`):
    >
    > | applied mm | perc mm/yr | NO₃ kg/ha/yr | implied mg/L |
    > |---|---|---|---|
    > | 2,363 (×0.6) | 0.00 | 0.00 | — |
    > | 3,151 (×0.8) | 0.00 | 0.00 | — |
    > | **3,939 (×1.0)** | **0.00** | **0.00** | **—** |
    > | 4,727 (×1.2) | 16.08 | 1.22 | 7.6 |
    > | 5,366 (×1.4) | 76.82 | 8.28 | 10.8 |
    > | 5,778 (×1.6) | 117.11 | 27.49 | 23.5 |
    >
    > The threshold has moved out past ×1.2: **at measured practice and at the generated
    > default the leaching column is now exactly zero**, where the 2026-08-06 table recorded
    > 9.40 mm and 1.69 kg N/ha. Implied concentrations are 0.0–23.5 mg/L rather than
    > 13.6–26.5. The five measured test windows give 16.01 / 0.10 / 0.33 / 0.00 / 5.71 mm,
    > so the between-window sparsity noted below is worse than recorded, not better.
    >
    > The drift is not the rule 11b reconciliation of 2026-08-28 (which barely moved these
    > rows — corn's years are not the draining ones). It predates it and its cause is not
    > established; the most likely candidate is `alfa.bm_e` reverting 12.25 → 17.0, which
    > grows more alfalfa, transpires more and drains less. **Whatever the cause, no
    > sustainability claim may cite the superseded numbers, and the λ_n frontier now separates
    > arms only where an arm over-irrigates by ≥ 20 %.**

    **Consequence:** the leaching column is usable for *within-model ranking* and can carry the
    λ_n frontier. It is still **not validated against measurement** at this site, so magnitudes
    are not field claims — that part of the finding stands. One caveat for uncertainty: at
    measured practice the signal is **sparse across windows** (2.40 kg/ha/yr in the 2013-start
    window, ~0 in the other four), so leaching differences will have high between-window
    variance.

    **Update 2026-07-31 — there is now a measurement, and it does not rescue the column.**
    The seven-year April soil-nitrate profile on this field is extracted and scored
    (PROVENANCE §5i, `scripts/n_trajectory.py`). It confirms the nitrogen side is off in the
    same direction as the water side: at the ported `orgn_min = 0.0010` the model mineralises
    54 kg N/ha/yr against 117 for the reference on this field and 210 measured by buried bag
    nearby, because the SWAT2012 sweep that chose 0.0010 does not transfer to rev 62. That is
    fittable and is now fitted. What is *not* fittable is the alfalfa half: SWAT makes soil
    nitrate and legume fixation strict substitutes, so the measured pool rise of +29 and +117
    kg/ha under alfalfa cannot be reproduced at any parameter setting. **The choice in the
    second bullet is therefore narrower than it looked** — leaching cannot be validated here
    even with the nitrogen cycle refitted, so the paper needs the explicit statement.

12. **`rsd_decomp` is inert and manure organic N never enters the fresh-residue pool.**
    `rsd_nitorg_n` is exactly 0.000 in all seven years and a full 0.05 → 0.80 sweep changes
    nothing, while the ArcSWAT reference routes 24–164 kg N/ha/yr through that pathway
    (PROVENANCE §5i). The obvious explanation has been **tested and ruled out**: tagging all
    four `gn*` rows `fresh_manure`, as the built-in `dairy_fr` is, changes nothing to the digit
    — there is no `pathogens.pth` in the tree and the pathogen module is off in `codes.bsn`, so
    the column is inert. What remains is that rev 62's `fert` operation routes organic N
    straight to the humus pool irrespective of fertiliser type. **Open:** worth confirming
    against the rev 62 source before the paper attributes the whole mineralisation shortfall to
    an engine difference, since this is a specific and checkable mechanism for it.

## Moved to supplementary material

Cut from the manuscript during length reduction; these need to exist in the supplement before
submission.

- Full input-reconciliation table (10 rows: `orgn_min`, soil profile, initial soil nitrate/labile P,
  barley harvest index, solar radiation, weather generator station, bulk density, manure
  incorporation, containing-object areas, simulation window) with prior value, reconciled value and
  basis for each.
- Morris screen setup: the 17 parameters, their agronomic bounds, and the four dropped as inert
  (`n_uptake`, `n_perc`, corn `tmp_opt`, `esco`).
- Before/after reconciliation table (PET, ET, per-crop yield, NO₃ leached).
- The two silent SWAT+ rev 60.5.7 engine behaviours: standalone `kill` is ignored (the combined
  `hvkl` is required, else the 2017 alfalfa stand survives into 2018 and the nominal corn harvest
  returns 155 t ha⁻¹ of alfalfa); and `op_data3` on a `plnt` operation is not a potential-heat-unit
  override — setting it terminates the engine, so heat units derive from `days_mat`.
- Runner correctness properties and regression tests (no stale reads, no cross-run leakage,
  dynamics preservation via write whitelist; the 2018-corn-stressed / 2016-alfalfa-unstressed
  property test).
- Object-area performance trap: correcting containing-object areas made every execution path
  approximately 3× faster, the engine having routed flow through a 1,432 ha channel network for a
  1 ha field.


13. **Methodology fixes applied 2026-08-28** (all pinned by tests in `test_focused.py`):
    - `exp4_joint` computed a composed warm start, recorded `"warm_start": true`, and passed
      nothing to the optimizer — `run()` took no start point. The search ran cold while the
      artefact claimed otherwise, which is precisely the reading rule 8 depends on. `run()` now
      takes `x0`, threads it into CMA-ES, and puts it in the checkpoint key so a cold partial
      cannot be resumed into a warm run.
    - `--max-n` had a silent default of 400 in `_focused.run` and in `exp3_rotation`'s
      `evaluate()` calls, while Exp 1 forced `None`. The cap binds on `DEFAULT_PLAN` itself, so
      Exp 3/4 were simulating a different fertiliser regime from Exp 1's baseline and composing
      them would have repeated the capped/uncapped class of error one level up. The flag is now
      required, recorded in every artefact, and checked before Exp 4 warm-starts.
    - Reported uncertainty was `sd/√5` over the five overlapping test windows, which rule 7
      forbids. `paired()` now returns `se_ess` (ESS = 1.25 from `windows.effective_n`),
      `se_naive`, a deterministic percentile bootstrap CI and an ESS-normal CI, and no longer
      has a key called `se`.
    - Exp 3 ranked rotations on a scalar profit at λ_n = 0, so the winner could be re-scored
      but never re-selected at another nitrate price. Each sequence now stores its separable
      train means, and the artefact carries a `no3_frontier` — the winning rotation at every λ
      in the grid, exact, with no extra engine runs.
    - `rerun_exp1.sh` re-ran the λ_n-independent foresight gate for every frontier point, and
      left "do not start PPO if the gate fails" to the operator. It now reuses one gate and
      exits 2 on `gate_pass: false` unless `FORCE_PPO=1`.


14. **The corn N-stress premise has tripped (2026-08-28).**
    `tests/test_fastrunner.py::test_corn_is_n_stressed_and_alfalfa_is_not` asserts 2018 corn
    runs > 20 days of nitrogen stress, and its docstring says a trip "means the annual/perennial
    N asymmetry Exp 1 is premised on has stopped holding, which wants investigating (and
    re-premising Exp 1), not relaxing." Restoring corn's workbook parameters under rule 11b took
    2018 corn from **20.8 → 5.2** days and 2013 corn from 7.8 → 0.6: the smaller book `bm_e` and
    `lai_pot` grow less corn, which demands less nitrogen. The asymmetry still holds through
    barley (2019 = 35.7 days, alfalfa = 0 in all three years), but corn no longer carries it.
    **Resolved 2026-08-28: the workbook values stand, having been separately validated, so
    corn's 20 d cannot return by any legitimate route.** The test was therefore *re-premised*,
    not relaxed — the floor is now asserted on the annual crops collectively (barley carries it
    at 35.7 d) and alfalfa's zero is checked across all three of its years, with corn's own
    value kept as a ceiling to catch the opposite drift. Renamed
    ``test_annuals_are_n_stressed_and_alfalfa_is_not``.

15. **`pet_co` stays at 0.964 — decided 2026-08-28, do not re-litigate.**
    The prescribed ET protocol (remove nutrient stress → fit canopy → PET last) was executed in
    full against a regional OpenET per-crop benchmark. Every step is recorded in
    `scripts/et_nostress.py` and `scripts/et_gap_check.py`, with artefacts under
    `runs/et_*.json`. It does **not** justify moving `pet_co`, for four measured reasons:

    - Nitrogen accounts for none of the gap. At the minimal no-stress rate (600 kg N/ha/season
      on the annuals) biomass rises up to 50 % and annual ET moves **< 0.4 %**.
    - Canopy accounts for none of it. `lai_pot` ×2 and `esco` across its whole range each move
      the crop coefficient by **≤ 0.02**, because realised peak LAI is already 3.9–4.6, past
      SWAT's LAI ≥ 3 transpiration saturation.
    - A quarter to two-fifths of the gap is **water supply, not the model**: attaching
      `irr_str9_unlim` lifts alfalfa's Kc 0.81 → 0.90 and corn's 0.86 → 0.91. The benchmark
      fields were irrigated more than this one; that is management and must not be calibrated
      away.
    - On the corrected model no single value fits: at the flat optimum (1.10–1.20) corn stays
      4–10 % short while barley overshoots 9–13 %. Corn's residual is a *growth* deficit under
      the validated workbook parameters (yield −24.6 %), and absorbing it into PET is exactly
      the error PROVENANCE §5h documents. Applied to the shipped model, `pet_co = 1.15` does not
      even raise ET (840 → 844 mm, because irrigation is fixed) — it converts demand into water
      stress (10.7 → 27.3 d) and pushes the already-zero leaching column further out.

    **What to write instead of a fitted value:** in-crop ET is 11–31 % below the regional
    benchmark, decomposed as above, reported as a quantified limitation. The benchmark is 21
    *different* Magic Valley fields in 2020–22 with its own 10–20 % field-scale uncertainty, so
    it bounds the bias rather than validating this field.
