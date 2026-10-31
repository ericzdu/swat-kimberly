---
tags: [architecture]
aliases: [Backend, Services]
created: 2026-07-27
---
# Backend Services

FastAPI on `127.0.0.1:8020`, hosting the LangGraph agent and focused domain services under `backend/services/`. See [[Backend Launch]] to run it.

## Model build & data
| Module | Responsibility |
|---|---|
| `build_project_service` | Deterministic per-field build ([[Field Setup and Model Build]]) |
| `soil_service` | gSSURGO dominant soil → `soils.sol` ([[gSSURGO Soil]]) |
| `weather_service` | gridMET fetch + packed-short decode ([[gridMET Weather]]) |
| `management_service` | Flat schedule or `jday+year_rot` rotation ([[Crop Management and Rotations]]) |
| `data_download_service` | Online GIS/weather download + data manifest |
| `crop_service` · `field_setup_service` | Crop config, dataset-status resolution |

## Engine & outputs
| Module | Responsibility |
|---|---|
| `swat_service` | Orchestrates runs (`start_run`, status, metrics, sensitivity) |
| `pyswat_facade` | pySWATPlus driver: stage TxtInOut, run rev-62, validate |
| `run_timeline_service` | Parse `mgt_out.txt` + daily outputs → [[Run Timeline]] |
| `field_data_service` | Single source of truth for field values, latest run id |

## Editing, agent & trust
| Module | Responsibility |
|---|---|
| `swat_editor_service` | Read/write all TxtInOut files + edit metadata ([[Structured Record Forms]]) |
| `insights_service` | Thin markers → typed widgets ([[Agent and Widget Protocol]]) |
| `chat_service` · `chat_session_service` · `llm_service` | Agent loop, sessions, LLM provider |
| `confidence_service` | Input grounding → quality + confidence badge |
| `readiness_service` | Gate simulation; per-check warnings ([[Confidence and Readiness]]) |

## Related
[[Architecture Overview]] · [[API Reference]] · [[Data Model]] · [[Backend Launch]]
