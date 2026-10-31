import { useState, useEffect } from 'react';
import { Link } from 'react-router-dom';
import { farms, scenarios, simulate, confidenceLabel, type Farm, type WaterBalance, type NutrientBalance, type NitrateBalance, type NitrateMonthlyPoint, type DailyPoint, type SimResult, type FieldConfidence, type OutputConfidence } from '@/lib/api';
import { BarChart, Bar, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend, ReferenceLine, Cell } from 'recharts';
import { Play, Loader2, Droplets, Sprout, Wheat, FlaskConical } from 'lucide-react';
import clsx from 'clsx';
import ErrorBanner from '@/components/ErrorBanner';
import ConfidenceBadge from '@/components/ConfidenceBadge';
import { CHART, tooltipStyle, axisTick } from '@/lib/chartTheme';

function outputConf(fc: FieldConfidence | null, id: string): OutputConfidence | undefined {
  const o = fc?.outputs?.find(x => x.id === id);
  return o ? { level: o.confidence, label: confidenceLabel(o.confidence), note: o.basis } : undefined;
}

type Scenario = 'irrigation' | 'fertilizer' | 'nitrate' | 'yield';

const TABS: { id: Scenario; label: string; icon: typeof Droplets }[] = [
  { id: 'irrigation', label: 'Irrigation', icon: Droplets },
  { id: 'fertilizer', label: 'Fertilizer', icon: Sprout },
  { id: 'nitrate', label: 'Water Quality', icon: FlaskConical },
  { id: 'yield', label: 'Yield', icon: Wheat },
];

export default function Visualizations() {
  const [farmsList, setFarmsList] = useState<Farm[]>([]);
  const [selectedFarm, setSelectedFarm] = useState('');
  const [scenario, setScenario] = useState<Scenario>('irrigation');
  const [loading, setLoading] = useState(false);
  const [advice, setAdvice] = useState('');
  const [wb, setWb] = useState<WaterBalance | null>(null);
  const [nb, setNb] = useState<NutrientBalance | null>(null);
  const [nitrate, setNitrate] = useState<NitrateBalance | null>(null);
  const [nitrateMonthly, setNitrateMonthly] = useState<NitrateMonthlyPoint[]>([]);
  const [fieldConf, setFieldConf] = useState<FieldConfidence | null>(null);
  const [daily, setDaily] = useState<DailyPoint[]>([]);
  const [yieldKgha, setYieldKgha] = useState<number | null>(null);
  const [history, setHistory] = useState<SimResult[]>([]);
  const [error, setError] = useState('');

  useEffect(() => { farms.list().then(setFarmsList).catch(() => {}); }, []);

  useEffect(() => {
    if (!selectedFarm) return;
    simulate.listForFarm(selectedFarm).then(setHistory).catch(() => {});
    farms.insights(selectedFarm).then(ins => {
      if (ins.confidence) setFieldConf(ins.confidence);
      if (ins.run_output?.water_balance) setWb(ins.run_output.water_balance);
      if (ins.run_output?.nutrient_balance) setNb(ins.run_output.nutrient_balance);
      if (ins.run_output?.nitrate) setNitrate(ins.run_output.nitrate);
      if (ins.run_output?.nitrate_monthly) setNitrateMonthly(ins.run_output.nitrate_monthly);
      if (ins.run_output?.daily_series) setDaily(ins.run_output.daily_series);
      if (ins.run_output?.yield_kgha != null) setYieldKgha(ins.run_output.yield_kgha);
      const key = scenario as keyof typeof ins;
      if (ins[key] && typeof ins[key] === 'object' && 'advice' in (ins[key] as object)) {
        setAdvice((ins[key] as { advice?: string }).advice || '');
      }
    }).catch(() => {});
  }, [selectedFarm]);

  const runScenario = async () => {
    if (!selectedFarm) return;
    setLoading(true);
    setError('');
    try {
      const res = await scenarios.run(selectedFarm, scenario);
      setAdvice(res.advice);
      setWb(res.charts.water_balance || null);
      setNb(res.charts.nutrient_balance || null);
      setNitrate(res.charts.nitrate || null);
      setNitrateMonthly(res.charts.nitrate_monthly || []);
      setDaily(res.charts.daily_series || []);
      setYieldKgha(res.charts.yield_kgha ?? null);
      simulate.listForFarm(selectedFarm).then(setHistory).catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Run failed');
    } finally {
      setLoading(false);
    }
  };

  // Each category gets its own fixed hue (never one color for many categories).
  const wbData = wb ? [
    { label: 'Precip', value: wb.precip_mm, fill: CHART.cat[0] },
    { label: 'ET', value: wb.et_mm, fill: CHART.cat[1] },
    { label: 'Runoff', value: wb.runoff_mm, fill: CHART.cat[4] },
    { label: 'Deep Perc', value: wb.deep_perc_mm, fill: CHART.cat[3] },
    { label: 'Soil Moist', value: wb.soil_moisture_mm, fill: CHART.cat[2] },
  ] : [];

  const nbData = nb ? [
    { label: 'Nitrogen', value: nb.nitrogen_kgha, fill: CHART.cat[1] },
    { label: 'Phosphorus', value: nb.phosphorus_kgha, fill: CHART.cat[2] },
  ] : [];

  const nitrateLimit = nitrate?.limit_mgL ?? 10;
  const lossData = nitrate ? [
    { label: 'Leached to groundwater', value: nitrate.leached_to_groundwater_kgha, fill: CHART.cat[3] },
    { label: 'Surface runoff', value: nitrate.surface_runoff_kgha, fill: CHART.cat[4] },
    { label: 'Lateral flow', value: nitrate.lateral_flow_kgha, fill: CHART.cat[0] },
    { label: 'Tile drain', value: nitrate.tile_drain_kgha, fill: CHART.cat[1] },
  ].filter(d => (d.value ?? 0) > 0) : [];
  const hasMonthlyConc = nitrateMonthly.some(m => m.no3_mgL != null);
  const streamConc = nitrate?.stream?.mean_no3_mgL ?? null;

  return (
    <div className="p-6 flex gap-6">
      <div className="flex-1 space-y-6 min-w-0">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-bold text-white">Results</h1>
          <select
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm"
            value={selectedFarm}
            onChange={e => setSelectedFarm(e.target.value)}
          >
            <option value="">Select farm...</option>
            {farmsList.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
          </select>
        </div>

        {!selectedFarm && (
          <div className="border border-white/10 rounded-xl p-8 text-center">
            <p className="text-white/40 text-sm mb-3">Select a farm or complete setup first.</p>
            <Link to="/setup" className="text-moss-400 text-sm hover:text-moss-300">Set up your farm</Link>
          </div>
        )}

        {selectedFarm && (
          <>
            <div className="flex gap-2 flex-wrap">
              {TABS.map(({ id, label, icon: Icon }) => (
                <button
                  key={id}
                  onClick={() => setScenario(id)}
                  className={clsx(
                    'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-colors',
                    scenario === id ? 'bg-moss-600/30 text-moss-400 border border-moss-500/40' : 'bg-white/5 text-white/50 border border-white/10 hover:text-white/80'
                  )}
                >
                  <Icon className="w-4 h-4" /> {label}
                </button>
              ))}
              <button
                onClick={runScenario}
                disabled={loading}
                className="flex items-center gap-2 bg-moss-600 hover:bg-moss-700 disabled:opacity-50 rounded-lg px-4 py-2 text-sm font-medium ml-auto"
              >
                {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                Run analysis
              </button>
            </div>

            {error && (
              <ErrorBanner variant="error" title="Simulation failed" message={error} />
            )}

            {advice && (
              <div className="border border-moss-500/30 bg-moss-500/5 rounded-xl p-4">
                <p className="text-xs text-white/40 mb-1">Recommendation</p>
                <p className="text-sm text-white/90">{advice}</p>
              </div>
            )}

            {scenario === 'yield' && yieldKgha != null && (
              <div className="border border-white/10 rounded-xl p-5">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <h3 className="text-sm font-semibold text-white/80">Estimated Yield</h3>
                  <ConfidenceBadge confidence={outputConf(fieldConf, 'yield')} size="xs" />
                </div>
                <p className="text-3xl font-bold text-moss-400">{(yieldKgha / 1000).toFixed(2)} <span className="text-lg font-normal text-white/50">t/ha</span></p>
                <p className="text-xs text-white/40 mt-1">{yieldKgha.toFixed(0)} kg/ha</p>
              </div>
            )}

            {scenario === 'nitrate' && (
              <>
                {nitrate && (
                  <div className="grid grid-cols-2 lg:grid-cols-3 gap-3">
                    <StatCard
                      label="Est. stream nitrate"
                      value={streamConc != null ? streamConc.toFixed(1) : '—'}
                      unit="mg/L"
                      note={`limit ${nitrateLimit.toFixed(0)} mg/L`}
                      danger={streamConc != null && streamConc >= nitrateLimit}
                      confidence={outputConf(fieldConf, 'nitrate')}
                    />
                    <StatCard
                      label="N leached to groundwater"
                      value={nitrate.leached_to_groundwater_kgha.toFixed(1)}
                      unit="kg/ha/yr"
                    />
                    <StatCard
                      label="Total N loss"
                      value={nitrate.total_no3_loss_kgha.toFixed(1)}
                      unit="kg/ha/yr"
                    />
                  </div>
                )}

                <div className="border border-white/10 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-white/80 mb-1">Stream Nitrate Through the Year</h3>
                  <p className="text-xs text-white/40 mb-4">
                    Estimated nitrate-N in the creek by month. The dashed line is the {nitrateLimit.toFixed(0)} mg/L drinking-water limit. Peaks in winter, when low flow is mostly groundwater — the pattern found on Bazile Creek (Richards et al., 2021).
                  </p>
                  {hasMonthlyConc ? (
                    <ResponsiveContainer width="100%" height={260}>
                      <LineChart data={nitrateMonthly} margin={{ top: 8, right: 12, bottom: 0, left: 0 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
                        <XAxis dataKey="month_label" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART.axis }} />
                        <YAxis tick={axisTick} tickLine={false} axisLine={false} width={38} label={{ value: 'mg/L', angle: -90, position: 'insideLeft', fill: CHART.muted, fontSize: 11 }} />
                        <Tooltip contentStyle={tooltipStyle} cursor={{ stroke: CHART.axis }} />
                        <ReferenceLine y={nitrateLimit} stroke={CHART.status.critical} strokeDasharray="6 4" label={{ value: `${nitrateLimit.toFixed(0)} mg/L drinking limit`, fill: CHART.status.critical, fontSize: 11, position: 'insideTopRight' }} />
                        <Line type="monotone" dataKey="no3_mgL" name="Stream nitrate-N (mg/L)" stroke={CHART.series1} strokeWidth={2} dot={{ r: 3, fill: CHART.series1 }} activeDot={{ r: 5 }} connectNulls />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-[260px] flex items-center justify-center text-white/30 text-sm text-center px-6">
                      Run a Water Quality analysis over a multi-month period to see the seasonal stream-nitrate curve.
                    </div>
                  )}
                </div>

                <div className="border border-white/10 rounded-xl p-5">
                  <h3 className="text-sm font-semibold text-white/80 mb-1">Where Nitrogen Leaves the Field</h3>
                  <p className="text-xs text-white/40 mb-4">
                    Annual nitrate-N loss by pathway (kg/ha). Leaching to groundwater is what later resurfaces in the stream.
                  </p>
                  {lossData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={220}>
                      <BarChart data={lossData} layout="vertical" margin={{ left: 40, right: 16 }}>
                        <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} horizontal={false} />
                        <XAxis type="number" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART.axis }} label={{ value: 'kg-N/ha/yr', position: 'insideBottom', offset: -2, fill: CHART.muted, fontSize: 11 }} />
                        <YAxis type="category" dataKey="label" width={140} tick={{ fill: CHART.inkSecondary, fontSize: 11 }} tickLine={false} axisLine={false} />
                        <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                        <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                          {lossData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                        </Bar>
                      </BarChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-[220px] flex items-center justify-center text-white/30 text-sm">
                      No measurable nitrate loss in the latest run.
                    </div>
                  )}
                </div>
              </>
            )}

            {scenario !== 'nitrate' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <div className="border border-white/10 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-white/80 mb-4">Water Balance (mm)</h3>
                {wbData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={wbData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
                      <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART.axis }} />
                      <YAxis tick={axisTick} tickLine={false} axisLine={false} width={38} />
                      <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                      <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                        {wbData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-[220px] flex items-center justify-center text-white/30 text-sm">Run an analysis to see water balance</div>
                )}
              </div>

              <div className="border border-white/10 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-white/80 mb-4">Nutrient Balance (kg/ha)</h3>
                {nbData.length > 0 ? (
                  <ResponsiveContainer width="100%" height={220}>
                    <BarChart data={nbData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke={CHART.grid} vertical={false} />
                      <XAxis dataKey="label" tick={axisTick} tickLine={false} axisLine={{ stroke: CHART.axis }} />
                      <YAxis tick={axisTick} tickLine={false} axisLine={false} width={38} />
                      <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
                      <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                        {nbData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="h-[220px] flex items-center justify-center text-white/30 text-sm">Run an analysis to see nutrients</div>
                )}
              </div>
            </div>
            )}

            {scenario !== 'nitrate' && daily.length > 0 && (
              <div className="border border-white/10 rounded-xl p-5">
                <h3 className="text-sm font-semibold text-white/80 mb-4">Soil Moisture Over Time</h3>
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
              </div>
            )}
          </>
        )}
      </div>

      {selectedFarm && (
        <aside className="w-56 shrink-0 hidden lg:block">
          <h3 className="text-xs font-semibold text-white/40 uppercase mb-3">Run History</h3>
          <ul className="space-y-2">
            {history.length === 0 && <li className="text-xs text-white/30">No runs yet</li>}
            {history.map(h => (
              <li key={h.run_id || h.simulation_id} className="text-xs p-2 rounded-lg bg-white/5 border border-white/10">
                <span className={clsx('inline-block w-2 h-2 rounded-full mr-1.5', h.status === 'completed' ? 'bg-moss-400' : h.status === 'failed' ? 'bg-red-400' : 'bg-earth-400')} />
                {h.status}
                {h.error && <p className="text-red-400/80 mt-1 line-clamp-2">{h.error}</p>}
                <p className="text-white/30 mt-0.5 truncate">{h.created_at?.slice(0, 10)}</p>
              </li>
            ))}
          </ul>
          <Link to={`/data?farm=${selectedFarm}`} className="text-xs text-moss-400 hover:underline block mt-4">
            View data files & run outputs →
          </Link>
        </aside>
      )}
    </div>
  );
}

function StatCard({ label, value, unit, note, danger, confidence }: { label: string; value: string; unit: string; note?: string; danger?: boolean; confidence?: OutputConfidence }) {
  return (
    <div className={clsx('rounded-xl border p-4', danger ? 'border-red-500/40 bg-red-500/5' : 'border-white/10 bg-white/5')}>
      <p className="text-[11px] uppercase tracking-wide text-white/45">{label}</p>
      <p className={clsx('text-2xl font-bold mt-1 tabular-nums', danger ? 'text-red-400' : 'text-white')}>
        {value} <span className="text-sm font-normal text-white/40">{unit}</span>
      </p>
      {note && <p className="text-[11px] text-white/40 mt-0.5">{note}</p>}
      {confidence && <div className="mt-2"><ConfidenceBadge confidence={confidence} size="xs" /></div>}
    </div>
  );
}
