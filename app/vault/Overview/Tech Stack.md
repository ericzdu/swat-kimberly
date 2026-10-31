---
tags: [architecture, reference]
aliases: [Stack]
created: 2026-07-27
---
# Tech Stack

## Frontend
- **React 18** + **Vite** + **TypeScript** + **TailwindCSS**
- **Recharts** — composed multi-series charts, lens toggles ([[Run Timeline]])
- **Electron** — desktop packaging
- Source: `ai-swat/src`. API base: `VITE_API_URL=http://localhost:8020/api`.

## Backend
- **FastAPI** + **uvicorn** on `127.0.0.1:8020`
- **LangGraph** ReAct agent; pluggable LLM via `llm_service` (MiniMax-M3 configured — an unreliable tool-caller, see [[Agent and Widget Protocol]])
- **pySWATPlus** — driver for the SWAT+ engine
- **SQLite** — `farms`, `simulations`, `messages`, `chat_sessions`, `settings` ([[Data Model]])
- Source: `ai-swat/backend`. Launch needs `DATA_ROOT` — see [[Backend Launch]].

## Engine
- **SWAT+ rev-62** (`swatplus-62.0.0-gnu-win_amd64-Rel.exe`), compiled Fortran
- rev-61 also available; both compiled with `-ffpe-trap` (SIGFPE = exit code 3) — relevant to [[Green-Ampt Infiltration]]

## Data sources
| Source | Use |
|---|---|
| USDA **gSSURGO** | dominant soil profile → `soils.sol` ([[gSSURGO Soil]]) |
| **gridMET** | daily precip & temperature ([[gridMET Weather]]) |
| **USGS NWIS** | observed flow for calibration ([[Run and Calibrate]]) |
| **USGS EPQS** | point elevation |

## Related
[[Architecture Overview]] · [[Backend Services]] · [[Backend Launch]]
