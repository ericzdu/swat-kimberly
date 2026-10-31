---
tags: [reference, handover, onboarding]
aliases: [Handover, Getting Started, README]
created: 2026-07-31
---
# Handover

Everything needed to run, understand and continue **AI-SWAT+**. Start here.

## 1. Run it (5 minutes)

```bash
docker compose up --build
```

Open **http://localhost:3000**. The first build compiles the SWAT+ engine from source (a few minutes); later builds are cached. Nothing else to install — see [[Docker Deployment]].

To use the AI advisor, add an LLM key to `.env` (copy `.env.example`) **or** set it in the app's Settings page. Everything else works without it.

## 2. What's in the box

| Path | What |
|---|---|
| `ai-swat/src/` | React 18 + Vite + TypeScript frontend |
| `ai-swat/backend/` | FastAPI + LangGraph backend |
| `rev62_template/` | the rev-62 SWAT+ project every field is built from |
| `a10_single_hru/` | demo project (support files for the GIS path) |
| `tools/convert_ssurgo.sh` | one-time gSSURGO `.mdb` → SQLite converter |
| `Dockerfile`, `docker-compose.yml` | the deployable stack |
| `DOCKER.md` | deployment guide |
| `vault/` | **this knowledge base** |
| `report/` | technical report + PDF |

Not shipped (regenerate or supply yourself): `data/` (runtime state), `soils_db/` (168 MB, see below), `node_modules/`, the Windows `.exe` engines.

## 3. First things to read
1. [[AI-SWAT+ Overview]] — what it is and who it's for
2. [[Architecture Overview]] — the three tiers
3. [[Docker Deployment]] — how it ships
4. [[Rotation Comparison Study]] — a full worked example of the app's purpose
5. [[Dev Log MOC]] — how it got here

## 4. Enable real soil (optional, recommended)

Without it, fields build on a generic template soil.

```bash
./tools/convert_ssurgo.sh /path/to/SWAT_US_SSURGO_Soils.mdb
docker compose up -d
```

The USDA `.mdb` is not redistributed here — obtain it from USDA/SWAT and convert once. Details: [[gSSURGO Soil]] · [[2026-07-31 gSSURGO on Linux]].

## 5. How to use the model honestly

> [!important] This is the single most important thing to understand
> Output is an **uncalibrated single-field model**. Absolute numbers are not predictions. The valid use is **scenario comparison** — same field, same weather, one thing changed — and the app is built around that ([[Run Snapshots and Compare]], confidence badges, [[Reliability and Confidence]]).

When comparing rotations, the run window **must cover whole cycles of each** or the comparison is silently meaningless. See [[Rotation Comparison Study]].

## 6. Known limitations & open items

> [!danger] The one blocker that matters
> **Grain crops are not filling, and temperature is the binding constraint.** Corn realises a
> harvest index of 0.018 against a parameterised 0.55; winter wheat 0.001 against 0.40. Root crops
> on the same field yield normally, so the defect is confined to grain fill. Meanwhile temperature
> stress binds on 27–35% of growing days while **nitrogen stress is exactly 0.000** — proven twice
> over (see [[Rotation Comparison Study]]). Until the crop parameters are revised, **absolute
> yields and nitrogen uptake are not quotable**, and no amount of fertiliser will help.
> Next step: apply the PI's crop-parameter reference to `tmp_opt` / `tmp_base`, the uptake
> fractions, and LAI where compensation is needed. Stomatal conductance is not adjustable.

| Item | Status |
|---|---|
| **Grain crops do not fill; temperature stress binding** | **open — top priority.** Needs the crop-parameter revision. |
| **Alfalfa stand declines** across its phase (2,254 → 354 → 581 kg/ha biomass) | **open** — perennial re-establishment; modelled as harvest-kill each cycle |
| Auto-fertiliser applied 0 N | **fixed** — the table was never attached; see [[Auto-Fertilisation]] |
| Potato / sugar beet yielded exactly 0 (harvested as `grain`) | **fixed** — now `tuber`; HI 0.57 / 0.53 |
| Switching rotations kept the previous crops | **fixed** — `plant.ini` community is now replaced, not skipped |
| Advisor could not apply rotations or change run length | **fixed** — see [[2026-07-31 Advisor rotation tools]] |
| Fertiliser rate takes **no soil-test credit** — ~60 kg N/ha above a soil-nitrate-adjusted rate | by design (matches AUTO_EFF), worth revisiting before rates are used as advice |
| **Open-Meteo / "Download data for my area" path** builds on a rev-61 base and breaks on rev-62 (malformed `hru-data.hru` from the GIS exporter) | **open** — use the gridMET onboarding instead ([[Field Setup and Model Build]]) |
| Base engine SIGFPEs on some post-2014 dates on Windows | mitigated — builds use the pre-2014 window; the Linux build omits `-ffpe-trap` |
| Legacy screens (Dashboard, Visualizations, Farm Management, Data Hub, Setup Wizard) still use the old dark theme and look faded | cosmetic |
| Advisor prose sometimes misstates units | trust the compare table; LLM-reliability context in [[AI Advisor]] |
| `yield_kgha` in run totals is the **best single harvest**, not a total or mean — unlike every other metric | reporting inconsistency, worth normalising |
| `POST …/label` rejects non-ASCII labels | minor |

## 7. Safety rules that matter

> [!danger] Field lifecycle
> New-field setup is **deterministic** — never let an agent auto-create or delete fields. Doing so previously produced stray farms and lost a field's data.

Runtime state lives in the `swat-data` volume; `docker compose down -v` **deletes all fields and runs**.

## 8. Where to go next

In priority order — each unblocks the next:

1. **Revise the crop parameters** for the five study crops (corn, alfalfa, potato, sugar beet,
   wheat) against the PI's parameter reference. Start with `tmp_opt` / `tmp_base`, since
   temperature is the binding stress, then the N and P uptake fractions (`frac_n_yld`,
   `frac_n_em/50/mat` and the P equivalents), then LAI where compensation is needed.
   **Do not touch stomatal conductance** — it is not adjustable here.
2. **Fix grain fill.** Root crops yield correctly while cereals do not, so investigate seed-pool
   accumulation on the `mgt_harvgrain` pathway specifically.
3. **Re-run the rotation comparison** — yields, uptake and fertiliser rates should finally cohere.
   Consider switching auto-fertilisation back to measured removal at that point.
4. Review alfalfa perennial re-establishment.
5. Migrate the GIS/Open-Meteo path to rev-62, or retire it in favour of gridMET onboarding.
6. Calibrate against observed data to move beyond directional output.

## Related
[[Docker Deployment]] · [[Rotation Comparison Study]] · [[Reliability and Confidence]] · [[Dev Log MOC]] · [[People and Provenance]]
