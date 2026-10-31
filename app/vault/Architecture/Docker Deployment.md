---
tags: [architecture, deployment, docker]
aliases: [Docker, Containers, Deployment]
created: 2026-07-31
---
# Docker Deployment

AI-SWAT+ ships as **two containers** that run on any machine with Docker — no Windows, no manual SWAT+ install, no host paths.

```bash
docker compose up --build     # then open http://localhost:3000
```

| Service | Port | What it is |
|---|---|---|
| `swat-web` | http://localhost:3000 | React UI on nginx, proxies `/api` → backend |
| `swat-api` | http://localhost:8020 | FastAPI + the SWAT+ engine |

## The hard problem: a Windows-only engine

The project ships only `swatplus-62.0.0-gnu-win_amd64-Rel.exe`. A Windows binary **cannot run in a Linux container**, and the original compose file pointed at a Linux binary that never existed.

The [[Dockerfile]] therefore **compiles the engine from source** in a first build stage:

```dockerfile
FROM debian:bookworm-slim AS engine
RUN apt-get install -y gfortran cmake make git
RUN git clone --depth 1 --branch 62.0.0 https://github.com/swat-model/swatplus.git
RUN cmake --preset gfortran_release_linux && cmake --build build/release -j$(nproc)
```

CMake names the target `swatplus-62.0.0-gnu-lin_x86_64-Rel`; the build normalises it to `/opt/swatplus/swatplus`. All 648 Fortran files compile in well under a minute on a modern machine.

> [!tip] The Linux build is *more* robust than the Windows one
> The `gfortran_release_linux` preset omits `-ffpe-trap`, the flag that makes the Windows binary abort (exit 3) on floating-point edge cases. See [[Green-Ampt Infiltration]] for the crash class this affects.

[[SWAT+ Engine Integration|pySWATPlus]] is fully cross-platform: on Windows it wants `.exe` + an `MZ` header, on Linux merely an **executable ELF**, launched with plain `subprocess` (no wine).

## Image layout

Baked assets live at `/opt/ai-swat/`, deliberately **outside `/data`**, so the runtime volume can never shadow them.

| Path | Contents | Env var |
|---|---|---|
| `/opt/swatplus/swatplus` | compiled Linux engine | `SWATPLUS_EXE` |
| `/opt/ai-swat/rev62_template/TxtInOut` | base project for new fields | `REV62_TEMPLATE` |
| `/opt/ai-swat/a10_single_hru/…/TxtInOut` | demo support files | `DEMO_TXTINOUT` |
| `/opt/ai-swat/soils_db/ssurgo.sqlite` | optional gSSURGO soil | `SSURGO_SQLITE` |
| `/data` | farms, runs, SQLite DB (named volume `swat-data`) | `DATA_ROOT` |

## Persistence

Fields, model runs and the app database live in the named volume `swat-data` and survive rebuilds.

```bash
docker compose down        # stop, keep data
docker compose down -v     # stop and DELETE all fields/runs
```

## Configuration

Everything is environment-driven; copy `.env.example` → `.env`. **All of it is optional** — the image is self-contained, and LLM keys can also be set in the app's Settings page (persisted in the data volume, no rebuild needed). See [[Backend Launch]] for the local (non-Docker) equivalents.

## Requirements & limits
- **Outbound internet** is needed when building a field ([[gridMET Weather]] + elevation are fetched live).
- **gSSURGO needs a one-time conversion** — see [[gSSURGO Soil]].
- Uncalibrated single-field output stays **directional**; see [[Reliability and Confidence]].

## Related
[[SWAT+ Engine Integration]] · [[gSSURGO Soil]] · [[Backend Launch]] · [[2026-07-31 Docker packaging]] · [[Handover]]
