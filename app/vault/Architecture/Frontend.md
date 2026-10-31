---
tags: [architecture]
aliases: [UI, Client]
created: 2026-07-27
---
# Frontend

A chat-native single-page app. **React 18 + Vite + TypeScript + Tailwind + Recharts**, also packaged as an Electron desktop app. Source: `ai-swat/src`.

## Surfaces / routes
- `/` — the **Advisor**: chat panel (400 px, left) + the AI-summoned [[Generative Canvas]] (main stage). App nav is a slim 64 px icon rail (`Sidebar.tsx`).
- `/editor` — the [[SWAT+ Editor]] (`pages/SwatEditor.tsx`), scoped light theme via `--se-*` CSS vars.
- `/settings` — provider keys & config.

## Key components
| Component | Role |
|---|---|
| `Chat.tsx` | split-pane workspace; canvas render; `handleWidgetSubmit` → `chat.interact` |
| `components/widgets/*` | ChartWidget, TableWidget, ChoiceWidget, ConfirmWidget, … |
| `RunTimeline.tsx` | the [[Run Timeline]] (verdict, stat cards, lens toggle, spine, charts) |
| `FileTableEditor.tsx` | list ↔ [[Structured Record Forms|form]] editing |
| `RecordForm.tsx` | labelled-field record editor |
| `SoilEditor.tsx` | the [[Layered Soil Editor]] |
| `RunPanel.tsx` | [[Run and Calibrate]] |
| `swatEditorNav.ts` | the 19-section nav ([[Editor File Map]]) |

## API client
`src/lib/api.ts` — typed clients (`swatEditor`, `swatModel`, `chat`, `gis`, …). Base `VITE_API_URL=http://localhost:8020/api`. `http()` sends `cache: 'no-store'` so edits/runs never show a stale response.

## Gotchas
- Browser automation needs `127.0.0.1`, not `localhost` (IPv6 `::1` mismatch).
- Recharts `ReferenceLine`/`ReferenceDot` need a matching `yAxisId` + resolvable `x` or they unmount the tree.

## Related
[[Architecture Overview]] · [[Backend Services]] · [[Generative Canvas]]
