---
tags: [devlog, fix, agent]
created: 2026-07-31
---
# 2026-07-31 — Advisor rotation tools

Driving the [[AI Advisor]] end-to-end on a real request — *"corn 5 years then alfalfa 4 years, apply it and run"* — exposed **four bugs**, two of them silent science errors.

## Bug 1 — the advisor couldn't apply a rotation at all

It answered by calling `request_swat_editor` and telling the **farmer** to hand-build the schedule in `management.sch`. Its only crop tool was `save_farm_crop_settings(crop_type, planting_date)` — a single crop.

**Fix:** new `apply_crop_rotation(blocks, irrigation)` in `agent/tool_factory.py`. Blocks are `"crop:years"` strings, so the LLM can express any rotation in one argument:

```python
["corn:5", "alfalfa:4"]                            # 9-year
["corn:3", "potato:1", "sugarbeet:1", "wheat:1"]   # 6-year
```

A friendly alias map (alfalfa→`alfa`, sugar beet→`sgbt`, potato→`pota`, …) expands to one crop per year and calls `management_service.apply_management(crops=[…])`. `AGENT_SYSTEM` gained a rule: when the farmer describes a rotation, call this tool — never tell them to edit files by hand, and never claim it's applied unless the tool returned ok.

## Bug 2 — switching rotations silently kept the old crops `#crash-class`

Every rotation shares `tag = "rot"` → `comm = "rot_comm"`, and `plant.ini` was only written **`if comm not in ptxt`**. So applying a second rotation over a first kept the first one's crop list; the new crops never entered the plant community and never grew.

> This is why the earlier corn/potato/sugar-beet/wheat study came back **corn-only**.

**Fix** (`management_service.apply_management`): remove any existing block with that community name — match the line whose first token is `comm`, skip its `tok[1]` plant rows — then append the fresh one. Idempotent, so rotation switching works.

**Verified:** after switching R1→R2, `plant.ini` held exactly corn/pota/sgbt/wwht (alfa gone) and `mgt_out.txt` logged 20 corn / 6 potato / 6 sugar beet / 7 wheat harvests.

## Bug 3 — the run window was shorter than the rotation `#science`

The field was built for **3 years** while rotation 1 is **9**, so alfalfa (years 6–9) never happened: a corn-only run masquerading as a rotation comparison. Weather is only fetched for the built window, so widening the run dates isn't enough — the field must be rebuilt.

## Bug 4 — no tool to change the run length

Asked to extend to 18 years the advisor called `request_confirm`… with nothing behind it. **Fix:** `set_simulation_years(years)` → `build_project_service.build_field_for_farm(farm_id, {"sim_years": n})`, with a docstring warning that rebuilding **resets management**, so the agent re-applies the rotation afterwards.

## Result

One sentence now drives the whole chain:

```
set_simulation_years → apply_crop_rotation → start_swat_simulation → wait_for_simulation
```

Both rotations ran 18 years, were snapshotted, labelled and compared — see [[Rotation Comparison Study]].

> [!note] Still imperfect (not code bugs)
> The advisor's prose sometimes misreads units (quoting a daily snapshot as an 18-year average) and it offered to re-run a rotation that had already been run under the same setup. Trust the compare table over the chat narrative.

## Related
[[AI Advisor]] · [[Crop Management and Rotations]] · [[Rotation Comparison Study]] · [[Run Snapshots and Compare]]
