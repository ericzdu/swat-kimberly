import { useEffect, useMemo, useState } from 'react';
import {
  ComposedChart, BarChart, Bar, Area, Line, XAxis, YAxis, CartesianGrid, Tooltip,
  ResponsiveContainer, ReferenceArea, ReferenceLine, ReferenceDot, Cell,
} from 'recharts';
import {
  swatModel, type RunTimeline as RT, type RunDay, type RunTotals, type RunStress,
} from '@/lib/api';
import {
  FlaskConical, Loader2, CalendarRange, ChevronDown, ChevronRight, Info,
  AlertTriangle, CheckCircle2, CircleAlert,
} from 'lucide-react';
import clsx from 'clsx';

/* ---------- constants ---------- */
const CROP_ICON: Record<string, string> = {
  corn: '🌽', csil: '🌽', soyb: '🫘', wwht: '🌾', barl: '🌾', alfa: '🌿', past: '🌱', frst: '🌲',
};
const CROP_COLOR: Record<string, string> = {
  corn: '#eab308', csil: '#f59e0b', soyb: '#65a30d', wwht: '#ca8a04', barl: '#a16207',
  alfa: '#16a34a', past: '#22c55e', frst: '#15803d',
};
const iconFor = (c: string) => CROP_ICON[c] || '🌱';
const colorFor = (c: string) => CROP_COLOR[c] || '#6b7280';

const C = {
  rain: '#2a78d6', irr: '#38bdf8', sw: '#eab308', et: '#1baf7a', perc: '#0f7a3d',
  bioms: '#16a34a', lai: '#1baf7a', yield: '#0ca30c', residue: '#94a3b8',
  fertn: '#ea6a34', uptake: '#16a34a', leached: '#dc2626', denit: '#6d5ae0',
  stress: '#dc2626',
};
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const day = (d: string) => new Date(d + 'T00:00:00').getTime();

// flux fields aggregate by SUM; everything else (states/stresses/weather) by MEAN
const FLUX = new Set(['precip', 'irr', 'et', 'pet', 'perc', 'surq_gen', 'latq', 'snomlt', 'wateryld',
  'fertn', 'nuptake', 'denit', 'gwsoiln', 'percn', 'fixn', 'no3atmo']);

type Agg = 'week' | 'month' | 'year';
type Lens = 'water' | 'growth' | 'nitrogen';

interface Bucket extends Record<string, number | string> { date: string; leached: number; }

/* ---------- aggregation ---------- */
function bucketKey(d: string, mode: Agg): string {
  const [y, m, day] = d.split('-').map(Number);
  if (mode === 'year') return `${y}`;
  if (mode === 'month') return `${y}-${String(m).padStart(2, '0')}`;
  // week: day-of-year / 7 via UTC so DST offsets can't shift a boundary
  const doy = Math.floor((Date.UTC(y, m - 1, day) - Date.UTC(y, 0, 1)) / 864e5);
  return `${y}-${String(Math.floor(doy / 7)).padStart(2, '0')}`;
}

// sensible default granularity + on-screen width for the reported span
function defaultAgg(years: number): Agg { return years > 8 ? 'year' : years > 3 ? 'month' : 'week'; }

function aggregate(series: RunDay[], mode: Agg, cumulative: boolean): Bucket[] {
  const groups = new Map<string, RunDay[]>();
  for (const r of series) {
    const k = bucketKey(r.date, mode);
    (groups.get(k) || groups.set(k, []).get(k)!).push(r);
  }
  const fields = series.length ? Object.keys(series[0]).filter(f => f !== 'date') : [];
  const buckets: Bucket[] = [...groups.values()].map(rows => {
    const b: Bucket = { date: rows.reduce((m, r) => (r.date < m ? r.date : m), rows[0].date), leached: 0 };
    for (const f of fields) {
      const vals = rows.map(r => (typeof r[f] === 'number' ? (r[f] as number) : 0));
      const v = FLUX.has(f) ? vals.reduce((a, c) => a + c, 0) : vals.reduce((a, c) => a + c, 0) / vals.length;
      b[f] = Math.round(v * 1000) / 1000;
    }
    b.leached = Math.round(((b.percn as number || 0) + (b.gwsoiln as number || 0)) * 1000) / 1000;
    return b;
  }).sort((a, b) => a.date.localeCompare(b.date));
  // running totals AFTER sorting, so cumulative curves are in date order
  if (cumulative) {
    const cum: Record<string, number> = {};
    for (const b of buckets)
      for (const f of ['fertn', 'nuptake', 'denit', 'leached']) {
        cum[f] = (cum[f] || 0) + (b[f] as number || 0);
        b[`${f}_cum`] = Math.round(cum[f] * 100) / 100;
      }
  }
  return buckets;
}

/* ---------- verdict ---------- */
type Status = 'good' | 'ok' | 'warn';
function verdict(t: RunTotals, s: RunStress) {
  const grow = Math.max(1, s.grow_days || 1);
  const cropH: Status = s.mean_strsw < 0.15 && s.mean_strsn < 0.15 ? 'good'
    : (s.mean_strsw > 0.4 || s.mean_strsn > 0.4 ? 'warn' : 'ok');
  const water: Status = s.water_days / grow < 0.05 ? 'good' : s.water_days / grow < 0.15 ? 'ok' : 'warn';
  const nleach: Status = t.leached_kgha < 2 ? 'good' : t.leached_kgha < 10 ? 'ok' : 'warn';
  return { cropH, water, nleach };
}

/* ---------- helpers ---------- */
const fmt = (v: number | null | undefined, d = 0) =>
  v == null || !Number.isFinite(v) ? '—' : v.toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d });
const hasTotals = (t: unknown): t is RunTotals => !!t && typeof (t as RunTotals).precip_mm === 'number';

/* ================= component ================= */
export default function RunTimeline({ farmId, runId, reloadKey }: {
  farmId: string; runId?: string; reloadKey?: number;
}) {
  const [tl, setTl] = useState<RT | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'empty' | 'error'>('loading');
  const [err, setErr] = useState('');
  const [lens, setLens] = useState<Lens>('water');
  const [agg, setAgg] = useState<Agg>('week');
  const [cumulative, setCumulative] = useState(false);
  const [showSci, setShowSci] = useState(false);
  const [explain, setExplain] = useState(false);

  useEffect(() => {
    let alive = true; setState('loading');
    (async () => {
      try {
        let rid = runId;
        if (!rid) {
          const runs = await swatModel.listRuns(farmId);
          const ts = (r: { completed_at?: string; created_at?: string }) => r.completed_at || r.created_at || '';
          const done = runs.filter(r => r.status === 'completed').sort((a, b) => ts(b).localeCompare(ts(a)));
          rid = (done[0] || runs[0])?.run_id;
        }
        if (!rid) { if (alive) setState('empty'); return; }
        const d = await swatModel.timeline(rid);
        if (!alive) return;
        if (!d.ok || (!d.crops.length && !d.series?.length)) { setState('empty'); return; }
        const yrs = d.start && d.end ? (day(d.end) - day(d.start)) / (365.25 * 864e5) : 2;
        setAgg(defaultAgg(yrs));
        setTl(d); setState('ready');
      } catch (e) { if (alive) { setErr(e instanceof Error ? e.message : 'Could not load timeline'); setState('error'); } }
    })();
    return () => { alive = false; };
  }, [farmId, runId, reloadKey]);

  const series = tl?.series || [];
  const buckets = useMemo(() => aggregate(series, agg, cumulative), [series, agg, cumulative]);

  if (state === 'loading') return <Shell><Row><Loader2 className="w-4 h-4 animate-spin" /> Building run timeline…</Row></Shell>;
  if (state === 'empty') return null;
  if (state === 'error') return <Shell><p className="text-xs text-[var(--se-error)] py-4">{err}</p></Shell>;
  if (!tl || !tl.start || !tl.end) return null;

  const t = hasTotals(tl.totals) ? tl.totals : null;
  const s = (tl.stress && 'grow_days' in tl.stress ? tl.stress : null) as RunStress | null;
  const S = tl.summary;

  // shared date domain (padded to whole months) + spine x-scale
  const ds = new Date(tl.start + 'T00:00:00'); const de = new Date(tl.end + 'T00:00:00');
  const dom0 = new Date(ds.getFullYear(), ds.getMonth(), 1).getTime();
  const dom1 = new Date(de.getFullYear(), de.getMonth() + 1, 1).getTime();
  const span = Math.max(1, dom1 - dom0);
  const pct = (d: string) => Math.max(0, Math.min(100, ((day(d) - dom0) / span) * 100));
  // scale the scrollable width with the reported span so long sims scroll through fully
  const years = span / (365.25 * 864e5);
  const chartW = Math.max(560, Math.round(years * 300));
  const yearLines: { x: number; y: number }[] = [];
  for (let y = ds.getFullYear(); y <= de.getFullYear(); y++) yearLines.push({ x: pct(`${y}-01-01`), y });

  const ferts = tl.events.filter(e => e.type === 'fertilizer');
  // stress windows (contiguous buckets with strsw>0.5) for shading
  const stressBands: { x1: string; x2: string }[] = [];
  let open: string | null = null;
  buckets.forEach((b, i) => {
    const stressed = (b.strsw as number || 0) > 0.5;
    if (stressed && open == null) open = b.date;
    if ((!stressed || i === buckets.length - 1) && open != null) {
      stressBands.push({ x1: open, x2: b.date }); open = null;
    }
  });

  const v = t && s ? verdict(t, s) : null;

  return (
    <Shell>
      {/* ---- verdict banner ---- */}
      {v && t && s && <VerdictBanner v={v} t={t} s={s} onJump={setLens} />}

      {/* ---- stat cards ---- */}
      {t && (
        <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2 my-4">
          <Stat label="Yield" value={fmt(t.yield_kgha / 1000, 1)} unit="t/ha" sub="at harvest" explain={explain} tip="Harvested biomass of the reported crop." />
          <Stat label="Rain" value={fmt(t.precip_mm)} unit="mm" sub="over the run" explain={explain} tip="Total precipitation the field received." />
          <Stat label="Irrigation" value={fmt(t.irr_mm)} unit="mm" sub={`${S.irrigation_events} events`} explain={explain} tip="Water auto-applied when the soil dried out." />
          <Stat label="Crop water use" value={fmt(t.et_mm)} unit="mm ET" sub={`of ${fmt(t.pet_mm)} demand`} explain={explain} tip="Actual evapotranspiration vs potential (PET) — how well supply met demand." />
          <Stat label="N applied" value={fmt(t.fertn_kgha)} unit="kg/ha" sub="manure + fert" explain={explain} tip="Nitrogen added as manure/fertilizer." />
          <Stat label="N leached" value={fmt(t.leached_kgha, 1)} unit="kg/ha" sub="to groundwater" explain={explain}
            tip="Nitrate that drained below the roots toward groundwater — the water-quality signal."
            tone={t.leached_kgha < 2 ? 'ok' : t.leached_kgha < 10 ? 'warn' : 'err'} />
        </div>
      )}

      {/* ---- control bar ---- */}
      <div className="flex flex-wrap items-center gap-2 mb-2">
        <Seg options={[['water', 'Water'], ['growth', 'Growth'], ['nitrogen', 'Nitrogen']]} value={lens} onChange={v => setLens(v as Lens)} />
        <div className="ml-auto flex items-center gap-2">
          {lens === 'nitrogen' && <Toggle on={cumulative} onClick={() => setCumulative(c => !c)}>Cumulative</Toggle>}
          <Seg small options={[['week', 'Wk'], ['month', 'Mo'], ['year', 'Yr']]} value={agg} onChange={v => setAgg(v as Agg)} />
          <Toggle on={explain} onClick={() => setExplain(e => !e)}><Info className="w-3 h-3" /></Toggle>
        </div>
      </div>

      {/* ---- crop spine (aligned above the hero chart plot area) ---- */}
      <div className="overflow-x-auto">
        <div style={{ minWidth: chartW }}>
          <div className="relative" style={{ marginLeft: 48, marginRight: 14 }}>
            {/* year axis */}
            <div className="relative h-4 mb-0.5">
              {yearLines.map((yl, i) => (
                <span key={i} className="absolute top-0 text-[10px] font-semibold text-[var(--se-text-mut)]" style={{ left: `${yl.x}%` }}>{yl.y}</span>
              ))}
            </div>
            <div className="relative h-12">
              {yearLines.map((yl, i) => (
                <div key={`yg${i}`} className="absolute top-0 bottom-0 w-px bg-[var(--se-border-lt)]" style={{ left: `${yl.x}%` }} />
              ))}
              {stressBands.map((b, i) => (
                <div key={`s${i}`} className="absolute top-0 bottom-0 bg-[#dc2626]/10" title="Crop was water-stressed here"
                  style={{ left: `${pct(b.x1)}%`, width: `${Math.max(0.5, pct(b.x2) - pct(b.x1))}%` }} />
              ))}
              {tl.crops.map((c, i) => {
                const left = c.plant ? pct(c.plant) : 0;
                const right = c.harvest ? pct(c.harvest) : 100;
                const col = colorFor(c.crop);
                return (
                  <div key={i} className="absolute top-0 bottom-0 rounded-lg flex items-center px-2 overflow-hidden shadow-sm"
                    style={{ left: `${left}%`, width: `${Math.max(3, right - left)}%`, background: `${col}22`, border: `1.5px solid ${col}` }}
                    title={`${c.label}${c.plant ? ` · planted ${c.plant}` : ''}${c.harvest ? ` · harvested ${c.harvest}` : ' · growing'}${c.biomass_kgha != null ? ` · biomass ${fmt(c.biomass_kgha)} kg/ha` : ''}`}>
                    <span className="text-base leading-none mr-1.5 shrink-0">{iconFor(c.crop)}</span>
                    <span className="min-w-0">
                      <span className="block text-[11px] font-semibold truncate leading-tight">{c.label}</span>
                      {c.biomass_kgha != null && <span className="block text-[9px] text-[var(--se-text-mut)] leading-tight">{fmt(c.biomass_kgha)} kg/ha</span>}
                    </span>
                  </div>
                );
              })}
              {ferts.map((f, i) => (
                <div key={`f${i}`} className="absolute -top-1 -translate-x-1/2" style={{ left: `${pct(f.date)}%` }}
                  title={`${f.label} · ${fmt(f.amount)} ${f.unit} · ${f.date}`}>
                  <FlaskConical className="w-3.5 h-3.5 text-[#d97706]" />
                </div>
              ))}
            </div>
          </div>

          {/* ---- hero chart ---- */}
          <div className="mt-1">
            <HeroChart lens={lens} data={buckets} cumulative={cumulative} stressBands={stressBands} ferts={ferts} crops={tl.crops} agg={agg} />
          </div>
        </div>
      </div>

      {/* ---- scientific details ---- */}
      <button onClick={() => setShowSci(x => !x)}
        className="mt-3 flex items-center gap-1.5 text-xs font-medium text-[var(--se-text-mut)] hover:text-[var(--se-accent)]">
        {showSci ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />} Scientific details
      </button>
      {showSci && t && s && <SciDetails t={t} s={s} />}

      <p className="text-[10px] text-[var(--se-text-fnt)] mt-3 flex items-center gap-1">
        <CalendarRange className="w-3 h-3" /> {tl.start} → {tl.end} · from the model run · uncalibrated single-field model — read as directional scenario estimates.
      </p>
    </Shell>
  );
}

/* ================= sub-components ================= */
function HeroChart({ lens, data, cumulative, stressBands, ferts, crops, agg }: {
  lens: Lens; data: Bucket[]; cumulative: boolean;
  stressBands: { x1: string; x2: string }[]; ferts: RT['events']; crops: RT['crops']; agg: Agg;
}) {
  const tickFmt = (d: string) => {
    const dt = new Date(d + 'T00:00:00');
    if (agg === 'year') return `${dt.getFullYear()}`;
    return dt.getMonth() === 0 ? `${MONTHS[0]} ${dt.getFullYear()}` : MONTHS[dt.getMonth()];
  };
  const grid = <CartesianGrid strokeDasharray="3 3" stroke="var(--se-border-lt)" vertical={false} />;
  const xAxis = <XAxis dataKey="date" tickFormatter={tickFmt} tick={{ fontSize: 10, fill: 'var(--se-text-fnt)' }} interval="preserveStartEnd" minTickGap={28} />;
  // the bucket CONTAINING date d = the last bucket that starts on/before d
  const bucketAt = (d: string) => {
    for (let i = data.length - 1; i >= 0; i--) if (data[i].date <= d) return data[i].date;
    return data[0]?.date;
  };
  const shade = stressBands.map((b, i) => <ReferenceArea key={`sh${i}`} x1={b.x1} x2={b.x2} fill={C.stress} fillOpacity={0.07} ifOverflow="extendDomain" />);
  const fertLines = ferts.map(f => bucketAt(f.date)).filter((x): x is string => !!x)
    .map((x, i) => <ReferenceLine key={`fl${i}`} yAxisId="l" x={x} stroke={C.fertn} strokeDasharray="2 2" strokeOpacity={0.5} />);
  const tip = <Tooltip content={<TipBox lens={lens} cumulative={cumulative} />} />;

  if (lens === 'growth') {
    const harvests = crops.filter(c => c.harvest && c.biomass_kgha);
    return (
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={data} margin={{ top: 6, right: 14, left: 8, bottom: 0 }} syncId="rt">
          {grid}{xAxis}
          <YAxis yAxisId="l" width={40} tick={{ fontSize: 10, fill: 'var(--se-text-fnt)' }} />
          <YAxis yAxisId="r" orientation="right" width={32} tick={{ fontSize: 10, fill: 'var(--se-text-fnt)' }} />
          {shade}
          <Area yAxisId="l" dataKey="bioms" name="Biomass" stroke={C.bioms} fill={C.bioms} fillOpacity={0.18} strokeWidth={2} dot={false} />
          <Line yAxisId="r" dataKey="lai" name="Canopy (LAI)" stroke={C.lai} strokeWidth={1.5} dot={false} />
          {harvests.map((h, i) => { const x = bucketAt(h.harvest || ''); return x ? <ReferenceDot key={`hv${i}`} yAxisId="l" x={x} y={h.biomass_kgha || 0} r={4} fill={C.yield} stroke="#fff" /> : null; })}
          {tip}
        </ComposedChart>
      </ResponsiveContainer>
    );
  }
  if (lens === 'nitrogen') {
    return (
      <ResponsiveContainer width="100%" height={200}>
        <ComposedChart data={data} margin={{ top: 6, right: 14, left: 8, bottom: 0 }} syncId="rt">
          {grid}{xAxis}
          <YAxis yAxisId="l" width={40} tick={{ fontSize: 10, fill: 'var(--se-text-fnt)' }} />
          {fertLines}
          <Bar yAxisId="l" dataKey="fertn" name="N applied" fill={C.fertn} barSize={cumulative ? 6 : undefined} />
          <Line yAxisId="l" dataKey={cumulative ? 'nuptake_cum' : 'nuptake'} name="Crop uptake" stroke={C.uptake} strokeWidth={1.5} dot={false} />
          <Area yAxisId="l" dataKey={cumulative ? 'leached_cum' : 'leached'} name="N leached" stroke={C.leached} fill={C.leached} fillOpacity={0.2} strokeWidth={2} dot={false} />
          {tip}
        </ComposedChart>
      </ResponsiveContainer>
    );
  }
  // water (default)
  return (
    <ResponsiveContainer width="100%" height={200}>
      <ComposedChart data={data} margin={{ top: 6, right: 14, left: 8, bottom: 0 }} syncId="rt">
        {grid}{xAxis}
        <YAxis yAxisId="l" width={40} tick={{ fontSize: 10, fill: 'var(--se-text-fnt)' }} />
        <YAxis yAxisId="r" orientation="right" width={32} tick={{ fontSize: 10, fill: 'var(--se-text-fnt)' }} />
        {shade}
        <Area yAxisId="r" dataKey="sw_ave" name="Soil moisture" stroke={C.sw} fill={C.sw} fillOpacity={0.12} strokeWidth={1.5} dot={false} />
        <Bar yAxisId="l" dataKey="precip" name="Rain" fill={C.rain} stackId="w" />
        <Bar yAxisId="l" dataKey="irr" name="Irrigation" fill={C.irr} stackId="w" />
        <Line yAxisId="l" dataKey="et" name="Crop water use (ET)" stroke={C.et} strokeWidth={1.5} dot={false} />
        {tip}
      </ComposedChart>
    </ResponsiveContainer>
  );
}

const TIP_ROWS: Record<Lens, { key: string; label: string; unit: string; color: string }[]> = {
  water: [{ key: 'precip', label: 'Rain', unit: 'mm', color: C.rain }, { key: 'irr', label: 'Irrigation', unit: 'mm', color: C.irr },
    { key: 'et', label: 'ET', unit: 'mm', color: C.et }, { key: 'sw_ave', label: 'Soil moisture', unit: 'mm', color: C.sw }],
  growth: [{ key: 'bioms', label: 'Biomass', unit: 'kg/ha', color: C.bioms }, { key: 'lai', label: 'Canopy LAI', unit: '', color: C.lai },
    { key: 'strsw', label: 'Water stress', unit: '', color: C.stress }],
  nitrogen: [{ key: 'fertn', label: 'N applied', unit: 'kg/ha', color: C.fertn }, { key: 'nuptake', label: 'Crop uptake', unit: 'kg/ha', color: C.uptake },
    { key: 'leached', label: 'N leached', unit: 'kg/ha', color: C.leached }, { key: 'denit', label: 'Denitrified', unit: 'kg/ha', color: C.denit }],
};
function TipBox({ active, payload, label, lens, cumulative }: any) {
  if (!active || !payload?.length) return null;
  const row = payload[0]?.payload as Bucket;
  const dt = new Date((label as string) + 'T00:00:00');
  return (
    <div className="bg-[var(--se-card)] border border-[var(--se-border)] rounded-lg shadow-lg px-3 py-2 text-[11px]">
      <p className="font-semibold mb-1">{MONTHS[dt.getMonth()]} {dt.getDate()}, {dt.getFullYear()}</p>
      {(TIP_ROWS[lens as Lens]).map(r => {
        const v = row[cumulative && ['nuptake', 'leached', 'denit', 'fertn'].includes(r.key) ? `${r.key}_cum` : r.key];
        return (
          <div key={r.key} className="flex items-center justify-between gap-3">
            <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-full" style={{ background: r.color }} />{r.label}</span>
            <span className="font-medium tabular-nums">{typeof v === 'number' ? v.toLocaleString(undefined, { maximumFractionDigits: 1 }) : '—'} {r.unit}</span>
          </div>
        );
      })}
    </div>
  );
}

function VerdictBanner({ v, t, s, onJump }: { v: ReturnType<typeof verdict>; t: RunTotals; s: RunStress; onJump: (l: Lens) => void }) {
  const crop = t.yield_kgha > 0 ? `harvested ${fmt(t.yield_kgha / 1000, 1)} t/ha` : 'grew';
  const sentence = `The crop ${crop}. ${v.water === 'good' ? 'Watering kept up with demand' : v.water === 'ok' ? 'Watering mostly kept up' : `The crop was thirsty ${s.water_days} days`}${v.nleach === 'good' ? ' and little nitrogen leached.' : v.nleach === 'ok' ? `, and ${fmt(t.leached_kgha, 1)} kg/ha of nitrogen leached below the roots.` : `, but ${fmt(t.leached_kgha, 1)} kg/ha of nitrogen leached toward groundwater.`}`;
  return (
    <div className="rounded-xl border border-[var(--se-border)] bg-[var(--se-rail)] px-4 py-3 mb-1">
      <p className="text-sm text-[var(--se-text)]">{sentence}</p>
      <div className="flex flex-wrap gap-2 mt-2">
        <Pill status={v.cropH} label="Crop health" onClick={() => onJump('growth')} />
        <Pill status={v.water} label="Watering" onClick={() => onJump('water')} />
        <Pill status={v.nleach} label="Nitrogen" onClick={() => onJump('nitrogen')} />
      </div>
    </div>
  );
}
function Pill({ status, label, onClick }: { status: Status; label: string; onClick: () => void }) {
  const map = {
    good: ['bg-[var(--se-ok-sf)] text-[var(--se-ok)] border-[color:var(--se-ok-bd)]', <CheckCircle2 key="i" className="w-3 h-3" />],
    ok: ['bg-amber-50 text-amber-700 border-amber-200', <CircleAlert key="i" className="w-3 h-3" />],
    warn: ['bg-[var(--se-error-sf)] text-[var(--se-error)] border-[color:var(--se-error-bd)]', <AlertTriangle key="i" className="w-3 h-3" />],
  } as const;
  const [cls, icon] = map[status];
  return <button onClick={onClick} className={clsx('inline-flex items-center gap-1 text-[11px] font-medium rounded-full px-2.5 py-1 border hover:opacity-80', cls)}>{icon}{label}</button>;
}

function SciDetails({ t, s }: { t: RunTotals; s: RunStress }) {
  const water = [
    { name: 'Rain', v: t.precip_mm, fill: C.rain }, { name: 'Irrigation', v: t.irr_mm, fill: C.irr },
    { name: 'ET', v: t.et_mm, fill: C.et }, { name: 'Deep perc', v: t.perc_mm, fill: C.perc },
    { name: 'Runoff', v: t.surq_mm, fill: '#6d5ae0' }, { name: 'Δ soil water', v: t.sw_delta, fill: C.sw },
  ];
  const nbud = [
    { name: 'Applied', v: t.fertn_kgha, fill: C.fertn }, { name: 'Fixation', v: t.fixn_kgha, fill: C.bioms },
    { name: 'Uptake', v: -t.nuptake_kgha, fill: C.uptake }, { name: 'Leached', v: -t.leached_kgha, fill: C.leached },
    { name: 'Denitrified', v: -t.denit_kgha, fill: C.denit },
  ];
  const stress = [
    { name: 'Water', v: s.water_days, fill: C.rain }, { name: 'Nitrogen', v: s.n_days, fill: '#f59e0b' },
    { name: 'Heat/cold', v: s.temp_days, fill: C.fertn }, { name: 'Waterlogged', v: s.aeration_days, fill: C.denit },
  ];
  return (
    <div className="grid md:grid-cols-3 gap-4 mt-3 p-3 rounded-xl bg-[var(--se-rail)] border border-[var(--se-border-lt)]">
      <MiniBar title="Water balance (mm)" data={water} />
      <MiniBar title="Nitrogen budget (kg/ha)" data={nbud} diverging />
      <MiniBar title={`Stress days (of ${s.grow_days} growing)`} data={stress} horizontal />
    </div>
  );
}
function MiniBar({ title, data, diverging, horizontal }: { title: string; data: { name: string; v: number; fill: string }[]; diverging?: boolean; horizontal?: boolean }) {
  return (
    <div>
      <p className="text-[11px] font-semibold text-[var(--se-text-mut)] mb-1.5">{title}</p>
      <ResponsiveContainer width="100%" height={140}>
        <BarChart data={data} layout={horizontal ? 'vertical' : 'horizontal'} margin={{ top: 2, right: 8, left: horizontal ? 8 : 0, bottom: 0 }}>
          {horizontal ? <>
            <XAxis type="number" tick={{ fontSize: 9, fill: 'var(--se-text-fnt)' }} />
            <YAxis type="category" dataKey="name" width={64} tick={{ fontSize: 9, fill: 'var(--se-text-mut)' }} />
          </> : <>
            <XAxis dataKey="name" tick={{ fontSize: 9, fill: 'var(--se-text-mut)' }} interval={0} angle={-20} textAnchor="end" height={40} />
            <YAxis tick={{ fontSize: 9, fill: 'var(--se-text-fnt)' }} width={32} />
          </>}
          {diverging && <ReferenceLine y={0} stroke="var(--se-border)" />}
          <Tooltip cursor={{ fill: 'var(--se-border-lt)', fillOpacity: 0.3 }} contentStyle={{ fontSize: 11, borderRadius: 8, border: '1px solid var(--se-border)', background: 'var(--se-card)' }} />
          <Bar dataKey="v" radius={3}>{data.map((d, i) => <Cell key={i} fill={d.fill} />)}</Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ---------- primitives ---------- */
function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="bg-[var(--se-card)] border border-[var(--se-border)] rounded-2xl p-5 shadow-sm">
      <div className="flex items-center gap-2 mb-3">
        <CalendarRange className="w-4 h-4 text-[var(--se-accent)]" />
        <h3 className="text-sm font-semibold text-[var(--se-text)]">Run timeline</h3>
      </div>
      {children}
    </div>
  );
}
const Row = ({ children }: { children: React.ReactNode }) => <div className="flex items-center gap-2 text-sm text-[var(--se-text-mut)] py-6">{children}</div>;

function Stat({ label, value, unit, sub, tone, explain, tip }: {
  label: string; value: string; unit: string; sub: string; tone?: 'ok' | 'warn' | 'err'; explain?: boolean; tip?: string;
}) {
  const tint = tone === 'err' ? 'bg-[var(--se-error-sf)] border-[color:var(--se-error-bd)]'
    : tone === 'warn' ? 'bg-amber-50 border-amber-200'
    : tone === 'ok' ? 'bg-[var(--se-ok-sf)] border-[color:var(--se-ok-bd)]'
    : 'bg-[var(--se-rail)] border-[var(--se-border-lt)]';
  return (
    <div className={clsx('rounded-xl border px-3 py-2.5', tint)} title={explain ? tip : undefined}>
      <div className="flex items-center gap-1 text-[10px] font-medium text-[var(--se-text-mut)] uppercase tracking-wide">
        {label}{explain && <Info className="w-2.5 h-2.5 opacity-60" />}
      </div>
      <div className="mt-0.5 flex items-baseline gap-1"><span className="text-lg font-semibold tabular-nums leading-none">{value}</span><span className="text-[10px] text-[var(--se-text-mut)]">{unit}</span></div>
      <div className="text-[9px] text-[var(--se-text-fnt)] mt-0.5">{sub}</div>
    </div>
  );
}

function Seg({ options, value, onChange, small }: { options: [string, string][]; value: string; onChange: (v: string) => void; small?: boolean }) {
  return (
    <div className="inline-flex rounded-lg border border-[var(--se-border)] bg-[var(--se-card)] p-0.5">
      {options.map(([val, lbl]) => (
        <button key={val} onClick={() => onChange(val)}
          className={clsx('rounded-md font-medium transition-colors', small ? 'text-[11px] px-2 py-1' : 'text-xs px-3 py-1',
            value === val ? 'bg-[var(--se-accent)] text-white' : 'text-[var(--se-text-mut)] hover:text-[var(--se-text)]')}>{lbl}</button>
      ))}
    </div>
  );
}
function Toggle({ on, onClick, children }: { on: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button onClick={onClick}
      className={clsx('inline-flex items-center gap-1 text-[11px] font-medium rounded-lg px-2.5 py-1 border',
        on ? 'bg-[var(--se-accent-sf)] text-[var(--se-accent)] border-[var(--se-accent-bd)]' : 'text-[var(--se-text-mut)] border-[var(--se-border)] hover:text-[var(--se-text)]')}>{children}</button>
  );
}
