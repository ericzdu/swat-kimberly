import type { Widget, CanvasPhase } from '@/lib/widgets';

// ---- Types ----
export interface Farm {
  id: string;
  name: string;
  location?: string;
  soil_type?: string;
  txtinout_path?: string;
  setup_complete?: number | boolean;
  data_source?: string;
  crop_type?: string;
  planting_date?: string;
  created_at: string;
}

export interface CropOption {
  id: string;
  label: string;
}

export interface CropSettings {
  farm_id: string;
  crop_type: string;
  crop_label: string;
  planting_date: string;
  configured: boolean;
  setup_path: string;
  options: CropOption[];
  message?: string;
  ok?: boolean;
}

export interface FieldDatasetItem {
  ready: boolean;
  detail: string;
}

export interface FieldDatasetStatus {
  ok: boolean;
  farm_id: string;
  farm_name?: string;
  location?: string;
  ready_to_simulate: boolean;
  setup_complete: boolean;
  datasets: Record<string, FieldDatasetItem>;
  missing: string[];
  maps_url: string;
  setup_url: string;
}

export interface AutoSetupResult {
  ok: boolean;
  message?: string;
  error?: string;
  farm_name?: string;
  ready_to_simulate?: boolean;
  setup_complete?: boolean;
  datasets?: Record<string, FieldDatasetItem>;
  steps?: unknown[];
  maps_url?: string;
  setup_url?: string;
}

export interface InboxFileInfo {
  path: string;
  name: string;
  size: number;
  role: string;
  confidence: string;
  detail: string;
}

export interface InboxInspectResult {
  ok: boolean;
  farm_id: string;
  inbox_dir: string;
  files: InboxFileInfo[];
  summary: {
    total_files: number;
    roles: Record<string, number>;
    has_complete_txtinout: boolean;
    can_build_from_gis: boolean;
    missing_for_gis_build: string[];
  };
}

export interface InboxUploadResult {
  ok: boolean;
  saved_as: string;
  file_count: number;
  summary?: InboxInspectResult['summary'];
  message?: string;
}

export interface InboxImportResult {
  ok: boolean;
  message?: string;
  error?: string;
  placed?: Record<string, string>;
  sources?: string[];
  hru_count?: number;
  steps?: unknown[];
  ready_to_simulate?: boolean;
  readiness?: FarmReadiness;
}

export interface ReadinessCheck {
  id: string;
  label: string;
  status: 'ok' | 'missing' | 'warning' | 'optional';
  detail: string;
}

export interface SetupGuideStep {
  id: string;
  title: string;
  detail: string;
  action: string;
}

export interface SetupGuide {
  next_step?: SetupGuideStep | null;
  steps: SetupGuideStep[];
  has_boundary?: boolean;
  quick_options?: string[];
}

export interface FarmReadiness {
  farm_id: string;
  farm_name?: string;
  setup_complete?: boolean;
  data_source?: string;
  ready_to_simulate: boolean;
  block_reason?: string;
  checks: ReadinessCheck[];
  last_run?: { run_id: string; status: string; completed_at?: string };
  simulation_period?: { begin: string; end: string; source?: string };
  setup_guide?: SetupGuide;
}

export type ConfidenceLevel = 'high' | 'moderate' | 'low' | 'directional' | 'unavailable';

export interface OutputConfidence {
  level: ConfidenceLevel;
  label?: string;
  note?: string;
}

export interface FieldConfidence {
  farm_id: string;
  farm_name?: string;
  data_source?: string;
  ready_to_simulate?: boolean;
  provenance?: { uploaded_swat_project?: boolean; weather_real?: boolean; gis_verified?: boolean };
  calibration_state?: 'uncalibrated' | 'observed_available_not_calibrated' | 'calibrated';
  inputs?: { id: string; present: boolean; quality: string; source?: string; detail?: string }[];
  outputs?: { id: string; label: string; confidence: ConfidenceLevel; can_produce: boolean; basis?: string }[];
  can_produce_now?: string[];
  data_to_improve?: { id: string; ask: string; improves: string[]; how: string; priority?: number }[];
  overall_confidence?: ConfidenceLevel;
  headline?: string;
}

export interface InsightItem {
  headline: string;
  severity: 'ok' | 'warning' | 'critical' | 'missing';
  detail: string;
  advice?: string;
  confidence?: OutputConfidence;
}

export interface FarmInsights {
  farm_id?: string;
  farm_name?: string;
  has_data: boolean;
  irrigation: InsightItem;
  fertilizer: InsightItem;
  nitrate: InsightItem;
  drought_risk: InsightItem;
  yield: InsightItem;
  last_run?: { run_id: string; status: string; completed_at?: string };
  readiness?: FarmReadiness;
  confidence?: FieldConfidence;
  run_output?: {
    water_balance?: WaterBalance;
    nutrient_balance?: NutrientBalance;
    nitrate?: NitrateBalance;
    nitrate_monthly?: NitrateMonthlyPoint[];
    yield_kgha?: number;
    daily_series?: DailyPoint[];
  };
}

export interface WaterBalance {
  precip_mm: number;
  et_mm: number;
  runoff_mm: number;
  deep_perc_mm: number;
  soil_moisture_mm: number;
}

export interface NutrientBalance {
  nitrogen_kgha: number;
  phosphorus_kgha: number;
}

export interface StreamNitrate {
  no3_load_kg_yr: number;
  mean_no3_mgL: number | null;
  limit_mgL: number;
}

export interface NitrateBalance {
  leached_to_groundwater_kgha: number;
  surface_runoff_kgha: number;
  lateral_flow_kgha: number;
  tile_drain_kgha: number;
  sat_excess_kgha?: number;
  total_no3_loss_kgha: number;
  stream?: StreamNitrate;
  limit_mgL: number;
}

export interface NitrateMonthlyPoint {
  month: number;
  month_label: string;
  no3_load_kg: number;
  no3_mgL: number | null;
  flow_m3s?: number;
}

export interface DailyPoint {
  date: string;
  precip_mm: number;
  et_mm: number;
  soil_moisture_mm: number;
}

// Field-specific choices the setup wizard collects (Galen defaults fill any gaps).
export interface FieldSetupOptions {
  rotation?: { years: number; crops: string[] };
  manure?: { year: number; month: number; amount_kg_ha: number }[];
  irrigation_tier?: 'high' | 'medium' | 'low';
  sim_years?: number;
}

export interface ScenarioResult {
  run_id: string;
  status: string;
  scenario: string;
  advice: string;
  output_summary: Record<string, unknown>;
  insights: FarmInsights;
  charts: {
    water_balance?: WaterBalance;
    nutrient_balance?: NutrientBalance;
    nitrate?: NitrateBalance;
    nitrate_monthly?: NitrateMonthlyPoint[];
    daily_series?: DailyPoint[];
    yield_kgha?: number;
  };
}

export interface ChatAnalysisCard {
  type: 'irrigation' | 'fertilizer' | 'nitrate' | 'yield';
  headline: string;
  severity: 'ok' | 'warning' | 'critical' | 'missing';
  verdict?: 'yes' | 'soon' | 'no' | 'info' | 'unknown' | 'high' | 'moderate' | 'low';
  recommendation: string;
  detail?: string;
  advice?: string;
  explanation?: string;
  water_balance?: WaterBalance;
  nutrient_balance?: NutrientBalance;
  nitrate?: NitrateBalance;
  nitrate_monthly?: NitrateMonthlyPoint[];
  yield_kgha?: number;
  confidence?: OutputConfidence;
}

export interface ChatResponse {
  response: string;
  session_id?: string;
  simulation_id?: string;
  created_farm_id?: string;
  provider?: string;
  model?: string;
  mode?: string;
  tools_used: string[];
  cards?: ChatAnalysisCard[];
  widgets?: Widget[];
  phase?: CanvasPhase;
}

export interface ChatSession {
  id: string;
  farm_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_preview?: string;
}

export interface ChatMessage {
  id: string;
  farm_id: string;
  session_id?: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  tools_used?: string[];
  cards?: ChatAnalysisCard[];
  widgets?: Widget[];
  simulation_id?: string;
  created_at?: string;
}

export interface ChatSessionDetail {
  session: ChatSession;
  messages: ChatMessage[];
}

export interface AiStatus {
  configured: boolean;
  message: string;
  provider: string;
  model: string;
  health: Record<string, string>;
  ollama_host?: string;
  ollama_models?: string[];
}

export interface SimCreate {
  farm_id: string;
  simulation_type: string;
  parameters?: Record<string, unknown>;
  begin_date?: string;
  end_date?: string;
}

export interface SimResult {
  simulation_id?: string;
  run_id?: string;
  status: string;
  progress?: number;
  output_summary?: Record<string, unknown>;
  error?: string;
  created_at?: string;
  completed_at?: string;
  sim_type?: string;
  label?: string;
  scenario?: string;
  begin_date?: string;
  end_date?: string;
}

export interface FileEntry {
  name: string;
  path: string;
  kind: 'file' | 'dir';
  size?: number | null;
  size_label?: string;
  previewable?: boolean;
}

export interface FilePreview {
  path: string;
  zone: string;
  size: number;
  lines: string[];
  truncated: boolean;
  total_lines: number;
}

export interface FarmRunStatus {
  run_id: string;
  sim_type?: string;
  status: string;
  error?: string | null;
  created_at?: string;
  completed_at?: string;
  output_dir?: string | null;
  output_files: string[];
  output_count: number;
}

export interface FarmDataStatus {
  farm_id: string;
  farm_name?: string;
  data_source?: string;
  readiness: FarmReadiness;
  setup: {
    progress_pct: number;
    steps: { id: string; label: string; status: string; detail: string; action?: string }[];
    ready_to_simulate: boolean;
    block_reason: string;
  };
  boundary: Record<string, unknown>;
  manifest?: { verified?: boolean; sources?: string[] } | null;
  gis_layers: { id: string; file: string; exists: boolean; size_label: string }[];
  gis_dir: string;
  txtinout_dir: string;
  files: { gis: FileEntry[]; txtinout: FileEntry[] };
  runs: FarmRunStatus[];
}

export interface HruParams {
  lu_threshold: number;
  soil_threshold: number;
  slope_classes: string;
}

export interface HruResult {
  success: boolean;
  hru_count: number;
  details?: Record<string, unknown>;
  geojson?: unknown;
  error?: string;
}

export interface HealthStatus {
  ollama: string;
  groq: string;
  openai: string;
  anthropic: string;
  openrouter: string;
  minimax: string;
}

export interface Provider {
  id: string;
  label: string;
  models: string[];
  has_api_key: boolean;
  status?: string;
  ready?: boolean;
  kind?: 'local' | 'cloud';
  default_model?: string;
}

export interface SystemStatus {
  backend: { ok: boolean };
  ai: AiStatus;
  providers: Provider[];
  settings: Settings;
}

export interface Settings {
  provider: string;
  model: string;
}

declare global {
  interface Window {
    electronAPI?: {
      navigate: (callback: (path: string) => void) => void;
      getVersion: () => Promise<string>;
      farms: {
        list: () => Promise<Farm[]>;
        create: (data: Partial<Farm>) => Promise<Farm>;
        delete: (farmId: string) => Promise<{ ok: boolean }>;
      };
      data: {
        uploadInbox: (farmId: string, filename: string, contentB64: string) => Promise<InboxUploadResult>;
      };
      chat: {
        send: (farmId: string, message: string, provider?: string, model?: string, sessionId?: string) => Promise<ChatResponse>;
      };
      sim: {
        create: (data: SimCreate) => Promise<{ simulation_id: string; status: string }>;
        status: (simId: string) => Promise<SimResult>;
      };
      system: {
        ping: () => Promise<{ pong: boolean }>;
        providers: () => Promise<Provider[]>;
        health: () => Promise<HealthStatus>;
        test: (provider: string, model: string) => Promise<{ ok: boolean; error?: string }>;
        getSettings: () => Promise<Settings>;
        saveSettings: (settings: Partial<Settings>) => Promise<{ ok: boolean }>;
        saveKeys: (keys: Record<string, string>) => Promise<{ ok: boolean; error?: string }>;
      };
      gis: {
        upload: (files: Record<string, string>) => Promise<{ message: string; geojson: unknown }>;
        generateHrus: (params: HruParams) => Promise<HruResult>;
        export: (outputPath: string) => Promise<{ success: boolean; files?: string[]; error?: string }>;
        mapHtml: () => Promise<string>;
        hruMapHtml: () => Promise<string>;
      };
    };
  }
}

const API_BASE = import.meta.env.VITE_API_URL || '/api';
const isElectron = typeof window !== 'undefined' && !!window.electronAPI;

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    cache: 'no-store',   // API responses change with edits/runs — never serve a stale HTTP cache
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) {
    let detail = await res.text();
    try {
      const json = JSON.parse(detail);
      detail = json.detail || json.error || json.message || detail;
      if (typeof detail !== 'string') detail = JSON.stringify(detail);
    } catch {
      // keep raw text
    }
    throw new Error(detail || `Request failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

async function httpForm<T>(path: string, formData: FormData): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { method: 'POST', body: formData });
  if (!res.ok) {
    let detail = await res.text();
    try {
      const json = JSON.parse(detail);
      detail = json.detail || json.error || json.message || detail;
      if (typeof detail !== 'string') detail = JSON.stringify(detail);
    } catch {
      // keep raw text
    }
    throw new Error(detail || `Upload failed (${res.status})`);
  }
  return res.json() as Promise<T>;
}

async function fileToBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const result = reader.result as string;
      const base64 = result.includes(',') ? result.split(',')[1] : result;
      resolve(base64 || '');
    };
    reader.onerror = () => reject(reader.error || new Error('Could not read file'));
    reader.readAsDataURL(file);
  });
}

// ---- Farms ----
export const farms = {
  list: () =>
    isElectron ? window.electronAPI!.farms.list() : http<Farm[]>('/farms'),
  create: (data: Partial<Farm>) =>
    isElectron
      ? window.electronAPI!.farms.create(data)
      : http<Farm>('/farms', { method: 'POST', body: JSON.stringify(data) }),
  update: (id: string, data: Partial<Farm> & { setup_complete?: boolean }) =>
    http<Farm>(`/farms/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
  delete: (id: string) =>
    isElectron
      ? window.electronAPI!.farms.delete(id)
      : http<{ ok: boolean }>(`/farms/${id}`, { method: 'DELETE' }),
  readiness: (id: string) => http<FarmReadiness>(`/farms/${id}/readiness`),
  insights: (id: string) => http<FarmInsights>(`/farms/${id}/insights`),
  getCropSettings: (id: string) => http<CropSettings>(`/farms/${id}/crop`),
  saveCropSettings: (id: string, cropType: string, plantingDate: string) =>
    http<CropSettings>(`/farms/${id}/crop`, {
      method: 'PUT',
      body: JSON.stringify({ crop_type: cropType, planting_date: plantingDate }),
    }),
  getDatasetStatus: (id: string) => http<FieldDatasetStatus>(`/farms/${id}/dataset-status`),
  autoSetup: (
    id: string,
    opts?: { cropType?: string; plantingDate?: string; locationHint?: string; runFirstSimulation?: boolean },
  ) =>
    http<AutoSetupResult>(`/farms/${id}/auto-setup`, {
      method: 'POST',
      body: JSON.stringify({
        crop_type: opts?.cropType || '',
        planting_date: opts?.plantingDate || '',
        location_hint: opts?.locationHint || '',
        run_first_simulation: opts?.runFirstSimulation !== false,
      }),
    }),
};

// ---- Data ----
export const data = {
  uploadTxtinout: (farmId: string, file: File) => {
    const fd = new FormData();
    fd.append('file', file);
    return httpForm<{ ready: boolean; readiness: FarmReadiness }>(`/data/farms/${farmId}/txtinout`, fd);
  },
  loadDemo: (farmId: string) =>
    http<{ ready: boolean; readiness: FarmReadiness }>(`/data/farms/${farmId}/demo`, { method: 'POST' }),
  getBoundary: (farmId: string) =>
    http<{ farm_id: string; geojson?: GeoJSON.FeatureCollection | null; has_boundary: boolean; area_ha?: number }>(
      `/data/farms/${farmId}/boundary`
    ),
  saveBoundary: (farmId: string, geojson: GeoJSON.FeatureCollection) =>
    http<{ ok: boolean; area_ha?: number }>(`/data/farms/${farmId}/boundary`, {
      method: 'POST',
      body: JSON.stringify({ geojson }),
    }),
  fetchOnline: (farmId: string) =>
    http<{ ok: boolean; message?: string; sources?: string[]; readiness: FarmReadiness }>(
      `/data/farms/${farmId}/fetch-online`,
      { method: 'POST' }
    ),
  fetchAndBuild: (farmId: string, options?: FieldSetupOptions) =>
    http<{
      ok: boolean;
      message?: string;
      hru_count?: number;
      sources?: string[];
      soil?: { ok: boolean; soil?: string; cmppct?: number; nly?: number; hyd_grp?: string };
      management?: Record<string, unknown>;
      readiness: FarmReadiness;
      error?: string;
    }>(`/data/farms/${farmId}/fetch-and-build`, {
      method: 'POST',
      body: options ? JSON.stringify(options) : undefined,
    }),
  buildModel: (farmId: string) =>
    http<{ ok: boolean; hru_count?: number; readiness: FarmReadiness }>(
      `/data/farms/${farmId}/build-model`,
      { method: 'POST' }
    ),
  getStatus: (farmId: string) => http<FarmDataStatus>(`/data/farms/${farmId}/status`),
  previewFile: (farmId: string, zone: string, path: string) =>
    http<FilePreview>(
      `/data/farms/${farmId}/files/preview?zone=${encodeURIComponent(zone)}&path=${encodeURIComponent(path)}`,
    ),
  uploadGis: (farmId: string, file: File, layer = 'dem') => {
    const fd = new FormData();
    fd.append('file', file);
    return httpForm<{ path: string }>(`/data/farms/${farmId}/upload?layer=${layer}`, fd);
  },
  uploadInbox: async (farmId: string, file: File) => {
    if (isElectron) {
      const contentB64 = await fileToBase64(file);
      return window.electronAPI!.data.uploadInbox(farmId, file.name, contentB64);
    }
    const fd = new FormData();
    fd.append('file', file);
    return httpForm<InboxUploadResult>(`/data/farms/${farmId}/inbox/upload`, fd);
  },
  inspectInbox: (farmId: string) => http<InboxInspectResult>(`/data/farms/${farmId}/inbox/inspect`),
  importInbox: (farmId: string, runFirstSimulation = false) =>
    http<InboxImportResult>(`/data/farms/${farmId}/inbox/import`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_first_simulation: runFirstSimulation }),
    }),
  copyFieldSetup: (toFarmId: string, fromFarmId: string) =>
    http<InboxImportResult & { from_farm_name?: string; to_farm_name?: string; copied?: string[] }>(
      `/data/farms/${toFarmId}/copy-setup`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_farm_id: fromFarmId }),
      },
    ),
};

// ---- Scenarios ----
export const scenarios = {
  run: (farmId: string, scenario: 'irrigation' | 'fertilizer' | 'nitrate' | 'yield', dates?: { begin_date?: string; end_date?: string }) =>
    http<ScenarioResult>('/scenarios/run', {
      method: 'POST',
      body: JSON.stringify({ farm_id: farmId, scenario, ...dates }),
    }),
};

// ---- Chat ----
export const chat = {
  status: () => http<AiStatus>('/chat/status'),
  listSessions: (farmId: string) =>
    http<ChatSession[]>(`/chat/sessions?farm_id=${encodeURIComponent(farmId)}`),
  createSession: (farmId: string, title = 'New chat') =>
    http<ChatSession>('/chat/sessions', {
      method: 'POST',
      body: JSON.stringify({ farm_id: farmId, title }),
    }),
  getSession: (sessionId: string) =>
    http<ChatSessionDetail>(`/chat/sessions/${encodeURIComponent(sessionId)}`),
  deleteSession: (sessionId: string) =>
    http<{ ok: boolean }>(`/chat/sessions/${encodeURIComponent(sessionId)}`, {
      method: 'DELETE',
    }),
  send: (
    farmId: string,
    message: string,
    opts?: { provider?: string; model?: string; useAgent?: boolean; sessionId?: string },
  ) =>
    isElectron
      ? window.electronAPI!.chat.send(farmId, message, opts?.provider, opts?.model, opts?.sessionId)
      : http<ChatResponse>('/chat', {
          method: 'POST',
          body: JSON.stringify({
            farm_id: farmId,
            message,
            session_id: opts?.sessionId || '',
            provider: opts?.provider || '',
            model: opts?.model || '',
            use_agent: opts?.useAgent !== false,
          }),
        }),
  // Generative-UI: submit a widget's answer; resumes the agent and returns a normal ChatResponse.
  interact: (
    farmId: string,
    sessionId: string,
    widgetId: string,
    kind: string,
    data: Record<string, unknown>,
    opts?: { provider?: string; model?: string },
  ) =>
    http<ChatResponse>('/interact', {
      method: 'POST',
      body: JSON.stringify({
        farm_id: farmId,
        session_id: sessionId,
        widget_id: widgetId,
        kind,
        data,
        provider: opts?.provider || '',
        model: opts?.model || '',
      }),
    }),
};

// ---- Simulation ----
export const simulate = {
  create: (data: SimCreate) =>
    isElectron
      ? window.electronAPI!.sim.create(data)
      : http<{ simulation_id: string; status: string }>('/simulate', {
          method: 'POST',
          body: JSON.stringify({
            farm_id: data.farm_id,
            simulation_type: data.simulation_type,
            begin_date: data.begin_date,
            end_date: data.end_date,
            parameters: data.parameters || {},
          }),
        }),
  status: (id: string) =>
    isElectron
      ? window.electronAPI!.sim.status(id)
      : http<SimResult>(`/simulate/${id}`),
  engine: () => http<{ pyswatplus_installed: boolean; active_jobs: number }>('/simulate/engine'),
  listForFarm: (farmId: string) => http<SimResult[]>(`/simulate/farm/${farmId}`),
};

// ---- SWAT+ model (Editor) ----
export interface SwatParam { name: string; change_type: 'pctchg' | 'absval' | 'relchg'; value: number; }
export interface SwatRunBody {
  begin_date?: string;
  end_date?: string;
  warmup_years?: number;
  parameters?: SwatParam[];
  print_prt_control?: Record<string, Record<string, boolean>>;
  scenario?: string;
}
export interface RunTimelineCrop { crop: string; label: string; plant: string | null; harvest: string | null; biomass_kgha: number | null; yield_kgha?: number | null; }
export interface RunTimelineEvent { date: string; type: string; amount: number; unit: string; label: string; }
export interface RunDay { date: string; [field: string]: number | string; }
export interface RunTotals {
  precip_mm: number; irr_mm: number; et_mm: number; pet_mm: number; perc_mm: number; surq_mm: number; latq_mm: number;
  fertn_kgha: number; fixn_kgha: number; nuptake_kgha: number; denit_kgha: number; leached_kgha: number;
  sw_start: number; sw_end: number; sw_delta: number; yield_kgha: number; peak_bioms: number; nue_pct: number | null;
}
export interface RunStress {
  water_days: number; n_days: number; temp_days: number; aeration_days: number;
  mean_strsw: number; mean_strsn: number; grow_days: number;
}
export interface RunTimeline {
  ok: boolean; run_id: string; start: string; end: string;
  crops: RunTimelineCrop[]; events: RunTimelineEvent[];
  series: RunDay[];
  totals: RunTotals | Record<string, never>;
  stress: RunStress | Record<string, never>;
  summary: { irrigation_events: number; irrigation_total_mm: number; fertilizer_events: number;
    fertilizer_total_kgha: number; harvests: number; crops: string[]; };
}

export const swatModel = {
  validate: (farmId: string) =>
    http<{ valid: boolean; error?: string; format?: string; found_files?: string[] }>(`/swat/validate/${farmId}`),
  run: (farmId: string, body: SwatRunBody) =>
    http<{ run_id: string; status: string }>('/swat/run', {
      method: 'POST',
      body: JSON.stringify({
        farm_id: farmId,
        begin_date: body.begin_date || '',
        end_date: body.end_date || '',
        warmup_years: body.warmup_years ?? 2,
        parameters: body.parameters || [],
        print_prt_control: body.print_prt_control || {},
        scenario: body.scenario || 'baseline',
      }),
    }),
  runStatus: (runId: string) =>
    http<{ run_id: string; status: string; progress?: number; output_summary?: Record<string, unknown>; error?: string }>(
      `/swat/runs/${runId}`,
    ),
  listRuns: (farmId: string) => http<SimResult[]>(`/swat/runs/farm/${farmId}`),
  timeline: (runId: string) => http<RunTimeline>(`/swat/runs/${runId}/timeline`),
  labelRun: (runId: string, label: string) =>
    http<{ ok: boolean; run_id: string; label: string }>(`/swat/runs/${runId}/label`, {
      method: 'POST', body: JSON.stringify({ label }),
    }),
  rerun: (runId: string, label?: string) =>
    http<{ ok: boolean; run_id: string; status: string; label: string }>(`/swat/runs/${runId}/rerun`, {
      method: 'POST', body: JSON.stringify({ label: label ?? null }),
    }),
  metrics: (body: { farm_id: string; run_id?: string; sim_file: string; obs_file: string; indicators: string[]; sim_col?: string; obs_col?: string; date_format?: string }) =>
    http<{ indicators: Record<string, unknown>; sim_file: string; obs_file: string }>('/swat/metrics', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  sensitivity: (body: { farm_id: string; parameters: { name: string; change_type: string; lower_bound: number; upper_bound: number }[]; sample_number: number }) =>
    http<{ job_id: string; status: string }>('/swat/sensitivity', { method: 'POST', body: JSON.stringify(body) }),
};

// ---- SWAT+ Editor (raw TxtInOut files) ----
export interface EditorFile { name: string; ext: string; size: number; desc: string; }
export interface EditorCategory { name: string; files: EditorFile[]; }
export interface EditorFileList { ok: boolean; categories: EditorCategory[]; txtinout?: string; error?: string; }
export interface EditorColumn {
  col: string; label: string; unit: string; desc: string;
  type: 'text' | 'number' | 'select'; options?: { value: string; label: string }[];
}
export interface EditorFileContent {
  ok: boolean; name: string; title: string; tabular: boolean;
  header: string[]; rows: string[][]; raw?: string; n_rows?: number; desc?: string; error?: string;
  columns?: EditorColumn[];
}
export interface EditorSoilLayer { [col: string]: string; }
export interface EditorSoil { name: string; nly: string; hyd_grp: string; texture: string; layers: EditorSoilLayer[]; [col: string]: unknown; }
export interface EditorSoilContent {
  ok: boolean; name: string; title: string;
  soil_cols: EditorColumn[]; layer_cols: EditorColumn[]; soils: EditorSoil[]; error?: string;
}
export const swatEditor = {
  listFiles: (farmId: string) => http<EditorFileList>(`/swat/editor/${farmId}/files`),
  readFile: (farmId: string, name: string) =>
    http<EditorFileContent>(`/swat/editor/${farmId}/file?name=${encodeURIComponent(name)}`),
  writeFile: (farmId: string, body: { name: string; title?: string; header?: string[]; rows?: string[][]; raw?: string }) =>
    http<{ ok: boolean; name: string; mode: string; n_rows?: number }>(`/swat/editor/${farmId}/file`, {
      method: 'POST',
      body: JSON.stringify({ name: body.name, title: body.title || '', header: body.header ?? null, rows: body.rows ?? null, raw: body.raw ?? null }),
    }),
  readSoil: (farmId: string) => http<EditorSoilContent>(`/swat/editor/${farmId}/soil`),
  writeSoil: (farmId: string, body: { title?: string; soils: EditorSoil[] }) =>
    http<{ ok: boolean; name: string; n_soils?: number }>(`/swat/editor/${farmId}/soil`, {
      method: 'POST',
      body: JSON.stringify({ title: body.title || '', soils: body.soils }),
    }),
};

// ---- GIS ----
export interface GeocodeResult {
  lat: number;
  lon: number;
  label: string;
  kind?: string;
}

export const gis = {
  loadData: async (formData: FormData): Promise<{ message: string; geojson: unknown }> => {
    if (isElectron) {
      const files: Record<string, string> = {};
      for (const [key, value] of formData.entries()) {
        if (value instanceof File) {
          const buffer = await value.arrayBuffer();
          files[key] = btoa(String.fromCharCode(...new Uint8Array(buffer)));
        }
      }
      return window.electronAPI!.gis.upload(files);
    }
    const res = await fetch(`${API_BASE}/gis/upload`, { method: 'POST', body: formData });
    if (!res.ok) throw new Error(await res.text());
    return res.json();
  },
  generateHrus: (params: HruParams) =>
    isElectron
      ? window.electronAPI!.gis.generateHrus(params)
      : http<HruResult>('/gis/generate_hrus', { method: 'POST', body: JSON.stringify(params) }),
  exportTxtinout: (outputPath: string) =>
    isElectron
      ? window.electronAPI!.gis.export(outputPath)
      : http<{ success: boolean; files?: string[]; error?: string }>('/gis/export', {
          method: 'POST',
          body: JSON.stringify({ output_path: outputPath }),
        }),
  mapHtml: () => (isElectron ? window.electronAPI!.gis.mapHtml() : Promise.resolve('')),
  hruMapHtml: () => (isElectron ? window.electronAPI!.gis.hruMapHtml() : Promise.resolve('')),
  geocode: (q: string) =>
    http<{ results: GeocodeResult[]; error?: string }>(`/gis/geocode?q=${encodeURIComponent(q)}`),
};

// ---- System ----
export const system = {
  ping: () => http<{ ok: boolean; service: string }>('/system/ping'),
  status: () =>
    isElectron
      ? Promise.all([
          window.electronAPI!.system.providers(),
          window.electronAPI!.system.getSettings(),
          window.electronAPI!.system.health(),
        ]).then(([providers, settings, health]) => ({
          backend: { ok: true },
          providers,
          settings,
          ai: {
            configured: false,
            message: '',
            provider: settings.provider,
            model: settings.model,
            health: health as unknown as Record<string, string>,
          },
        } satisfies SystemStatus))
      : http<SystemStatus>('/system/status'),
  health: () =>
    isElectron ? window.electronAPI!.system.health() : http<HealthStatus>('/system/health'),
  providers: () =>
    isElectron ? window.electronAPI!.system.providers() : http<Provider[]>('/system/providers'),
  test: (provider: string, model: string) =>
    isElectron
      ? window.electronAPI!.system.test(provider, model)
      : http<{ ok: boolean; error?: string | null }>('/system/test', {
          method: 'POST',
          body: JSON.stringify({ provider, model }),
        }),
  saveKeys: (keys: Record<string, string>) =>
    isElectron
      ? window.electronAPI!.system.saveKeys(keys)
      : http<{ ok: boolean; error?: string }>('/system/keys', { method: 'POST', body: JSON.stringify(keys) }),
  getSettings: () =>
    isElectron ? window.electronAPI!.system.getSettings() : http<Settings>('/system/settings'),
  saveSettings: (settings: Partial<Settings>) =>
    isElectron
      ? window.electronAPI!.system.saveSettings(settings)
      : http<{ ok: boolean }>('/system/settings', { method: 'POST', body: JSON.stringify(settings) }),
};

export const isElectronApp = isElectron;

export function severityColor(severity: string): string {
  switch (severity) {
    case 'critical': return 'text-[var(--se-error)] bg-[var(--se-error-sf)] border-[var(--se-error-bd)]';
    case 'warning': return 'text-[var(--se-warn)] bg-[var(--se-warn-sf)] border-[var(--se-warn-bd)]';
    case 'ok': return 'text-[var(--se-ok)] bg-[var(--se-ok-sf)] border-[var(--se-ok-bd)]';
    default: return 'text-[var(--se-text-mut)] bg-[var(--se-rail)] border-[var(--se-border)]';
  }
}

export function confidenceColor(level: string): string {
  switch (level) {
    case 'high': return 'text-[var(--se-ok)] bg-[var(--se-ok-sf)] border-[var(--se-ok-bd)]';
    case 'moderate': return 'text-[var(--se-accent)] bg-[var(--se-accent-sf)] border-[var(--se-accent-bd)]';
    case 'low': return 'text-[var(--se-warn)] bg-[var(--se-warn-sf)] border-[var(--se-warn-bd)]';
    case 'directional': return 'text-[var(--se-warn)] bg-[var(--se-warn-sf)] border-[var(--se-warn-bd)]';
    case 'unavailable': return 'text-[var(--se-text-fnt)] bg-[var(--se-rail)] border-[var(--se-border)]';
    default: return 'text-[var(--se-text-mut)] bg-[var(--se-rail)] border-[var(--se-border)]';
  }
}

export function confidenceLabel(level: string): string {
  switch (level) {
    case 'high': return 'High confidence';
    case 'moderate': return 'Moderate confidence';
    case 'low': return 'Low — estimate';
    case 'directional': return 'Directional only';
    case 'unavailable': return 'Not available';
    default: return level;
  }
}
