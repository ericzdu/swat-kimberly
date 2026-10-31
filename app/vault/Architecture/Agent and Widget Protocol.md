---
tags: [architecture]
aliases: [Widget Protocol, Agent]
created: 2026-07-27
---
# Agent and Widget Protocol

How the [[AI Advisor]] turns a question into a grounded answer plus canvas UI.

## The agent
A **LangGraph ReAct agent** (`chat_service` / `agent.py`) with a pluggable LLM (`llm_service`, MiniMax-M3). Its system prompt forbids stating a chart value or model number without first calling a tool.

## Tool catalog
| Group | Tools |
|---|---|
| **Read data** | `query_field_data` · `get_field_data_provenance` · `get_field_dataset_status` · `get_latest_farm_insights` · `get_current_farm_info` |
| **Analyse** | `run_irrigation_analysis` · `run_nitrate_analysis` · `run_fertilizer_analysis` · `run_yield_analysis` · `run_calibration_check` |
| **Visualise** | `show_chart` · `show_table` · `show_soil_profile` |
| **Ask / act** | `request_choice` · `request_confirm` · `request_crop_form` · `request_field_map` · `request_dataset_status` · `request_swat_editor` · `set_field_boundary_from_location` · `fetch_online_map_data` |

## The widget protocol (thin markers → backend-filled envelope)
The model emits only a **thin** marker; the **backend** — not the model — fills the full typed envelope from a field catalog and validates it (Pydantic on the server, Zod on the client). Every numeric widget carries a required `confidence` field, so honesty is structural.

```
model → show_chart("nitrate")            # thin marker only
  → insights_service.build_widgets()     # fills envelope from catalog
  → { kind:"chart", title, payload, confidence }   # typed + validated
  → canvas renders the widget
user edits/submits a widget
  → POST /api/interact  →  synthetic HumanMessage  →  agent re-runs
```

- `request_*` / `show_*` markers → `insights_service.build_widgets` → canvas widgets.
- The two-way loop reruns the existing `_run_with_agent` path (no ToolMessage injection — that path is broken against this codebase).

> [!warning] Model reliability
> MiniMax-M3 sometimes hallucinates values instead of calling tools in polluted sessions. Mitigations: hardened prompt + this structural protocol; a stronger model is the real fix. See [[AI Advisor]].

## Related
[[AI Advisor]] · [[Generative Canvas]] · [[Reliability and Confidence]]
