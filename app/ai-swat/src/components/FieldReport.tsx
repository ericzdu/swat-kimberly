import { useCallback, useEffect, useState } from 'react';
import { farms, confidenceColor, type FarmInsights, type InsightItem } from '@/lib/api';
import ChartWidget from '@/components/widgets/ChartWidget';
import DataChecklist from '@/components/DataChecklist';
import RunTimeline from '@/components/RunTimeline';
import RunSnapshots from '@/components/RunSnapshots';
import RunCompare from '@/components/RunCompare';
import type { Widget } from '@/lib/widgets';
import {
  BarChart3, Droplets, FlaskConical, Sprout, Wheat, RefreshCw, Loader2, Info,
  Database, CloudRain, MapPin, Calendar, Layers, AlertTriangle,
} from 'lucide-react';
import clsx from 'clsx';

// Build a chart-widget envelope so we can reuse the existing ChartWidget renderer.
function chart(variant: string, title: string, payload: Record<string, unknown>): Widget {
  return {
    widget_id: `report-${variant}`,
    kind: 'chart',
    placement: 'canvas',
    interactive: false,
    title,
    payload: { variant, ...payload },
  } as unknown as Widget;
}

const num = (v: unknown, d = 1) => (typeof v === 'number' && Number.isFinite(v) ? v.toFixed(d) : '—');

// One deterministic canvas view that shows EVERYTHING for a ready field: every
// model-run output as a chart, the raw numbers as tables, the plain-language
// interpretations, and the field's input data + quality. No agent involved.
export default function FieldReport({ farmId, reloadKey = 0, onAsk }: {
  farmId: string;
  reloadKey?: number;
  onAsk?: (msg: string) => void;
}) {
  const [ins, setIns] = useState<FarmInsights | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [activeRunId, setActiveRunId] = useState<string | undefined>(undefined);
  const [compareIds, setCompareIds] = useState<string[]>([]);

  const load = useCallback(() => {
    setLoading(true);
    setError('');
    farms
      .insights(farmId)
      .then(setIns)
      .catch(e => setError(e instanceof Error ? e.message : 'Could not load results.'))
      .finally(() => setLoading(false));
  }, [farmId]);

  useEffect(() => { load(); }, [load, reloadKey]);

  if (loading && !ins) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-sm text-[var(--se-text-mut)]">
        <Loader2 className="w-4 h-4 animate-spin" /> Loading results &amp; field data…
      </div>
    );
  }
  if (error) {
    return (
      <div className="flex items-start gap-2 rounded-lg border border-[var(--se-error-bd)] bg-[var(--se-error-sf)] px-3 py-2 text-sm text-[var(--se-error)]">
        <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" /> {error}
      </div>
    );
  }

  const ro = ins?.run_output;
  const rd = ins?.readiness;
  const conf = ins?.confidence;
  const period = (rd as unknown as { simulation_period?: { begin?: string; end?: string; years?: number } } | undefined)?.simulation_period;
  const hasResults = Boolean(ins?.has_data && ro);
  const overall = conf?.overall_confidence;
  const calibrated = conf?.calibration_state === 'calibrated';

  // ---- Result charts (only those the run actually produced) ----
  const charts: Widget[] = [];
  if (ro?.water_balance) charts.push(chart('water_balance', 'Water balance (mm / year)', { water_balance: ro.water_balance }));
  if (ro?.nutrient_balance && (ro.nutrient_balance.nitrogen_kgha || 0) + (ro.nutrient_balance.phosphorus_kgha || 0) > 0)
    charts.push(chart('nutrient_balance', 'Nutrient balance (kg/ha)', { nutrient_balance: ro.nutrient_balance }));
  if (ro?.nitrate && (ro.nitrate.total_no3_loss_kgha || 0) > 0)
    charts.push(chart('n_pathways', 'Nitrate loss pathways (kg-N/ha/yr)', { nitrate: ro.nitrate }));
  if (ro?.nitrate_monthly?.length)
    charts.push(chart('stream_nitrate', 'Stream nitrate through the year', { nitrate_monthly: ro.nitrate_monthly, nitrate: ro.nitrate }));
  if (ro?.daily_series?.length)
    charts.push(chart('soil_moisture', 'Soil moisture & ET over recent days', { daily_series: ro.daily_series }));

  // ---- Key-number tables ----
  const wb = ro?.water_balance;
  const nb = ro?.nutrient_balance;
  const nit = ro?.nitrate;
  const waterRows: [string, string][] = wb ? [
    ['Precipitation', `${num(wb.precip_mm)} mm`],
    ['Evapotranspiration (ET)', `${num(wb.et_mm)} mm`],
    ['Surface runoff', `${num(wb.runoff_mm)} mm`],
    ['Deep percolation', `${num(wb.deep_perc_mm)} mm`],
    ['Soil moisture', `${num(wb.soil_moisture_mm)} mm`],
  ] : [];
  const nitrateRows: [string, string][] = nit ? [
    ['Leached to groundwater', `${num(nit.leached_to_groundwater_kgha, 2)} kg-N/ha`],
    ['Surface runoff', `${num(nit.surface_runoff_kgha, 2)} kg-N/ha`],
    ['Lateral flow', `${num(nit.lateral_flow_kgha, 2)} kg-N/ha`],
    ['Tile drain', `${num(nit.tile_drain_kgha, 2)} kg-N/ha`],
    ['Total N loss', `${num(nit.total_no3_loss_kgha, 2)} kg-N/ha`],
    ...(nit.stream ? [['Stream nitrate (mean)', `${num(nit.stream.mean_no3_mgL, 2)} mg/L (limit ${nit.limit_mgL})`] as [string, string]] : []),
  ] : [];

  const interps: { label: string; icon: typeof Droplets; item?: InsightItem }[] = [
    { label: 'Irrigation', icon: Droplets, item: ins?.irrigation },
    { label: 'Water quality (nitrate)', icon: FlaskConical, item: ins?.nitrate },
    { label: 'Fertilizer', icon: Sprout, item: ins?.fertilizer },
    { label: 'Yield', icon: Wheat, item: ins?.yield },
  ];

  const sev: Record<string, string> = {
    ok: 'text-[var(--se-ok)]', warning: 'text-[var(--se-warn)]', critical: 'text-[var(--se-error)]', missing: 'text-[var(--se-text-fnt)]',
  };

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="w-9 h-9 rounded-xl bg-[var(--se-accent-sf)] flex items-center justify-center shrink-0">
          <BarChart3 className="w-5 h-5 text-[var(--se-accent)]" />
        </div>
        <div className="min-w-0">
          <h2 className="text-base font-semibold truncate">{ins?.farm_name || 'Field'} — results &amp; data</h2>
          <p className="text-xs text-[var(--se-text-fnt)]">Everything from the latest model run and this field's inputs.</p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          {overall && (
            <span className={clsx('text-[11px] px-2 py-0.5 rounded-full border capitalize', confidenceColor(overall))}>
              {overall} confidence
            </span>
          )}
          <button
            onClick={load}
            className="flex items-center gap-1.5 text-xs border border-[var(--se-border)] rounded-lg px-3 py-1.5 text-[var(--se-text-mut)] hover:text-[var(--se-accent)] hover:border-[var(--se-accent-bd)]"
          >
            <RefreshCw className={clsx('w-3.5 h-3.5', loading && 'animate-spin')} /> Refresh
          </button>
        </div>
      </div>

      {!calibrated && (
        <div className="flex items-start gap-2 rounded-lg border border-[var(--se-warn-bd)] bg-[var(--se-warn-sf)] px-3 py-2 text-[11px] text-[var(--se-warn)]">
          <Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>Uncalibrated single-field model — read these as directional scenario estimates, not exact measured values. Add observed data to calibrate.</span>
        </div>
      )}

      {/* ================= RUN SNAPSHOTS · TIMELINE · COMPARE ================= */}
      <RunSnapshots
        farmId={farmId}
        reloadKey={reloadKey}
        activeRunId={activeRunId}
        onView={id => { setActiveRunId(id); setCompareIds([]); }}
        onCompare={ids => setCompareIds(ids)}
      />
      {compareIds.length >= 2
        ? <RunCompare farmId={farmId} runIds={compareIds} onClose={() => setCompareIds([])} />
        : <RunTimeline farmId={farmId} runId={activeRunId} reloadKey={reloadKey} />}

      {/* ================= MODEL RESULTS ================= */}
      <section className="space-y-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--se-text-mut)] flex items-center gap-1.5">
          <BarChart3 className="w-3.5 h-3.5" /> Model run results
        </h3>

        {!hasResults ? (
          <div className="rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] p-6 text-center">
            <p className="text-sm text-[var(--se-text-mut)]">No completed run yet for this field.</p>
            <div className="flex flex-wrap gap-2 justify-center mt-3">
              {['Should I irrigate today? Use run_irrigation_analysis.', 'How is my water quality / nitrate? Use run_nitrate_analysis.', 'What yield can I expect? Use run_yield_analysis.'].map((m, i) => (
                <button key={i} onClick={() => onAsk?.(m)} className="text-xs px-3 py-1.5 rounded-lg border border-[var(--se-border)] hover:border-[var(--se-accent)] hover:text-[var(--se-accent)]">
                  {['Run irrigation', 'Run water quality', 'Run yield'][i]}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <>
            {/* Stat strip */}
            <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
              <Stat label="Yield" value={ro?.yield_kgha != null ? `${(ro.yield_kgha / 1000).toFixed(2)} t/ha` : '—'} icon={Wheat} />
              <Stat label="N leached" value={nit ? `${num(nit.leached_to_groundwater_kgha, 1)} kg/ha` : '—'} icon={FlaskConical} />
              <Stat label="Stream NO₃" value={nit?.stream?.mean_no3_mgL != null ? `${num(nit.stream.mean_no3_mgL, 2)} mg/L` : '—'} icon={Droplets} />
              <Stat label="ET" value={wb ? `${num(wb.et_mm, 0)} mm` : '—'} icon={CloudRain} />
            </div>

            {/* Charts grid */}
            {charts.length > 0 && (
              <div className="grid gap-4 lg:grid-cols-2">
                {charts.map(w => <ChartWidget key={w.widget_id} widget={w} />)}
              </div>
            )}

            {/* Key numbers tables */}
            <div className="grid gap-4 sm:grid-cols-2">
              {waterRows.length > 0 && <KeyTable title="Water balance" rows={waterRows} />}
              {nitrateRows.length > 0 && <KeyTable title="Nitrogen loss" rows={nitrateRows} />}
            </div>

            {/* Interpretations */}
            <div className="grid gap-3 sm:grid-cols-2">
              {interps.filter(x => x.item?.headline).map(({ label, icon: Icon, item }) => (
                <div key={label} className="rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] p-4">
                  <div className="flex items-center gap-2 mb-1.5">
                    <Icon className="w-4 h-4 text-[var(--se-accent)]" />
                    <span className="text-xs font-semibold text-[var(--se-text)]">{label}</span>
                    {item?.confidence?.level && (
                      <span className={clsx('ml-auto text-[10px] px-1.5 py-0.5 rounded-full border capitalize', confidenceColor(item.confidence.level))}>
                        {item.confidence.level}
                      </span>
                    )}
                  </div>
                  <p className={clsx('text-sm font-medium', sev[item?.severity || 'missing'])}>{item?.headline}</p>
                  {item?.advice && <p className="text-xs text-[var(--se-text-mut)] mt-1 leading-relaxed">{item.advice}</p>}
                </div>
              ))}
            </div>
          </>
        )}
      </section>

      {/* ================= FIELD INPUT DATA ================= */}
      <section className="space-y-4">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--se-text-mut)] flex items-center gap-1.5">
          <Database className="w-3.5 h-3.5" /> Field input data
        </h3>

        <div className="grid gap-3 grid-cols-2 sm:grid-cols-4">
          <Stat label="Data source" value={ins?.confidence?.data_source || rd?.data_source || '—'} icon={Database} small />
          <Stat label="Simulation" value={period?.begin && period?.end ? `${String(period.begin).slice(-4)}–${String(period.end).slice(-4)}` : '—'} icon={Calendar} small />
          <Stat label="Weather" value={conf?.provenance?.weather_real ? 'Observed' : 'Generated'} icon={CloudRain} small />
          <Stat label="Map layers" value={conf?.provenance?.gis_verified ? 'Verified' : 'Unverified'} icon={MapPin} small />
        </div>

        {/* Data readiness checklist */}
        {rd?.checks && rd.checks.length > 0 && <DataChecklist checks={rd.checks} />}

        {/* Input quality */}
        {conf?.inputs && conf.inputs.length > 0 && (
          <div className="rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] overflow-hidden">
            <div className="px-4 py-2 border-b border-[var(--se-border-lt)] flex items-center gap-1.5">
              <Layers className="w-3.5 h-3.5 text-[var(--se-text-mut)]" />
              <span className="text-xs font-semibold text-[var(--se-text-mut)]">Input quality</span>
            </div>
            <table className="w-full text-xs">
              <tbody>
                {conf.inputs.map(inp => (
                  <tr key={inp.id} className="border-b border-[var(--se-border-lt)] last:border-0">
                    <td className="px-4 py-2 text-[var(--se-text)] capitalize">{inp.id.replace(/_/g, ' ')}</td>
                    <td className="px-4 py-2 text-[var(--se-text-mut)]">{inp.detail || (inp.present ? 'present' : 'missing')}</td>
                    <td className="px-4 py-2 text-right">
                      <span className={clsx(
                        'text-[10px] px-2 py-0.5 rounded-full border capitalize',
                        inp.quality === 'high' ? 'text-[var(--se-ok)] bg-[var(--se-ok-sf)] border-[var(--se-ok-bd)]'
                          : inp.quality === 'medium' ? 'text-[var(--se-accent)] bg-[var(--se-accent-sf)] border-[var(--se-accent-bd)]'
                          : inp.quality === 'missing' ? 'text-[var(--se-error)] bg-[var(--se-error-sf)] border-[var(--se-error-bd)]'
                          : 'text-[var(--se-warn)] bg-[var(--se-warn-sf)] border-[var(--se-warn-bd)]',
                      )}>
                        {inp.quality}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <p className="text-[11px] text-[var(--se-text-fnt)]">
          Edit any raw input file (soil, weather, management, crop) in the <span className="font-medium text-[var(--se-text-mut)]">SWAT+ Editor</span>.
        </p>
      </section>
    </div>
  );
}

function Stat({ label, value, icon: Icon, small }: { label: string; value: string; icon: typeof Droplets; small?: boolean }) {
  return (
    <div className="rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] p-3">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wide text-[var(--se-text-fnt)] mb-1">
        <Icon className="w-3 h-3" /> {label}
      </div>
      <p className={clsx('font-semibold text-[var(--se-text)] truncate', small ? 'text-sm' : 'text-lg')}>{value}</p>
    </div>
  );
}

function KeyTable({ title, rows }: { title: string; rows: [string, string][] }) {
  return (
    <div className="rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] overflow-hidden">
      <div className="px-4 py-2 border-b border-[var(--se-border-lt)]">
        <span className="text-xs font-semibold text-[var(--se-text-mut)]">{title}</span>
      </div>
      <table className="w-full text-xs">
        <tbody>
          {rows.map(([k, v]) => (
            <tr key={k} className="border-b border-[var(--se-border-lt)] last:border-0">
              <td className="px-4 py-1.5 text-[var(--se-text-mut)]">{k}</td>
              <td className="px-4 py-1.5 text-right font-mono text-[var(--se-text)] tabular-nums">{v}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
