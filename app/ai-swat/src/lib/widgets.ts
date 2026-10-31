// Generative-UI widget protocol (chat-native overhaul).
// The chat response carries a closed, typed `widgets[]` union plus a top-level
// canvas `phase`. P1 only populates `result-card`; interactive kinds (map-draw,
// form, file-upload, choice, swat-editor-panel…) are layered in later phases.
// See docs/UI_OVERHAUL_PLAN.md.
import type { ChatAnalysisCard, OutputConfidence } from '@/lib/api';

export type WidgetKind =
  | 'result-card' | 'chart' | 'table' | 'confidence'      // output-only
  | 'checklist' | 'progress' | 'file-browser'             // output-only
  | 'form' | 'map-draw' | 'file-upload' | 'field-picker'  // interactive
  | 'choice' | 'confirm' | 'swat-editor-panel';           // interactive

export type CanvasPhase = 'idle' | 'collecting' | 'running' | 'results' | 'error';
export type Placement = 'inline' | 'canvas';

export interface WidgetSubmitSpec {
  endpoint: '/api/interact';
  label: string;
  response_schema?: unknown;   // drives client validation before POST; re-validated server-side
}

export interface WidgetEnvelope<K extends WidgetKind = WidgetKind, P = unknown> {
  widget_id: string;           // == originating tool_call_id (interactive) or `card-${i}` (output)
  kind: K;
  placement: Placement;        // inline | canvas
  interactive: boolean;        // false = output-only
  title?: string | null;       // handoff-card label
  prompt?: string;             // farmer-facing helper text
  payload: P;                  // per-kind, schema-validated both ends
  submit?: WidgetSubmitSpec;   // present iff interactive
  confidence?: OutputConfidence | null;  // REQUIRED for result-card | chart | table
}

// Populated kinds (grows per phase). result-card carries today's ChatAnalysisCard verbatim.
export type ResultCardWidget = WidgetEnvelope<'result-card', ChatAnalysisCard>;

export type Widget = ResultCardWidget | WidgetEnvelope;
