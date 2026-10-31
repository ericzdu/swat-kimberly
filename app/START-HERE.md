# AI-SWAT+ — Handover Package

A farmer-facing decision-support app that turns **one field** into a working, location-specific **SWAT+** hydrology model and lets a farmer interrogate it in plain language.

---

## Run it (one command)

```bash
docker compose up --build
```

Then open **http://localhost:3000**

The first build compiles the SWAT+ engine from source (a few minutes) — everything after that is cached. Nothing else to install: no Windows, no manual SWAT+ setup, no host paths.

| | URL | What |
|---|---|---|
| Web UI | http://localhost:3000 | the app |
| API | http://localhost:8020 | FastAPI + SWAT+ engine |

**Optional:** copy `.env.example` → `.env` and add an LLM key to enable the AI advisor (or set it later in the app's **Settings** page). Everything else works without it.

Full deployment guide: **`DOCKER.md`**

---

## Read the documentation

Open the **`vault/`** folder in [Obsidian](https://obsidian.md) (File → Open folder as vault). It's 49 linked notes covering features, architecture, domain science, and a dated development history.

Start with **`vault/Reference/Handover.md`** — how to run it, what's included, every known limitation, and what to do next. Then `Home.md` is the index.

The vault is plain Markdown, so it also reads fine in any editor or on GitHub.

---

## What's in this package

| Path | Contents |
|---|---|
| `ai-swat/src/` | React 18 + Vite + TypeScript frontend |
| `ai-swat/backend/` | FastAPI + LangGraph backend (55 Python modules) |
| `rev62_template/` | the rev-62 SWAT+ project every new field is built from |
| `a10_single_hru/` | demo project used by the GIS import path |
| `tools/convert_ssurgo.sh` | one-time gSSURGO soil database converter |
| `vault/` | **the Obsidian knowledge base — all development detail** |
| `report/` | technical report + rotation study (HTML + PDF) |
| `Dockerfile`, `docker-compose.yml` | the deployable stack |
| `DOCKER.md` | deployment guide |

**Not included** (regenerate or supply): `data/` runtime state, `node_modules/`, the 168 MB soil database, the Windows `.exe` engines (the container compiles a Linux engine from source).

---

## Enable real soil (optional, recommended)

Without this, fields build on a generic template soil rather than the actual soil under the field.

```bash
./tools/convert_ssurgo.sh /path/to/SWAT_US_SSURGO_Soils.mdb
docker compose up -d
```

The USDA "SWAT US SSURGO Soils" database isn't redistributed here — obtain it from USDA/SWAT and convert once (~7 min, runs inside Docker).

---

## The one thing to understand before using results

This is an **uncalibrated single-field model**. The absolute numbers are **not predictions**.

The valid use is **scenario comparison** — same field, same weather, one thing changed — and the whole app is built around that (run snapshots, side-by-side compare, confidence badges). `vault/Reference/Rotation Comparison Study.md` is a complete worked example.

⚠️ When comparing crop rotations, the simulation window must cover **whole cycles of each rotation**, or the comparison is silently meaningless.

---

## Known open items

- **Auto-fertiliser applies 0 N** — the decision table never triggers, so nitrogen-management advice isn't yet credible.
- **The "Download data for my area" (Open-Meteo/GIS) path** is built on an older SWAT+ revision and fails on rev-62 — use the standard gridMET field onboarding.
- Some legacy screens still use the old dark theme and look faded.

All of these, with root causes and suggested fixes, are in `vault/Reference/Handover.md`.
