---
tags: [reference]
aliases: [Launch, DATA_ROOT, Run the servers]
created: 2026-07-27
---
# Backend Launch

How to start the servers. **⚠️ `DATA_ROOT` is mandatory** or every field vanishes.

## Backend (from `ai-swat/backend`)
```
DATA_ROOT="G:/AI-SWAT+ project/data" \
SWATPLUS_EXE="G:/AI-SWAT+ project/swatplus_bin/swatplus-62.0.0-gnu-win_amd64-Rel.exe" \
python -m uvicorn main:app --host 127.0.0.1 --port 8020 --log-level warning
```

> [!danger] Why DATA_ROOT matters
> `config.py` defaults `DATA_ROOT` to `/data`, and `db.py` puts the SQLite at `$DATA_ROOT/db/ai_swat.db`. The real farms DB lives at `G:/AI-SWAT+ project/data/db/ai_swat.db`. **Restarting uvicorn without `DATA_ROOT` points at an empty DB → `/api/farms` returns `[]` and every editor call 404s "Farm not found".** The farms aren't lost — the process is just reading the wrong file. Always relaunch with `DATA_ROOT` set.

- Runs **without `--reload`**, so any backend code edit needs a manual restart.
- `SWATPLUS_EXE` should stay **rev-62** ([[SWAT+ Engine Integration]]).

## Frontend
- Dev server: **Vite** (default 5173; a launch config uses 5182). API base is the absolute `VITE_API_URL=http://localhost:8020/api` (the Vite `/api` proxy is misconfigured to :8000, so the env URL is what's used).
- Packaged as Electron for desktop.

## Paths under `$DATA_ROOT`
`db/ai_swat.db` · `farms/{id}/TxtInOut` · `outputs/{run_id}/workspace/TxtInOut` · `gis/{id}/`. See [[Data Model]].

## Related
[[Backend Services]] · [[Data Model]] · [[Tech Stack]]
