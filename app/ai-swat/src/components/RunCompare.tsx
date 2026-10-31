import { Fragment, useEffect, useMemo, useState } from 'react';
import { swatModel, type RunTimeline, type RunDay, type SimResult } from '@/lib/api';
import { X, Loader2, GitCompare, FileDown } from 'lucide-react';
import clsx from 'clsx';

const COLORS = ['#0068C1', '#B06B2C', '#3F7A3C', '#8A5A08', '#6B5B9E'];
const METRICS: { key: string; label: string; unit: string; dp: number; lowerBetter?: boolean }[] = [
  { key: 'yield_kgha', label: 'Yield', unit: 'kg/ha', dp: 0 },
  { key: 'leached_kgha', label: 'N leached', unit: 'kg/ha', dp: 1, lowerBetter: true },
  { key: 'nuptake_kgha', label: 'N uptake', unit: 'kg/ha', dp: 1 },
  { key: 'fertn_kgha', label: 'N applied', unit: 'kg/ha', dp: 1 },
  { key: 'irr_mm', label: 'Irrigation', unit: 'mm', dp: 0, lowerBetter: true },
  { key: 'et_mm', label: 'Evapotranspiration', unit: 'mm', dp: 0 },
  { key: 'precip_mm', label: 'Precipitation', unit: 'mm', dp: 0 },
  { key: 'perc_mm', label: 'Percolation', unit: 'mm', dp: 0, lowerBetter: true },
];
const CHART_KEYS = ['yield_kgha', 'leached_kgha', 'irr_mm', 'et_mm'];

// per-day series fields we can plot over time, and how to aggregate to a year
const SERIES_METRICS: { key: string; label: string; unit: string; agg: 'sum' | 'mean' | 'max' }[] = [
  { key: 'sw_ave', label: 'Soil water', unit: 'mm (yr mean)', agg: 'mean' },
  { key: 'et', label: 'ET', unit: 'mm/yr', agg: 'sum' },
  { key: 'bioms', label: 'Biomass', unit: 'kg/ha (yr peak)', agg: 'max' },
  { key: 'percn', label: 'N leached', unit: 'kg/ha/yr', agg: 'sum' },
];

type Row = { id: string; name: string; tl: RunTimeline };

// SWAT+ logs four growth-stress factors per day (0 = unstressed, 1 = fully limiting).
// Averaged over days the crop is standing, they say directly what is holding yield back.
const STRESS = [
  { key: 'strstmp', label: 'Temperature', driver: 'tmp_opt / tmp_base in plants.plt' },
  { key: 'strsw', label: 'Water', driver: 'irrigation trigger, soil water holding' },
  { key: 'strsn', label: 'Nitrogen', driver: 'fertiliser supply + uptake parameters' },
  { key: 'strsa', label: 'Aeration', driver: 'waterlogging / drainage' },
];

/** Growth-limitation, canopy and efficiency diagnostics for one run. */
function diagnose(tl: RunTimeline) {
  const ser = tl.series || [];
  const num = (d: RunDay, k: string) => Number((d as Record<string, unknown>)[k]) || 0;
  const grow = ser.filter(d => num(d, 'bioms') > 1);
  const n = Math.max(1, grow.length);
  const stress = STRESS.map(s => {
    const vals = grow.map(d => num(d, s.key));
    return {
      ...s,
      mean: vals.reduce((a, b) => a + b, 0) / n,
      pct: (vals.filter(v => v > 0.5).length / n) * 100,
    };
  }).sort((a, b) => b.mean - a.mean);
  const lai = grow.map(d => num(d, 'lai'));
  const et = ser.reduce((a, d) => a + num(d, 'et'), 0);
  const pet = ser.reduce((a, d) => a + num(d, 'pet'), 0);
  const t = (tl.totals || {}) as Record<string, number>;
  const applied = t.fertn_kgha || 0;
  return {
    stress,
    growDays: grow.length,
    laiPeak: lai.length ? Math.max(...lai) : 0,
    laiMean: lai.reduce((a, b) => a + b, 0) / n,
    etPet: pet ? et / pet : 0,
    nue: t.nue_pct || 0,
    leachFrac: applied ? ((t.leached_kgha || 0) / applied) * 100 : 0,
    irrEvents: ser.filter(d => num(d, 'irr') > 0).length,
    years: new Set(ser.map(d => String(d.date).slice(0, 4))).size,
    // years that actually received nitrogen — the agronomically meaningful denominator
    fertYears: new Set(ser.filter(d => num(d, 'fertn') > 0).map(d => String(d.date).slice(0, 4))).size,
    waterIn: (t.precip_mm || 0) + (t.irr_mm || 0),
    waterOut: (t.et_mm || 0) + (t.perc_mm || 0) + (t.surq_mm || 0) + (t.latq_mm || 0),
    swDelta: t.sw_delta || 0,
    nIn: applied + (t.fixn_kgha || 0),
    nOut: (t.nuptake_kgha || 0) + (t.leached_kgha || 0) + (t.denit_kgha || 0),
  };
}

function yearly(series: RunDay[], key: string, agg: 'sum' | 'mean' | 'max'): { yr: number; v: number }[] {
  const by: Record<number, number[]> = {};
  for (const d of series) {
    const y = Number(String(d.date).slice(0, 4));
    const v = Number((d as Record<string, unknown>)[key]);
    if (Number.isFinite(y) && Number.isFinite(v)) (by[y] ||= []).push(v);
  }
  return Object.keys(by).map(Number).sort((a, b) => a - b).map(y => {
    const vs = by[y];
    const v = agg === 'sum' ? vs.reduce((a, b) => a + b, 0)
      : agg === 'max' ? Math.max(...vs)
        : vs.reduce((a, b) => a + b, 0) / vs.length;
    return { yr: y, v };
  });
}

export default function RunCompare({ farmId, runIds, onClose }: {
  farmId: string; runIds: string[]; onClose: () => void;
}) {
  const [rows, setRows] = useState<Row[]>([]);
  const [loading, setLoading] = useState(true);
  const [metric, setMetric] = useState('sw_ave');
  const [showYears, setShowYears] = useState(false);

  useEffect(() => {
    let alive = true; setLoading(true);
    (async () => {
      const meta = await swatModel.listRuns(farmId).catch(() => [] as SimResult[]);
      const nameOf = (id: string) => {
        const r = meta.find(m => m.run_id === id);
        return r?.label || r?.scenario || id.slice(0, 8);
      };
      const tls = await Promise.all(runIds.map(id =>
        swatModel.timeline(id).then(tl => ({ id, name: nameOf(id), tl })).catch(() => null)));
      if (alive) { setRows(tls.filter(Boolean) as Row[]); setLoading(false); }
    })();
    return () => { alive = false; };
  }, [farmId, runIds]);

  const val = (tl: RunTimeline, k: string): number | undefined => (tl.totals as Record<string, number>)?.[k];

  // overlaid yearly series per run for the selected metric
  const lines = useMemo(() => {
    const m = SERIES_METRICS.find(x => x.key === metric)!;
    return rows.map((r, i) => ({ name: r.name, color: COLORS[i % COLORS.length], pts: yearly(r.tl.series || [], m.key, m.agg) }));
  }, [rows, metric]);

  const diags = useMemo(() => rows.map(r => diagnose(r.tl)), [rows]);

  // per-crop: harvest count, mean standing biomass, mean yield, realised harvest index
  const cropStats = useMemo(() => {
    const perRun = rows.map(r => {
      const acc: Record<string, { n: number; bio: number; yld: number; hi: number }> = {};
      for (const c of r.tl.crops || []) {
        if (c.biomass_kgha == null) continue;          // still standing, not harvested
        const k = c.label || c.crop;
        (acc[k] ||= { n: 0, bio: 0, yld: 0, hi: 0 });
        acc[k].n += 1;
        acc[k].bio += c.biomass_kgha || 0;
        acc[k].yld += c.yield_kgha || 0;
      }
      for (const k of Object.keys(acc)) {
        const a = acc[k];
        a.bio /= a.n; a.yld /= a.n;
        a.hi = a.bio ? a.yld / a.bio : 0;
      }
      return acc;
    });
    const labels = [...new Set(perRun.flatMap(m => Object.keys(m)))]
      .sort((a, b) => (perRun.reduce((s, m) => s + (m[b]?.n || 0), 0))
        - (perRun.reduce((s, m) => s + (m[a]?.n || 0), 0)));
    return { perRun, labels };
  }, [rows]);

  // year-by-year water and nitrate detail
  const yearTable = useMemo(() => {
    const toMap = (pts: { yr: number; v: number }[]) =>
      Object.fromEntries(pts.map(p => [p.yr, p.v])) as Record<number, number>;
    const perRun = rows.map(r => ({
      irr: toMap(yearly(r.tl.series || [], 'irr', 'sum')),
      et: toMap(yearly(r.tl.series || [], 'et', 'sum')),
      sw: toMap(yearly(r.tl.series || [], 'sw_ave', 'mean')),
      pn: toMap(yearly(r.tl.series || [], 'percn', 'sum')),
    }));
    const precip = toMap(yearly(rows[0]?.tl.series || [], 'precip', 'sum'));
    const years = [...new Set(perRun.flatMap(m => Object.keys(m.irr).map(Number)))].sort((a, b) => a - b);
    return { perRun, precip, years };
  }, [rows]);

  // Print the comparison on its own. The panel is temporarily MOVED to be a direct
  // child of <body> and every sibling hidden, then put back afterwards.
  // Hiding-in-place with `visibility` + `position:absolute` (the obvious approach)
  // clips the output to a single page, because absolutely positioned content cannot
  // paginate — which silently truncated the report once it grew past one page.
  const savePdf = () => {
    const el = document.getElementById('run-compare-print');
    if (!el) { window.print(); return; }
    const anchor = document.createComment('run-compare');
    const holder = document.createElement('div');
    holder.id = 'run-compare-holder';
    el.parentNode?.replaceChild(anchor, el);
    holder.appendChild(el);
    document.body.appendChild(holder);
    document.body.classList.add('print-compare');

    let done = false;
    const cleanup = () => {
      if (done) return;
      done = true;
      anchor.parentNode?.replaceChild(el, anchor);
      holder.remove();
      document.body.classList.remove('print-compare');
      window.removeEventListener('afterprint', cleanup);
    };
    window.addEventListener('afterprint', cleanup);
    setTimeout(() => { window.print(); setTimeout(cleanup, 800); }, 60);
  };

  if (loading) return (
    <div className="flex items-center justify-center gap-2 py-10 text-sm text-[var(--se-text-mut)]">
      <Loader2 className="w-4 h-4 animate-spin" /> Loading runs to compare…
    </div>
  );
  if (rows.length < 2) return (
    <div className="rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] p-6 text-sm text-[var(--se-text-mut)]">
      Couldn&apos;t load enough runs to compare. <button onClick={onClose} className="text-[var(--se-accent)]">Back to timeline</button>
    </div>
  );

  const mSel = SERIES_METRICS.find(x => x.key === metric)!;
  const allYears = [...new Set(lines.flatMap(l => l.pts.map(p => p.yr)))].sort((a, b) => a - b);
  const vmax = Math.max(1, ...lines.flatMap(l => l.pts.map(p => p.v)));
  const CW = 640, CH = 210, ml = 44, mt = 10, mb = 24;
  const xOf = (yr: number) => allYears.length <= 1 ? ml : ml + (yr - allYears[0]) / (allYears[allYears.length - 1] - allYears[0]) * (CW - ml - 8);
  const yOf = (v: number) => mt + (CH - mt - mb) * (1 - v / vmax);

  return (
    <div id="run-compare-print" className="rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] overflow-hidden">
      <style>{`@media print{
        /* savePdf() moves this panel into #run-compare-holder at body level, so simply
           hiding body's other children isolates it WITHOUT absolute positioning —
           which is what lets the report flow across as many pages as it needs. */
        body.print-compare>*:not(#run-compare-holder){display:none!important}
        body.print-compare #run-compare-holder{display:block}
        body.print-compare #run-compare-print{border:0;border-radius:0;background:#fff;overflow:visible!important}
        body.print-compare .no-print{display:none!important}
        /* keep related blocks whole, but let long tables paginate */
        body.print-compare .grid>*{break-inside:avoid}
        body.print-compare svg{break-inside:avoid}
        body.print-compare tr{break-inside:avoid}
        body.print-compare thead{display:table-header-group}
        body.print-compare table{width:100%;table-layout:auto;font-size:10px;break-inside:auto}
        body.print-compare th,body.print-compare td{padding:4px 7px!important;white-space:normal!important}
        @page{size:A4;margin:12mm 10mm}
      }`}</style>

      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--se-border-lt)]">
        <GitCompare className="w-4 h-4 text-[var(--se-accent)]" />
        <span className="text-sm font-semibold text-[var(--se-text)]">Comparing {rows.length} runs</span>
        <div className="ml-auto flex items-center gap-2 no-print">
          <button onClick={savePdf} title="Save this comparison as a PDF"
            className="flex items-center gap-1 text-xs px-2.5 py-1.5 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:text-[var(--se-accent)] hover:border-[var(--se-accent-bd)]">
            <FileDown className="w-3.5 h-3.5" /> Save PDF
          </button>
          <button onClick={onClose} className="flex items-center gap-1 text-xs text-[var(--se-text-mut)] hover:text-[var(--se-text)]">
            <X className="w-3.5 h-3.5" /> Close
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1 px-4 py-2 border-b border-[var(--se-border-lt)] text-[11px]">
        {rows.map((r, i) => (
          <span key={r.id} className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full shrink-0" style={{ background: COLORS[i % COLORS.length] }} />
            <span className="text-[var(--se-text)] font-medium">{r.name}</span>
            <span className="text-[var(--se-text-fnt)]">{r.tl.start?.slice(0, 4)}–{r.tl.end?.slice(0, 4)}</span>
          </span>
        ))}
      </div>

      {/* metric comparison table */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-[var(--se-bg)]">
              <th className="text-left px-4 py-2 text-[var(--se-text-fnt)] font-medium">Metric</th>
              {rows.map((r, i) => (
                <th key={r.id} className="text-right px-4 py-2 font-medium whitespace-nowrap" style={{ color: COLORS[i % COLORS.length] }}>{r.name}</th>
              ))}
              <th className="text-right px-4 py-2 text-[var(--se-text-fnt)] font-medium whitespace-nowrap">Δ last vs 1st</th>
            </tr>
          </thead>
          <tbody>
            {METRICS.map(m => {
              const vals = rows.map(r => val(r.tl, m.key));
              const nums = vals.filter((v): v is number => typeof v === 'number');
              if (!nums.length) return null;
              const best = m.lowerBetter ? Math.min(...nums) : Math.max(...nums);
              const base = vals[0], last = vals[vals.length - 1];
              const delta = (typeof base === 'number' && typeof last === 'number' && base !== 0) ? (last - base) / Math.abs(base) * 100 : null;
              const deltaGood = delta == null ? null : (m.lowerBetter ? delta < 0 : delta > 0);
              return (
                <tr key={m.key} className="border-t border-[var(--se-border-lt)]">
                  <td className="px-4 py-2 text-[var(--se-text-mut)] whitespace-nowrap">{m.label} <span className="text-[var(--se-text-fnt)]">({m.unit})</span></td>
                  {vals.map((v, i) => (
                    <td key={i} className={clsx('px-4 py-2 text-right tabular-nums',
                      v === best ? 'font-semibold text-[var(--se-text)]' : 'text-[var(--se-text-mut)]')}>
                      {typeof v === 'number' ? v.toFixed(m.dp) : '—'}
                    </td>
                  ))}
                  <td className={clsx('px-4 py-2 text-right tabular-nums',
                    delta == null ? 'text-[var(--se-text-fnt)]' : deltaGood ? 'text-[var(--se-ok)]' : 'text-[var(--se-warn)]')}>
                    {delta == null ? '—' : `${delta > 0 ? '+' : ''}${delta.toFixed(0)}%`}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* overlaid time-series */}
      <div className="border-t border-[var(--se-border-lt)] px-4 pt-3 pb-4">
        <div className="flex items-center gap-2 mb-2 flex-wrap">
          <span className="text-[11px] font-semibold text-[var(--se-text-mut)]">Over time</span>
          <div className="flex gap-1 no-print">
            {SERIES_METRICS.map(sm => (
              <button key={sm.key} onClick={() => setMetric(sm.key)}
                className={clsx('text-[11px] px-2 py-0.5 rounded-md border',
                  metric === sm.key ? 'bg-[var(--se-accent)] text-white border-[var(--se-accent)]'
                    : 'border-[var(--se-border)] text-[var(--se-text-mut)] hover:border-[var(--se-accent-bd)]')}>
                {sm.label}
              </button>
            ))}
          </div>
          <span className="text-[11px] text-[var(--se-text-fnt)] ml-auto">{mSel.label} · {mSel.unit}</span>
        </div>
        <svg viewBox={`0 0 ${CW} ${CH}`} className="w-full h-auto" style={{ maxWidth: CW }}>
          {[0, 0.5, 1].map(f => {
            const yy = yOf(vmax * f);
            return <g key={f}>
              <line x1={ml} y1={yy} x2={CW - 8} y2={yy} stroke="var(--se-border)" />
              <text x={ml - 6} y={yy + 3} fontSize="9" fill="var(--se-text-fnt)" textAnchor="end" fontFamily="monospace">{(vmax * f).toFixed(0)}</text>
            </g>;
          })}
          {allYears.filter((_, i) => allYears.length <= 8 || i % 3 === 0).map(yr => (
            <text key={yr} x={xOf(yr)} y={CH - 8} fontSize="9" fill="var(--se-text-fnt)" textAnchor="middle" fontFamily="monospace">{yr}</text>
          ))}
          {lines.map(l => (
            <g key={l.name}>
              <polyline fill="none" stroke={l.color} strokeWidth="2"
                points={l.pts.map(p => `${xOf(p.yr).toFixed(1)},${yOf(p.v).toFixed(1)}`).join(' ')} />
              {l.pts.map(p => <circle key={p.yr} cx={xOf(p.yr)} cy={yOf(p.v)} r="2" fill={l.color} />)}
            </g>
          ))}
        </svg>
      </div>

      {/* bar charts of totals */}
      <div className="grid gap-4 sm:grid-cols-2 p-4 border-t border-[var(--se-border-lt)]">
        {CHART_KEYS.map(k => {
          const m = METRICS.find(x => x.key === k)!;
          const bars = rows.map((r, i) => ({ name: r.name, v: Number(val(r.tl, k)) || 0, c: COLORS[i % COLORS.length] }));
          const max = Math.max(...bars.map(b => b.v), 1);
          return (
            <div key={k} className="rounded-lg border border-[var(--se-border-lt)] p-3">
              <div className="text-[11px] font-semibold text-[var(--se-text-mut)] mb-2">{m.label} <span className="text-[var(--se-text-fnt)]">({m.unit})</span></div>
              <div className="space-y-1.5">
                {bars.map((b, i) => (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-[10px] w-16 truncate text-[var(--se-text-fnt)]" title={b.name}>{b.name}</span>
                    <div className="flex-1 h-4 bg-[var(--se-bg)] rounded overflow-hidden">
                      <div className="h-full rounded" style={{ width: `${b.v / max * 100}%`, background: b.c }} />
                    </div>
                    <span className="text-[10px] w-14 text-right tabular-nums text-[var(--se-text-mut)]">{b.v.toFixed(m.dp)}</span>
                  </div>
                ))}
              </div>
            </div>
          );
        })}
      </div>

      {/* ---- what is limiting the crop? the most diagnostic view ---- */}
      <div className="border-t border-[var(--se-border-lt)] px-4 py-4">
        <div className="text-[11px] font-semibold text-[var(--se-text)] mb-1">What is limiting the crop?</div>
        <p className="text-[11px] text-[var(--se-text-fnt)] mb-2">
          Daily growth-stress factors averaged over days with a standing crop. 0 = unstressed, 1 = fully limiting.
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead><tr className="bg-[var(--se-bg)]">
              <th className="text-left px-3 py-1.5 font-medium text-[var(--se-text-fnt)]">Stress</th>
              {rows.map((r, i) => (
                <th key={r.id} colSpan={2} className="px-3 py-1.5 font-medium text-center whitespace-nowrap"
                  style={{ color: COLORS[i % COLORS.length] }}>{r.name}</th>
              ))}
              <th className="text-left px-3 py-1.5 font-medium text-[var(--se-text-fnt)]">Governed by</th>
            </tr></thead>
            <tbody>
              {(diags[0]?.stress || []).map((_, si) => {
                const label = diags[0].stress[si].label;
                const driver = diags[0].stress[si].driver;
                const worst = Math.max(...diags.map(d => d.stress.find(s => s.label === label)?.mean ?? 0));
                return (
                  <tr key={label} className="border-t border-[var(--se-border-lt)]">
                    <td className="px-3 py-1.5 text-[var(--se-text-mut)]">{label}</td>
                    {diags.map((d, di) => {
                      const s = d.stress.find(x => x.label === label);
                      const hot = (s?.mean ?? 0) > 0.25;
                      const none = (s?.mean ?? 0) < 0.005;
                      return (
                        <Fragment key={di}>
                          <td className={clsx('px-3 py-1.5 text-right tabular-nums font-semibold',
                            hot ? 'text-[var(--se-error)]' : none ? 'text-[var(--se-ok)]' : 'text-[var(--se-text-mut)]')}>
                            {(s?.mean ?? 0).toFixed(3)}
                          </td>
                          <td className="px-1 py-1.5 text-right tabular-nums text-[var(--se-text-fnt)]">
                            {(s?.pct ?? 0).toFixed(0)}%
                          </td>
                        </Fragment>
                      );
                    })}
                    <td className="px-3 py-1.5 text-[var(--se-text-fnt)]">
                      {worst > 0.25 ? <strong className="text-[var(--se-text-mut)]">{driver}</strong> : driver}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        <p className="text-[10px] text-[var(--se-text-fnt)] mt-1.5">
          Second column per run = share of growing days above 0.5 (meaningfully limiting).
        </p>
      </div>

      {/* ---- per-crop performance: realised harvest index vs the parameter ---- */}
      <div className="border-t border-[var(--se-border-lt)] px-4 py-4">
        <div className="text-[11px] font-semibold text-[var(--se-text)] mb-1">Crop performance</div>
        <p className="text-[11px] text-[var(--se-text-fnt)] mb-2">
          Every harvest, averaged per crop. HI = yield ÷ biomass — compare with the crop&apos;s
          parameter (corn 0.55, wheat 0.40, potato 1.05).
        </p>
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-[var(--se-bg)]">
                <th rowSpan={2} className="text-left px-3 py-1.5 font-medium text-[var(--se-text-fnt)]">Crop</th>
                {rows.map((r, i) => (
                  <th key={r.id} colSpan={4} className="px-3 py-1 font-medium text-center whitespace-nowrap"
                    style={{ color: COLORS[i % COLORS.length] }}>{r.name}</th>
                ))}
              </tr>
              <tr className="bg-[var(--se-bg)]">
                {rows.map(r => (
                  <Fragment key={r.id}>
                    <th className="px-2 py-1 font-normal text-[10px] text-[var(--se-text-fnt)]">n</th>
                    <th className="px-2 py-1 font-normal text-[10px] text-[var(--se-text-fnt)]">biomass</th>
                    <th className="px-2 py-1 font-normal text-[10px] text-[var(--se-text-fnt)]">yield</th>
                    <th className="px-2 py-1 font-normal text-[10px] text-[var(--se-text-fnt)]">HI</th>
                  </Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {cropStats.labels.map(label => (
                <tr key={label} className="border-t border-[var(--se-border-lt)]">
                  <td className="px-3 py-1.5 text-[var(--se-text-mut)]">{label}</td>
                  {cropStats.perRun.map((m, i) => {
                    const c = m[label];
                    return (
                      <Fragment key={i}>
                        <td className="px-2 py-1.5 text-right tabular-nums text-[var(--se-text-mut)]">{c ? c.n : '—'}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-[var(--se-text-mut)]">{c ? c.bio.toFixed(0) : '—'}</td>
                        <td className="px-2 py-1.5 text-right tabular-nums text-[var(--se-text)]">{c ? c.yld.toFixed(0) : '—'}</td>
                        <td className={clsx('px-2 py-1.5 text-right tabular-nums',
                          c && c.hi < 0.1 ? 'text-[var(--se-error)] font-semibold' : 'text-[var(--se-text-fnt)]')}>
                          {c ? c.hi.toFixed(3) : '—'}
                        </td>
                      </Fragment>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---- year by year ---- */}
      <div className="border-t border-[var(--se-border-lt)] px-4 py-4">
        <div className="flex items-center gap-2 mb-1">
          <span className="text-[11px] font-semibold text-[var(--se-text)]">Year by year</span>
          <button onClick={() => setShowYears(v => !v)}
            className="no-print text-[11px] text-[var(--se-accent)] hover:underline">
            {showYears ? 'hide' : 'show'}
          </button>
        </div>
        <div className={clsx('overflow-x-auto', !showYears && 'hidden print:block')}>
          <table className="w-full text-xs">
            <thead>
              <tr className="bg-[var(--se-bg)]">
                <th rowSpan={2} className="text-left px-3 py-1.5 font-medium text-[var(--se-text-fnt)]">Year</th>
                <th rowSpan={2} className="px-2 py-1.5 font-medium text-[var(--se-text-fnt)] text-[10px]">Rain</th>
                {rows.map((r, i) => (
                  <th key={r.id} colSpan={4} className="px-3 py-1 font-medium text-center whitespace-nowrap"
                    style={{ color: COLORS[i % COLORS.length] }}>{r.name}</th>
                ))}
              </tr>
              <tr className="bg-[var(--se-bg)]">
                {rows.map(r => (
                  <Fragment key={r.id}>
                    <th className="px-2 py-1 font-normal text-[10px] text-[var(--se-text-fnt)]">irrig</th>
                    <th className="px-2 py-1 font-normal text-[10px] text-[var(--se-text-fnt)]">ET</th>
                    <th className="px-2 py-1 font-normal text-[10px] text-[var(--se-text-fnt)]">soil w.</th>
                    <th className="px-2 py-1 font-normal text-[10px] text-[var(--se-text-fnt)]">NO₃ lch</th>
                  </Fragment>
                ))}
              </tr>
            </thead>
            <tbody>
              {yearTable.years.map(yr => (
                <tr key={yr} className="border-t border-[var(--se-border-lt)]">
                  <td className="px-3 py-1 text-[var(--se-text-mut)]">{yr}</td>
                  <td className="px-2 py-1 text-right tabular-nums text-[var(--se-text-fnt)]">
                    {(yearTable.precip[yr] ?? 0).toFixed(0)}
                  </td>
                  {yearTable.perRun.map((m, i) => (
                    <Fragment key={i}>
                      <td className="px-2 py-1 text-right tabular-nums text-[var(--se-text-mut)]">{(m.irr[yr] ?? 0).toFixed(0)}</td>
                      <td className="px-2 py-1 text-right tabular-nums text-[var(--se-text-mut)]">{(m.et[yr] ?? 0).toFixed(0)}</td>
                      <td className="px-2 py-1 text-right tabular-nums text-[var(--se-text-mut)]">{(m.sw[yr] ?? 0).toFixed(0)}</td>
                      <td className="px-2 py-1 text-right tabular-nums text-[var(--se-text-mut)]">{(m.pn[yr] ?? 0).toFixed(2)}</td>
                    </Fragment>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* ---- canopy, efficiency and mass balance ---- */}
      <div className="grid gap-4 sm:grid-cols-2 px-4 pb-4 border-t border-[var(--se-border-lt)] pt-4">
        <div className="rounded-lg border border-[var(--se-border-lt)] p-3">
          <div className="text-[11px] font-semibold text-[var(--se-text-mut)] mb-2">Canopy &amp; efficiency</div>
          <table className="w-full text-[11px]">
            <tbody>
              {([
                ['Peak leaf area index', (d: ReturnType<typeof diagnose>) => d.laiPeak.toFixed(2)],
                ['ET / potential ET', d => d.etPet.toFixed(2)],
                ['N use efficiency', d => `${d.nue.toFixed(1)}%`],
                ['N leached per N applied', d => `${d.leachFrac.toFixed(0)}%`],
                ['N applied per fertilised yr', d => {
                  const t = (rows[diags.indexOf(d)]?.tl.totals || {}) as Record<string, number>;
                  return d.fertYears ? `${((t.fertn_kgha || 0) / d.fertYears).toFixed(0)} kg/ha` : '—';
                }],
                ['Irrigation events', d => d.irrEvents.toLocaleString()],
              ] as [string, (d: ReturnType<typeof diagnose>) => string][]).map(([lab, fn]) => (
                <tr key={lab} className="border-t border-[var(--se-border-lt)] first:border-0">
                  <td className="py-1 text-[var(--se-text-mut)]">{lab}</td>
                  {diags.map((d, i) => (
                    <td key={i} className="py-1 text-right tabular-nums text-[var(--se-text)]">{fn(d)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="rounded-lg border border-[var(--se-border-lt)] p-3">
          <div className="text-[11px] font-semibold text-[var(--se-text-mut)] mb-2">Mass balance <span className="text-[var(--se-text-fnt)]">(whole period)</span></div>
          <table className="w-full text-[11px]">
            <tbody>
              {([
                ['Water in (rain + irrigation)', d => `${d.waterIn.toFixed(0)} mm`],
                ['Water out (ET + drainage)', d => `${d.waterOut.toFixed(0)} mm`],
                ['Δ soil storage', d => `${d.swDelta >= 0 ? '+' : ''}${d.swDelta.toFixed(0)} mm`],
                ['N in (fertiliser + fixation)', d => `${d.nIn.toFixed(0)} kg/ha`],
                ['N out (uptake + losses)', d => `${d.nOut.toFixed(0)} kg/ha`],
                ['N to soil storage', d => `${(d.nIn - d.nOut) >= 0 ? '+' : ''}${(d.nIn - d.nOut).toFixed(0)} kg/ha`],
              ] as [string, (d: ReturnType<typeof diagnose>) => string][]).map(([lab, fn]) => (
                <tr key={lab} className="border-t border-[var(--se-border-lt)] first:border-0">
                  <td className="py-1 text-[var(--se-text-mut)]">{lab}</td>
                  {diags.map((d, i) => (
                    <td key={i} className="py-1 text-right tabular-nums text-[var(--se-text)]">{fn(d)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <p className="px-4 pb-3 text-[11px] text-[var(--se-text-fnt)]">
        Best value per row is bold (lower is better for N leached, irrigation, percolation).
        Totals are summed over the whole run — divide by the years shown to get annual rates.
        Directional single-field estimates — compare scenarios, not absolutes.
      </p>
    </div>
  );
}
