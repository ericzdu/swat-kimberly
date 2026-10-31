---
tags: [overview]
aliases: [AI-SWAT+, About]
created: 2026-07-27
---
# AI-SWAT+ Overview

**AI-SWAT+** is a farmer-facing application that provisions a genuine, location-correct **SWAT+** hydrology model for a single field, runs it across multiple seasons, and puts a language-model advisor in front of the results that can reference any input or output value and render it as a chart, table, or soil profile in a live canvas.

## The problem it solves
Conventional hydrology modelling is the domain of specialists. A farmer can't easily go from *"here is my field"* to *"should I irrigate this week, and how much nitrogen is leaving toward the groundwater?"* AI-SWAT+ closes that gap.

## The core loop
> [!abstract] Draw → Build → Simulate → Ask
> 1. **Draw** — name or draw the field boundary on a map.
> 2. **Build** — a real SWAT+ model is built from its soil, weather & rotation (see [[Field Setup and Model Build]]).
> 3. **Simulate** — the engine runs the field across multiple seasons (see [[SWAT+ Engine Integration]]).
> 4. **Ask** — the [[AI Advisor]] answers, citing the model's real numbers.

## Three surfaces
| Surface | What it is |
|---|---|
| [[AI Advisor]] + [[Generative Canvas]] | Chat-native advice with an AI-summoned canvas |
| [[Run Timeline]] | A scrollable, multi-year picture of what the model did |
| [[SWAT+ Editor]] | File-level inspection & tuning of the model |

## Design principles
- **Grounded, not guessed** — the agent never states a chart value or model number without calling a tool to fetch it.
- **Honest about uncertainty** — an uncalibrated single-field run is framed as a *directional scenario estimate*, never as fact (see [[Reliability and Confidence]]).
- **Deterministic build** — the same field + choices always produce the same model; field creation/deletion is never delegated to the LLM.

## By the numbers
- **69** SWAT+ input files per field model
- **55** files with labelled edit metadata (see [[Structured Record Forms]])
- **19** editor sections in [[Editor File Map|file.cio order]]
- **rev-62** SWAT+ engine, per-field builds

## Related
[[Architecture Overview]] · [[Features MOC]] · [[Tech Stack]] · [[People and Provenance]]
