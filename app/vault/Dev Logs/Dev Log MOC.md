---
tags: [moc, devlog]
aliases: [Dev Logs, Changelog]
created: 2026-07-27
---
# Dev Log MOC

Dated record of significant development work. Newest first.

## 2026-07-31
- [[2026-07-31 Auto-fertiliser and crop diagnostics]] — auto-fert built, temperature found limiting `#fix` `#science`
- [[2026-07-31 Advisor rotation tools]] — advisor can finally apply rotations + set run length `#fix` `#agent`
- [[2026-07-31 Docker packaging]] — two portable containers, engine compiled from source `#deployment`
- [[2026-07-31 gSSURGO on Linux]] — `.mdb` → SQLite, real soil everywhere `#data`

## 2026-07-30
- [[2026-07-30 Satellite basemap and light theme]] — satellite imagery on field maps, faded-UI fix `#ui`

## 2026-07-29
- [[2026-07-29 Run snapshots and compare]] — named scenarios, re-run, side-by-side, PDF `#feature`

## 2026-07-27
- [[2026-07-27 Crop rotation overlap fix]] — winter-wheat → alfalfa no longer grow simultaneously `#fix`
- [[2026-07-27 Readiness grounded-build fix]] — grounded builds no longer flagged "less accurate" `#fix`
- [[2026-07-27 Technical report and PDF]] — the report/walkthrough deliverable `#docs`

## 2026-07-24
- [[2026-07-24 Bulk field metadata extraction]] — 22-agent mine of the official editor `#editor`
- [[2026-07-24 Layered soils editor]] — nested `soils.sol` editor `#editor`
- [[2026-07-24 SWAT+ Editor structured forms]] — labelled record forms `#editor`
- [[2026-07-24 gridMET temp offset and Green-Ampt]] — data-integrity + cold-crash fixes `#fix` `#crash`

## Earlier (pre-vault, from project memory)
- Management now executes (single crop + `jday+year_rot` rotation), gridMET weather, gSSURGO soil per field.
- UI overhaul to a chat-native generative-UI app (chat + AI-summoned canvas + SWAT+ editor).
- Field-onboarding safety: new-field setup is deterministic; the agent never auto-creates/deletes fields.

## Related
[[Home]] · [[AI-SWAT+ Overview]]
