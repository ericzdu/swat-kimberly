---
tags: [architecture, reference]
aliases: [Database, Storage]
created: 2026-07-27
---
# Data Model

State is a small **SQLite** database plus the on-disk SWAT+ projects.

## SQLite tables (`backend/db.py`)
| Table | Holds |
|---|---|
| `farms` | fields and their setup state |
| `simulations` | run records & status |
| `messages` | advisor conversation (with widget JSON) |
| `chat_sessions` | per-field conversations |
| `settings` | provider keys & app config |

DB path: `$DATA_ROOT/db/ai_swat.db` (see [[Backend Launch]]).

## The `farms` record
`id`, `name`, `location`, `soil_type`, `txtinout_path`, `data_source`, `setup_complete`, `created_at` (+ `crop_type`, `planting_date`).

- `data_source` values: `gssurgo_rev62` (deterministic build), `online` / `online_verified`, `upload` / `upload_verified`, `demo`.

## On-disk projects
- Each field owns a `TxtInOut` folder of ~69 input files at `$DATA_ROOT/farms/{id}/TxtInOut` ([[SWAT+ File Model]]).
- Every run executes against an **isolated copy** under `$DATA_ROOT/outputs/{run_id}/workspace/TxtInOut`, so a crash or a bad parameter never touches the source model.
- GIS/boundary and the data manifest live under `$DATA_ROOT/gis/{id}/`.

## Related
[[Backend Services]] · [[API Reference]] · [[Backend Launch]] · [[SWAT+ File Model]]
