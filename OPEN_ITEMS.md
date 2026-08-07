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
