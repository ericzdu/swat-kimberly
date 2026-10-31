---
tags: [devlog, ui, maps]
created: 2026-07-30
---
# 2026-07-30 — Satellite basemap + light-theme fixes

## Satellite imagery on every field map

Farmers recognise their fields **from the air**, not from a street map. New `components/MapBasemap.tsx` is a drop-in replacement for a bare `<TileLayer>` with a built-in **Map / Satellite** toggle rendered as a Leaflet control:

- **Satellite** = Esri World Imagery **+ a place/road label overlay** (a hybrid view, so towns and roads still read on the imagery)
- **Map** = OpenStreetMap
- **No API key** for either source
- `defaultLayer="satellite"` — the useful default for drawing a boundary

Wired into all three field maps — the chat canvas draw widget, [[Field Setup and Model Build|guided setup]], and the Maps page — each bumped to `maxZoom={19}` so you can get tight on one field. The toggle calls `L.DomEvent.disableClickPropagation`, so tapping it never drops a boundary corner.

## Faded UI — legacy dark theme on a light app

The Maps page rendered washed-out and half-invisible. Cause: the app moved to a **light theme** (`--se-*` tokens on `:root`), but `/gis` was still written for the **old dark theme** — `text-white/40`, `bg-white/5`, `border-white/10`, plus `moss-`/`earth-` palette colours. White text at 40 % opacity on a white panel.

Converted the whole page to the design tokens: text → `--se-text` / `--se-text-mut` / `--se-text-fnt`, borders → `--se-border`, primary buttons → `--se-accent`, status blocks → the `ok`/`warn`/`error` triads. The over-map hint became a `--se-card` pill so it reads on satellite imagery.

> [!note] Same cause elsewhere
> Other legacy screens not in the main nav (Dashboard, Visualizations, Farm Management, Data Hub, Setup Wizard) were built the same way and will look faded until converted the same way.

## One-click field creation

The boundary is the only thing genuinely required — everything else has a sensible default. Step 1 of guided setup now offers **"Create field"** (saves the boundary and builds immediately with defaults: corn silage, gSSURGO soil, gridMET weather) alongside **"Customize setup"** for the optional crop/manure/irrigation/length steps.

## Related
[[Field Setup and Model Build]] · [[Frontend]] · [[Generative Canvas]]
