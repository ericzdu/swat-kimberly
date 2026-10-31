import { useState } from 'react';
import { BarChart, Bar, LineChart, Line, Area, ComposedChart, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine, Cell } from 'recharts';
import type { Widget } from '@/lib/widgets';
import type { WaterBalance, NutrientBalance, NitrateBalance, NitrateMonthlyPoint, DailyPoint } from '@/lib/api';
import { CHART, tooltipStyle, axisTick } from '@/lib/chartTheme';

type ChartVariant = 'water_balance' | 'nutrient_balance' | 'stream_nitrate' | 'n_pathways' | 'soil_moisture' | 'custom';

interface CustomSeries { field: string; label: string; unit: string; data: number[]; }
interface ChartPayload {
  variant: ChartVariant;
  water_balance?: WaterBalance;
  nutrient_balance?: NutrientBalance;
  nitrate?: NitrateBalance;
  nitrate_monthly?: NitrateMonthlyPoint[];
  daily_series?: DailyPoint[];
  // custom (agent-generated) charts:
  chart_type?: 'line' | 'bar' | 'area';
  agg?: string;
  x?: string[];
  series?: CustomSeries[];
}

function NoData({ label }: { label?: string }) {
  return (
    <div className="h-[240px] flex items-center justify-center text-[var(--se-text-fnt)] text-sm text-center px-6">
      {label || 'No data'}
    </div>
  );
}

// Output-only canvas widget: renders SWAT+ result charts, mirroring the exact
// Recharts blocks on the Visualizations page and reusing the shared chart theme.
export default function ChartWidget({ widget }: { widget: Widget }) {
  const p = widget.payload as ChartPayload;

  return (
    <div className="rounded-lg border border-[var(--se-border)] bg-[var(--se-card)] p-4 space-y-3">
      {widget.title && <h3 className="text-sm font-semibold text-[var(--se-text)]">{widget.title}</h3>}
      {p.variant === 'custom' ? <CustomChart p={p} /> : renderChart(p)}
    </div>
  );
}

// Agent-generated, data-driven chart. Interactive: switch line/bar/area, toggle series.
function CustomChart({ p }: { p: ChartPayload }) {
  const series = p.series ?? [];
  const x = p.x ?? [];
  const [type, setType] = useState<'line' | 'bar' | 'area'>(p.chart_type ?? 'line');
  const [hidden, setHidden] = useState<Record<string, boolean>>({});
  if (!series.length || !x.length) return <NoData label="No data to plot." />;

  const rows = x.map((xv, i) => {
    const r: Record<string, string | number> = { x: xv };
    series.forEach(s => { r[s.field] = s.data[i] ?? 0; });
    return r;
  });
  const colorOf = (field: string) => CHART.cat[series.findIndex(s => s.field === field) % CHART.cat.length];
  const shown = series.filter(s => !hidden[s.field]);
  const marks = shown.map(s => {
    const c = colorOf(s.field);
    const onePt = x.length === 1;  // a lone point is invisible without a dot
    if (type === 'bar') return <Bar key={s.field} dataKey={s.field} name={s.label} fill={c} radius={[3, 3, 0, 0]} />;
    if (type === 'area') return <Area key={s.field} dataKey={s.field} name={s.label} stroke={c} fill={c} fillOpacity={0.16} strokeWidth={2} dot={onePt} />;
    return <Line key={s.field} type="monotone" dataKey={s.field} name={s.label} stroke={c} strokeWidth={2} dot={onePt} />;
  });
  const btn = (t: 'line' | 'bar' | 'area') =>
    `text-[11px] px-2 py-0.5 rounded-md capitalize ${type === t ? 'bg-[var(--se-accent)] text-white' : 'text-[var(--se-text-mut)] hover:text-[var(--se-text)]'}`;

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="inline-flex rounded-lg border border-[var(--se-border)] bg-[var(--se-card)] p-0.5">
          {(['line', 'bar', 'area'] as const).map(t => <button key={t} className={btn(t)} onClick={() => setType(t)}>{t}</button>)}
        </div>
        {p.agg && <span className="text-[10px] text-[var(--se-text-fnt)]">per {p.agg}</span>}
      </div>
      <ResponsiveContainer width="100%" height={260}>
        <ComposedChart data={rows} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
          <XAxis dataKey="x" tick={{ fill: CHART.muted, fontSize: 10 }} tickLine={false} axisLine={{ stroke: CHART.axis }} minTickGap={24} />
          <YAxis tick={axisTick} tickLine={false} axisLine={false} width={40} />
          <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
          {marks}
        </ComposedChart>
      </ResponsiveContainer>
      <div className="flex flex-wrap gap-1.5">
        {series.map(s => (
          <button key={s.field} onClick={() => setHidden(h => ({ ...h, [s.field]: !h[s.field] }))}
            className={`inline-flex items-center gap-1.5 text-[11px] rounded-full px-2 py-0.5 border ${hidden[s.field] ? 'opacity-40 border-[var(--se-border)]' : 'border-[var(--se-border)]'}`}
            title="Toggle series">
            <span className="w-2 h-2 rounded-full" style={{ background: colorOf(s.field) }} />
            {s.label}{s.unit ? ` (${s.unit})` : ''}
          </button>
        ))}
      </div>
      <p className="text-[10px] text-[var(--se-text-fnt)]">From your model run — uncalibrated, read as a directional estimate.</p>
    </div>
  );
}

function renderChart(p: ChartPayload) {
  switch (p.variant) {
    case 'water_balance': {
      const wb = p.water_balance;
      if (!wb) return <NoData label="Run an analysis to see water balance" />;
      const data = [
        { label: 'Precip', value: wb.precip_mm, fill: CHART.cat[0] },
        { label: 'ET', value: wb.et_mm, fill: CHART.cat[1] },
        { label: 'Runoff', value: wb.runoff_mm, fill: CHART.cat[4] },
        { label: 'Deep Perc', value: wb.deep_perc_mm, fill: CHART.cat[3] },
        { label: 'Soil Moist', value: wb.soil_moisture_mm, fill: CHART.cat[2] },
      ];
      return (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART.axis }} />
            <YAxis tick={axisTick} tickLine={false} axisLine={false} width={38} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>
              {data.map((d, i) => <Cell key={i} fill={d.fill} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      );
    }

    case 'nutrient_balance': {
      const nb = p.nutrient_balance;
      if (!nb) return <NoData label="Run an analysis to see nutrients" />;
      const data = [
        { label: 'Nitrogen', value: nb.nitrogen_kgha, fill: CHART.cat[1] },
        { label: 'Phosphorus', value: nb.phosphorus_kgha, fill: CHART.cat[2] },
      ];
      return (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART.axis }} />
            <YAxis tick={axisTick} tickLine={false} axisLine={false} width={38} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
            <Bar dataKey="value" radius={[4, 4, 0, 0]}>
              {data.map((d, i) => <Cell key={i} fill={d.fill} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      );
    }

    case 'stream_nitrate': {
      const monthly = p.nitrate_monthly ?? [];
      const hasMonthlyConc = monthly.some(m => m.no3_mgL != null);
      if (!hasMonthlyConc) return <NoData label="Run a Water Quality analysis over a multi-month period to see the seasonal stream-nitrate curve." />;
      const limit = p.nitrate?.limit_mgL ?? 10;
      return (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={monthly} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="month_label" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART.axis }} />
            <YAxis tick={axisTick} tickLine={false} axisLine={false} width={38} label={{ value: 'mg/L', angle: -90, position: 'insideLeft', fill: CHART.muted, fontSize: 11 }} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: CHART.axis }} />
            <ReferenceLine y={limit} stroke={CHART.status.critical} strokeDasharray="6 4" label={{ value: `${limit.toFixed(0)} mg/L drinking limit`, fill: CHART.status.critical, fontSize: 11, position: 'insideTopRight' }} />
            <Line type="monotone" dataKey="no3_mgL" name="Stream nitrate-N (mg/L)" stroke={CHART.series1} strokeWidth={2} dot={{ r: 3, fill: CHART.series1 }} activeDot={{ r: 5 }} connectNulls />
          </LineChart>
        </ResponsiveContainer>
      );
    }

    case 'n_pathways': {
      const nitrate = p.nitrate;
      if (!nitrate) return <NoData label="No measurable nitrate loss in the latest run." />;
      const data = [
        { label: 'Leached to groundwater', value: nitrate.leached_to_groundwater_kgha, fill: CHART.cat[3] },
        { label: 'Surface runoff', value: nitrate.surface_runoff_kgha, fill: CHART.cat[4] },
        { label: 'Lateral flow', value: nitrate.lateral_flow_kgha, fill: CHART.cat[0] },
        { label: 'Tile drain', value: nitrate.tile_drain_kgha, fill: CHART.cat[1] },
      ].filter(d => (d.value ?? 0) > 0);
      if (data.length === 0) return <NoData label="No measurable nitrate loss in the latest run." />;
      return (
        <ResponsiveContainer width="100%" height={240}>
          <BarChart data={data} layout="vertical" margin={{ left: 40, right: 16 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
            <XAxis type="number" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART.axis }} label={{ value: 'kg-N/ha/yr', position: 'insideBottom', offset: -2, fill: CHART.muted, fontSize: 11 }} />
            <YAxis type="category" dataKey="label" width={140} tick={{ fill: CHART.inkSecondary, fontSize: 11 }} tickLine={false} axisLine={false} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(0,0,0,0.04)' }} />
            <Bar dataKey="value" radius={[0, 4, 4, 0]}>
              {data.map((d, i) => <Cell key={i} fill={d.fill} />)}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      );
    }

    case 'soil_moisture': {
      const daily = p.daily_series ?? [];
      if (daily.length === 0) return <NoData label="Run an analysis to see soil moisture over time" />;
      return (
        <ResponsiveContainer width="100%" height={240}>
          <LineChart data={daily} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
            <XAxis dataKey="date" tick={{ fill: CHART.muted, fontSize: 10 }} tickLine={false} axisLine={{ stroke: CHART.axis }} minTickGap={24} />
            <YAxis tick={axisTick} tickLine={false} axisLine={false} width={38} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: CHART.axis }} />
            <Legend iconType="plainline" wrapperStyle={{ fontSize: 12, color: CHART.inkSecondary }} />
            <Line type="monotone" dataKey="soil_moisture_mm" name="Soil moisture (mm)" stroke={CHART.cat[2]} strokeWidth={2} dot={false} />
            <Line type="monotone" dataKey="et_mm" name="ET (mm)" stroke={CHART.cat[1]} strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      );
    }

    default:
      return <NoData />;
  }
}
