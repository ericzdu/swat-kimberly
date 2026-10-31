---
tags: [feature]
aliases: [Advisor, Chat]
created: 2026-07-27
---
# AI Advisor

A **LangGraph ReAct agent** that answers plain-language questions about a field — and answers *from the model*, not from memory.

## What the farmer sees
A chat panel on the left; questions like *"Should I irrigate today?"* return a direct answer citing the field's real soil-moisture, ET and rainfall, plus a stated confidence. Starter chips suggest common questions.

## How it works
- The agent has tools grouped into **read data**, **analyse**, **visualise**, and **ask/act** (full list in [[Agent and Widget Protocol]]).
- It is constrained by its system prompt to **never state a chart value or model number without first calling a tool** to fetch it.
- It speaks in relative/directional terms ("nitrate loss would drop about a third"), never as absolute fact — enforcing [[Reliability and Confidence]] in prose.
- Answers render together with the [[Generative Canvas]]; results carry a confidence badge.

## Model
The configured LLM is **MiniMax-M3** (pluggable via `llm_service`). It is an *unreliable tool-caller* in polluted sessions — it can hallucinate values instead of calling tools — which motivated the hardened prompt and the structural [[Agent and Widget Protocol|widget protocol]]. A stronger model is a known upgrade path.

## Key tools (examples)
- `query_field_data`, `show_soil_profile` — read real values
- `run_irrigation_analysis`, `run_nitrate_analysis`, `run_fertilizer_analysis`, `run_yield_analysis`
- `show_chart`, `show_table` — build custom visuals

> [!warning] Guardrail
> The advisor never fabricates data. If a value isn't available it says so. See [[Reliability and Confidence]].

## Related
[[Generative Canvas]] · [[Agent and Widget Protocol]] · [[Run Timeline]]
