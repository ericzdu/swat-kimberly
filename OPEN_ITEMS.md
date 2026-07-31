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
7. Explain or bound the residual −11 % evapotranspiration gap.
8. Confirm co-authors and affiliations.
9. Full cluster runs for Exp 1–4 at production budgets (see EXPERIMENTS.md / CLAUDE.md).
   Smoke ceiling gate already shows +2,042 $/ha foresight value — proceed to PPO is justified.

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
