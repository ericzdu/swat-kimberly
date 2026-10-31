---
tags: [architecture, reference]
aliases: [API, Endpoints]
created: 2026-07-27
---
# API Reference

REST API on `127.0.0.1:8020`, grouped by router prefix.

## `/api/farms`
- `GET/POST/DELETE /{id}` — CRUD
- `POST /{id}/boundary` · `GET /{id}/boundary`
- `POST /{id}/fetch-and-build` — the deterministic build ([[Field Setup and Model Build]])
- `POST /{id}/fetch-online` · `POST /{id}/upload` · `POST /{id}/txtinout` · `POST /{id}/observed`
- `GET /{id}/readiness` · `GET /{id}/status` · `GET /{id}/dataset-status`
- `GET /{id}/insights` · `GET /{id}/soil`

## `/api/swat`
- `POST /run` — trigger a run (`SwatRunRequest`)
- `GET /runs/{id}` — status · `GET /runs/farm/{id}` — list
- `GET /runs/{id}/timeline` — the [[Run Timeline]] payload
- `GET /runs/{id}/files` · `GET /runs/{id}/download`
- `GET /validate/{id}` · `POST /metrics` · `POST /sensitivity` · `GET /engine`

## `/api/swat/editor`
- `GET /{id}/files` · `GET /{id}/file?name=…` · `POST /{id}/file`
- `GET /{id}/soil` · `POST /{id}/soil` ([[Layered Soil Editor]])

## `/api/chat`
- `GET/POST /sessions` · `GET /sessions/{id}` · `DELETE /sessions/{id}`
- `POST /interact` — the two-way widget loop ([[Agent and Widget Protocol]])

## Others
- `/api/data` — upload / txtinout / observed / copy-setup
- `/api/gis` — `GET /geocode`, boundary
- `/api/agent` — `GET /tools`
- `/api/system` — `GET /health`, `/providers`, `/settings`, `POST /keys`
- `/api/scenarios`, `/api/simulate` — scenario runs, HRU generation

## Related
[[Backend Services]] · [[Data Model]] · [[Run and Calibrate]]
