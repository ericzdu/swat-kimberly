---
tags: [domain]
aliases: [Readiness, Grounding]
created: 2026-07-27
---
# Confidence and Readiness

The two services that decide *whether* a field can be simulated and *how much* to trust its numbers.

## `readiness_service`
Emits per-check readiness (weather, **Farm map layers**, crop, model data) shown as warnings in the chat header; a check with status `warning`/`missing` triggers the "results may be less accurate" banner.

- **Grounded build recognition** — a `data_source` of `gssurgo_rev62` / `online` (with weather OK) counts as **verified map layers**, even without a downloaded-layer manifest. `_is_grounded_build()`. See [[2026-07-27 Readiness grounded-build fix]].
- A grounded build also writes a `data_manifest.json` (`verified: true`, accurate `sources`) so the check reports honest detail.

## `confidence_service`
`assess_field_data_and_confidence` → per-input quality + the confidence badge shown on results.
- `grounded_gis = gis_verified OR uploaded OR grounded_build`.
- **Guardrail:** per-layer quality stays gated by `ds_ready()`, so template-default layers (elevation/topography, which the gSSURGO build does *not* location-derive) read as *missing/none* and are **never overstated** — only soil + weather (the real datasets) read as grounded.

See [[Reliability and Confidence]] for the honesty stance this enforces.

## Related
[[Reliability and Confidence]] · [[Field Setup and Model Build]] · [[gSSURGO Soil]] · [[2026-07-27 Readiness grounded-build fix]]
