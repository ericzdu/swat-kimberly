---
tags: [devlog, deployment, docker]
created: 2026-07-31
---
# 2026-07-31 — Docker packaging

Packaged the whole stack into two portable containers, verified end-to-end. Full reference: [[Docker Deployment]].

## The blocker

The repo ships **only a Windows engine** (`swatplus-62.0.0-gnu-win_amd64-Rel.exe`), and the pre-existing `docker-compose.yml` mounted a Linux binary — `swatplus-gnu-lin_x86_64` — **that does not exist anywhere in the project**. It could never have worked.

**Fix:** a first build stage compiles the engine from official source (`swat-model/swatplus`, tag `62.0.0`) with the project's own `gfortran_release_linux` CMake preset. 648 Fortran files, ~15 s on 32 cores. Verified running natively:

```
SWAT+ Revision 62.0.0 — GNU (12.2.0), Linux
```

## Real bugs the container exposed

Containerising a project is a clean-room install, and it found dependency rot the dev machine was hiding:

- **`python-multipart` was missing from `requirements.txt`.** FastAPI raises at *import* time on the upload route, so uvicorn crash-looped. The Windows box had it installed incidentally — **any fresh install would have failed**.
- `requests`, `matplotlib` and `pillow` are imported directly by our code but were only arriving transitively. Now pinned.

## Verification (not just "it built")

| Check | Result |
|---|---|
| Both containers healthy | ✅ |
| UI :3000, API :8020, nginx `/api` proxy | ✅ all 200 |
| All 64 endpoints registered | ✅ every router imports |
| Field + boundary created | ✅ |
| gridMET weather fetched from container | ✅ |
| **Real SWAT+ run completed** | ✅ 4.4 t/ha, full water + nutrient balance |
| Snapshots, rename, re-run, timeline, editor, upload | ✅ |
| Frontend bundle has satellite basemap, snapshots, Save PDF | ✅ |

## Notes
- Assets are baked at `/opt/ai-swat/`, **outside `/data`**, so the runtime volume can't shadow them.
- `.dockerignore` keeps `data/`, `vault/`, `soils_db/`, `swatplus_bin/` and `node_modules` out of the build context.
- Verifying ELF magic with `head -c4 … | grep $'\x7fELF'` fails in `/bin/sh` (binary grep); use `od -An -tx1 -N4 … | grep -qi '^7f454c46'`.
- Docker Desktop's daemon can't be started from a non-interactive shell — the WSL VM boots but the npipe daemon needs the desktop session.

## Related
[[Docker Deployment]] · [[SWAT+ Engine Integration]] · [[2026-07-31 gSSURGO on Linux]] · [[Handover]]
