import { useEffect, useRef, useState } from 'react';
import {
  Play, Plus, Trash2, Loader2, AlertTriangle, Info, RefreshCw,
  BarChart3, Printer, Sprout, FlaskConical, Table2, Sliders,
} from 'lucide-react';
import clsx from 'clsx';
import { swatModel, type SwatParam } from '@/lib/api';
import CropSettings from '@/components/CropSettings';

type TabId = 'run' | 'parameters' | 'print' | 'crop' | 'calibration';
type ChangeType = SwatParam['change_type'];

interface ParamRow {
  id: string;
  name: string;
  change_type: ChangeType;
  value: number;
}

type PrintFreq = 'daily' | 'monthly' | 'yearly' | 'avann';
type PrintObject = 'hru_wb' | 'hru_nb' | 'hru_ls' | 'channel_sd' | 'crop_yld' | 'basin_wb';
type PrintState = Record<PrintObject, Record<PrintFreq, boolean>>;

interface RunStatusState {
  run_id: string;
  status: string;
  progress?: number;
  output_summary?: Record<string, unknown>;
  error?: string;
}

const SE_VARS = {
  '--se-bg': '#FAFAFA',
  '--se-rail': '#F4F5F7',
  '--se-card': '#FFFFFF',
  '--se-border': '#E2E5EA',
  '--se-border-lt': '#ECEFF1',
  '--se-text': '#1A2230',
  '--se-text-mut': '#607D8B',
  '--se-text-fnt': '#90A4AE',
  '--se-accent': '#0068C1',
  '--se-accent-h': '#00579E',
  '--se-accent-sf': '#E4F0FA',
  '--se-accent-bd': '#B9D8F1',
  '--se-error': '#B00020',
  '--se-error-sf': '#FCE8EA',
  '--se-ok': '#2E7D32',
} as React.CSSProperties;

const TABS: { id: TabId; label: string; icon: typeof Sliders }[] = [
  { id: 'run', label: 'Run', icon: Play },
  { id: 'parameters', label: 'Parameters', icon: Sliders },
  { id: 'print', label: 'Print output', icon: Printer },
  { id: 'crop', label: 'Crop', icon: Sprout },
  { id: 'calibration', label: 'Calibration', icon: FlaskConical },
];

const CHANGE_TYPES: ChangeType[] = ['pctchg', 'absval', 'relchg'];

const PRINT_OBJECTS: { id: PrintObject; label: string }[] = [
  { id: 'hru_wb', label: 'HRU water balance' },
  { id: 'hru_nb', label: 'HRU nutrient balance' },
  { id: 'hru_ls', label: 'HRU losses' },
  { id: 'channel_sd', label: 'Channel (sediment)' },
  { id: 'crop_yld', label: 'Crop yield' },
  { id: 'basin_wb', label: 'Basin water balance' },
];

const PRINT_FREQS: PrintFreq[] = ['daily', 'monthly', 'yearly', 'avann'];

let rowSeq = 0;
const newRow = (name: string, change_type: ChangeType, value: number): ParamRow => ({
  id: `row-${rowSeq++}`,
  name,
  change_type,
  value,
});

function emptyPrintState(): PrintState {
  const base = {} as PrintState;
  for (const o of PRINT_OBJECTS) {
    base[o.id] = { daily: false, monthly: false, yearly: false, avann: false };
  }
  return base;
}

function numberOrNull(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

export default function RunPanel({ farmId }: { farmId: string }) {
  const [tab, setTab] = useState<TabId>('run');
  const [error, setError] = useState('');

  // Run controls
  const [beginDate, setBeginDate] = useState('01-Jan-2020');
  const [endDate, setEndDate] = useState('31-Dec-2020');
  const [warmupYears, setWarmupYears] = useState(2);
  const [scenario, setScenario] = useState('baseline');
  const [running, setRunning] = useState(false);
  const [runStatus, setRunStatus] = useState<RunStatusState | null>(null);

  // Parameters
  const [rows, setRows] = useState<ParamRow[]>(() => [
    newRow('cn2', 'pctchg', 0),
    newRow('esco', 'absval', 0.5),
  ]);

  // Print output
  const [printState, setPrintState] = useState<PrintState>(() => {
    const s = emptyPrintState();
    s.channel_sd.daily = true;
    return s;
  });

  // Calibration
  const [simFile, setSimFile] = useState('channel_sd_mon.txt');
  const [obsFile, setObsFile] = useState('');
  const [simCol, setSimCol] = useState('flo_out');
  const [obsCol, setObsCol] = useState('discharge');
  const [indicators, setIndicators] = useState('NSE,PBIAS,KGE,R2');
  const [metricsLoading, setMetricsLoading] = useState(false);
  const [metricsError, setMetricsError] = useState('');
  const [metricsResult, setMetricsResult] = useState<Record<string, unknown> | null>(null);

  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = () => {
    if (pollRef.current) {
      clearInterval(pollRef.current);
      pollRef.current = null;
    }
  };

  // Clear run/metrics state and any active poll when the field changes.
  useEffect(() => {
    stopPolling();
    setRunStatus(null);
    setRunning(false);
    setMetricsResult(null);
    setMetricsError('');
    setError('');
    return stopPolling;
  }, [farmId]);

  const buildPrintControl = (): Record<string, Record<string, boolean>> => {
    const out: Record<string, Record<string, boolean>> = {};
    for (const o of PRINT_OBJECTS) {
      const freqs = printState[o.id];
      const active: Record<string, boolean> = {};
      for (const f of PRINT_FREQS) {
        if (freqs[f]) active[f] = true;
      }
      if (Object.keys(active).length) out[o.id] = active;
    }
    return out;
  };

  const runModel = async () => {
    if (!farmId) return;
    stopPolling();
    setError('');
    setRunning(true);
    setRunStatus(null);
    try {
      const parameters: SwatParam[] = rows
        .filter(r => r.name.trim())
        .map(r => ({ name: r.name.trim(), change_type: r.change_type, value: r.value }));
      const res = await swatModel.run(farmId, {
        begin_date: beginDate,
        end_date: endDate,
        warmup_years: warmupYears,
        parameters,
        print_prt_control: buildPrintControl(),
        scenario: scenario || 'baseline',
      });
      setRunStatus({ run_id: res.run_id, status: res.status });
      pollRef.current = setInterval(async () => {
        try {
          const s = await swatModel.runStatus(res.run_id);
          setRunStatus({
            run_id: s.run_id,
            status: s.status,
            progress: s.progress,
            output_summary: s.output_summary,
            error: s.error,
          });
          if (s.status === 'completed' || s.status === 'failed' || s.status === 'cancelled') {
            stopPolling();
            setRunning(false);
          }
        } catch (e) {
          stopPolling();
          setRunning(false);
          setError(e instanceof Error ? e.message : 'Lost contact with the run.');
        }
      }, 2000);
    } catch (e) {
      setRunning(false);
      setError(e instanceof Error ? e.message : 'Could not start the run.');
    }
  };

  const computeMetrics = async () => {
    if (!farmId) return;
    setMetricsError('');
    setMetricsLoading(true);
    setMetricsResult(null);
    try {
      const inds = indicators
        .split(',')
        .map(s => s.trim())
        .filter(Boolean);
      const res = await swatModel.metrics({
        farm_id: farmId,
        run_id: runStatus?.run_id,
        sim_file: simFile,
        obs_file: obsFile,
        indicators: inds,
        sim_col: simCol,
        obs_col: obsCol,
      });
      setMetricsResult(res.indicators);
    } catch (e) {
      setMetricsError(e instanceof Error ? e.message : 'Could not compute metrics.');
    } finally {
      setMetricsLoading(false);
    }
  };

  const progress = runStatus?.progress ?? (runStatus?.status === 'completed' ? 100 : 0);
  const summary = runStatus?.output_summary;
  const waterBalance =
    summary && typeof summary.water_balance === 'object' && summary.water_balance
      ? (summary.water_balance as Record<string, unknown>)
      : null;
  const nitrate =
    summary && typeof summary.nitrate === 'object' && summary.nitrate
      ? (summary.nitrate as Record<string, unknown>)
      : null;
  const yieldKgha = summary ? numberOrNull(summary.yield_kgha) : null;

  const inputCls =
    'bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm text-[var(--se-text)] outline-none focus:border-[var(--se-accent)]';
  const labelCls = 'block text-xs font-medium text-[var(--se-text-mut)]';
  const cardCls = 'bg-[var(--se-card)] border border-[var(--se-border)] rounded-lg';
  const primaryBtn =
    'flex items-center gap-2 bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40 rounded-lg px-5 py-2.5 text-sm font-medium transition-colors';

  const statusColor = (status: string): string => {
    if (status === 'completed') return 'text-[var(--se-ok)] border-[var(--se-ok)] bg-[var(--se-card)]';
    if (status === 'failed' || status === 'cancelled')
      return 'text-[var(--se-error)] border-[var(--se-error)] bg-[var(--se-error-sf)]';
    return 'text-[var(--se-accent)] border-[var(--se-accent-bd)] bg-[var(--se-accent-sf)]';
  };

  return (
    <div
      style={SE_VARS}
      className="bg-[var(--se-bg)] text-[var(--se-text)] min-h-full h-full overflow-y-auto"
    >
      <div className="p-6 max-w-5xl mx-auto space-y-5">
        <div className="flex items-center gap-3">
          <Play className="w-6 h-6 text-[var(--se-accent)]" />
          <div>
            <h1 className="text-2xl font-bold text-[var(--se-text)]">Run SWAT+</h1>
            <p className="text-sm text-[var(--se-text-mut)] mt-0.5">
              Configure the run, override parameters, and compute goodness-of-fit.
            </p>
          </div>
        </div>

        {/* Honesty note */}
        <div className="flex items-start gap-2 rounded-lg border border-[var(--se-accent-bd)] bg-[var(--se-accent-sf)] px-3 py-2.5 text-xs text-[var(--se-accent-h)]">
          <Info className="w-4 h-4 shrink-0 mt-0.5" />
          <span>Parameter changes apply to this run only — not written to model files.</span>
        </div>

        {error && (
          <div className="flex items-start gap-2 rounded-lg border border-[var(--se-error)] bg-[var(--se-error-sf)] px-3 py-2 text-xs text-[var(--se-error)]">
            <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
            <span>{error}</span>
          </div>
        )}

        {/* Secondary tab bar */}
        <div className="flex flex-wrap gap-1 border-b border-[var(--se-border)]">
          {TABS.map(t => {
            const Icon = t.icon;
            const active = tab === t.id;
            return (
              <button
                key={t.id}
                onClick={() => setTab(t.id)}
                className={clsx(
                  'flex items-center gap-1.5 px-3 py-2 text-sm rounded-t-lg border-b-2 -mb-px transition-colors',
                  active
                    ? 'border-[var(--se-accent)] text-[var(--se-accent)] font-medium'
                    : 'border-transparent text-[var(--se-text-mut)] hover:text-[var(--se-text)]',
                )}
              >
                <Icon className="w-4 h-4" /> {t.label}
              </button>
            );
          })}
        </div>

        <div className="pt-1">
          {/* ---- Run ---- */}
          {tab === 'run' && (
            <div className="space-y-4">
              <div className={clsx(cardCls, 'p-4 space-y-3')}>
                <h2 className="text-sm font-semibold text-[var(--se-text)]">Simulation period</h2>
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className={labelCls}>
                    Begin date
                    <input
                      type="text"
                      className={clsx('mt-1 w-full', inputCls)}
                      value={beginDate}
                      onChange={e => setBeginDate(e.target.value)}
                      placeholder="01-Jan-2020"
                    />
                  </label>
                  <label className={labelCls}>
                    End date
                    <input
                      type="text"
                      className={clsx('mt-1 w-full', inputCls)}
                      value={endDate}
                      onChange={e => setEndDate(e.target.value)}
                      placeholder="31-Dec-2020"
                    />
                  </label>
                  <label className={labelCls}>
                    Warm-up years
                    <input
                      type="number"
                      min={0}
                      className={clsx('mt-1 w-full', inputCls)}
                      value={warmupYears}
                      onChange={e => setWarmupYears(Math.max(0, Number(e.target.value) || 0))}
                    />
                  </label>
                  <label className={labelCls}>
                    Scenario
                    <input
                      type="text"
                      className={clsx('mt-1 w-full', inputCls)}
                      value={scenario}
                      onChange={e => setScenario(e.target.value)}
                      placeholder="baseline"
                    />
                  </label>
                </div>
              </div>

              <button onClick={runModel} disabled={running || !farmId} className={primaryBtn}>
                {running ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
                {running ? 'Running…' : 'Run SWAT+'}
              </button>

              {runStatus && (
                <div className={clsx(cardCls, 'p-4 space-y-3')}>
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-[var(--se-text-mut)]">
                      Run{' '}
                      <span className="text-[var(--se-text)] font-mono">{runStatus.run_id}</span>
                    </span>
                    <span
                      className={clsx(
                        'px-2 py-0.5 rounded-full border text-[10px] uppercase tracking-wide',
                        statusColor(runStatus.status),
                      )}
                    >
                      {runStatus.status}
                    </span>
                  </div>

                  <div className="h-2 rounded-full bg-[var(--se-border-lt)] overflow-hidden">
                    <div
                      className="h-full bg-[var(--se-accent)] transition-all"
                      style={{ width: `${Math.min(100, Math.max(0, progress))}%` }}
                    />
                  </div>

                  {runStatus.error && <p className="text-xs text-[var(--se-error)]">{runStatus.error}</p>}

                  {runStatus.status === 'completed' && (
                    <div className="grid gap-3 sm:grid-cols-3 pt-1">
                      <div className={clsx(cardCls, 'p-3')}>
                        <div className="flex items-center gap-1.5 text-[11px] text-[var(--se-text-mut)] mb-1">
                          <BarChart3 className="w-3.5 h-3.5" /> Water balance
                        </div>
                        {waterBalance ? (
                          <ul className="text-xs text-[var(--se-text)] space-y-0.5">
                            {Object.entries(waterBalance).slice(0, 5).map(([k, v]) => (
                              <li key={k} className="flex justify-between gap-2">
                                <span className="text-[var(--se-text-mut)]">{k}</span>
                                <span className="font-mono">
                                  {numberOrNull(v)?.toFixed(1) ?? String(v)}
                                </span>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-xs text-[var(--se-text-fnt)]">—</p>
                        )}
                      </div>
                      <div className={clsx(cardCls, 'p-3')}>
                        <div className="text-[11px] text-[var(--se-text-mut)] mb-1">Yield</div>
                        <p className="text-lg font-semibold text-[var(--se-text)]">
                          {yieldKgha != null ? `${yieldKgha.toFixed(0)}` : '—'}
                          {yieldKgha != null && (
                            <span className="text-xs text-[var(--se-text-mut)]"> kg/ha</span>
                          )}
                        </p>
                      </div>
                      <div className={clsx(cardCls, 'p-3')}>
                        <div className="text-[11px] text-[var(--se-text-mut)] mb-1">Nitrate</div>
                        {nitrate ? (
                          <ul className="text-xs text-[var(--se-text)] space-y-0.5">
                            {Object.entries(nitrate).slice(0, 5).map(([k, v]) => (
                              <li key={k} className="flex justify-between gap-2">
                                <span className="text-[var(--se-text-mut)]">{k}</span>
                                <span className="font-mono">
                                  {numberOrNull(v)?.toFixed(2) ?? String(v)}
                                </span>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <p className="text-xs text-[var(--se-text-fnt)]">—</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}

          {/* ---- Parameters ---- */}
          {tab === 'parameters' && (
            <div className="space-y-3">
              <div className={clsx(cardCls, 'overflow-hidden')}>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-[var(--se-rail)] text-left text-[11px] uppercase tracking-wide text-[var(--se-text-mut)] font-semibold">
                      <th className="px-3 py-2">Parameter</th>
                      <th className="px-3 py-2 w-40">Change type</th>
                      <th className="px-3 py-2 w-32">Value</th>
                      <th className="px-3 py-2 w-10" />
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(r => (
                      <tr key={r.id} className="border-t border-[var(--se-border-lt)]">
                        <td className="px-3 py-2">
                          <input
                            type="text"
                            className={clsx('w-full', inputCls, 'px-2.5 py-1.5')}
                            value={r.name}
                            placeholder="e.g. cn2"
                            onChange={e =>
                              setRows(rs => rs.map(x => (x.id === r.id ? { ...x, name: e.target.value } : x)))
                            }
                          />
                        </td>
                        <td className="px-3 py-2">
                          <select
                            className={clsx('w-full', inputCls, 'px-2.5 py-1.5')}
                            value={r.change_type}
                            onChange={e =>
                              setRows(rs =>
                                rs.map(x =>
                                  x.id === r.id ? { ...x, change_type: e.target.value as ChangeType } : x,
                                ),
                              )
                            }
                          >
                            {CHANGE_TYPES.map(c => (
                              <option key={c} value={c}>{c}</option>
                            ))}
                          </select>
                        </td>
                        <td className="px-3 py-2">
                          <input
                            type="number"
                            step="any"
                            className={clsx('w-full', inputCls, 'px-2.5 py-1.5')}
                            value={r.value}
                            onChange={e =>
                              setRows(rs =>
                                rs.map(x => (x.id === r.id ? { ...x, value: Number(e.target.value) || 0 } : x)),
                              )
                            }
                          />
                        </td>
                        <td className="px-3 py-2 text-right">
                          <button
                            onClick={() => setRows(rs => rs.filter(x => x.id !== r.id))}
                            className="text-[var(--se-text-fnt)] hover:text-[var(--se-error)]"
                            aria-label="Remove row"
                          >
                            <Trash2 className="w-4 h-4" />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {!rows.length && (
                      <tr className="border-t border-[var(--se-border-lt)]">
                        <td colSpan={4} className="px-3 py-4 text-center text-xs text-[var(--se-text-fnt)]">
                          No parameter overrides — the model runs with project defaults.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
              <button
                onClick={() => setRows(rs => [...rs, newRow('', 'pctchg', 0)])}
                className="flex items-center gap-1.5 text-xs px-3 py-2 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:text-[var(--se-accent)] hover:border-[var(--se-accent-bd)]"
              >
                <Plus className="w-3.5 h-3.5" /> Add parameter
              </button>
            </div>
          )}

          {/* ---- Print output ---- */}
          {tab === 'print' && (
            <div className="space-y-3">
              <p className="text-xs text-[var(--se-text-mut)]">
                Choose which output objects the engine writes, and at what frequency. These build the
                <span className="font-mono text-[var(--se-text)]"> print.prt </span> control for this run.
              </p>
              <div className={clsx(cardCls, 'overflow-x-auto')}>
                <table className="w-full text-sm">
                  <thead>
                    <tr className="bg-[var(--se-rail)] text-left text-[11px] uppercase tracking-wide text-[var(--se-text-mut)] font-semibold">
                      <th className="px-3 py-2">Output object</th>
                      {PRINT_FREQS.map(f => {
                        const allOn = PRINT_OBJECTS.every(o => printState[o.id][f]);
                        return (
                          <th key={f} className="px-3 py-2 text-center w-24">
                            <div className="flex flex-col items-center gap-1">
                              <span className="capitalize">{f}</span>
                              <input
                                type="checkbox"
                                aria-label={`Select all ${f}`}
                                className="accent-[var(--se-accent)] w-3.5 h-3.5"
                                checked={allOn}
                                onChange={e =>
                                  setPrintState(s => {
                                    const next = { ...s };
                                    for (const o of PRINT_OBJECTS) {
                                      next[o.id] = { ...next[o.id], [f]: e.target.checked };
                                    }
                                    return next;
                                  })
                                }
                              />
                            </div>
                          </th>
                        );
                      })}
                    </tr>
                  </thead>
                  <tbody>
                    {PRINT_OBJECTS.map(o => (
                      <tr key={o.id} className="border-t border-[var(--se-border-lt)]">
                        <td className="px-3 py-2 text-[var(--se-text)]">
                          {o.label}
                          <span className="block text-[10px] font-mono text-[var(--se-text-fnt)]">{o.id}</span>
                        </td>
                        {PRINT_FREQS.map(f => (
                          <td key={f} className="px-3 py-2 text-center">
                            <input
                              type="checkbox"
                              className="accent-[var(--se-accent)] w-4 h-4"
                              checked={printState[o.id][f]}
                              onChange={e =>
                                setPrintState(s => ({
                                  ...s,
                                  [o.id]: { ...s[o.id], [f]: e.target.checked },
                                }))
                              }
                            />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* ---- Crop ---- */}
          {tab === 'crop' && <CropSettings farmId={farmId} />}

          {/* ---- Calibration ---- */}
          {tab === 'calibration' && (
            <div className="space-y-4">
              <p className="text-xs text-[var(--se-text-mut)]">
                Compare simulated output against an observed record and compute goodness-of-fit indicators.
              </p>
              <div className={clsx(cardCls, 'p-4 grid gap-3 sm:grid-cols-2')}>
                <label className={labelCls}>
                  Simulated file
                  <input
                    type="text"
                    className={clsx('mt-1 w-full', inputCls)}
                    value={simFile}
                    onChange={e => setSimFile(e.target.value)}
                  />
                </label>
                <label className={labelCls}>
                  Observed file (path)
                  <input
                    type="text"
                    className={clsx('mt-1 w-full', inputCls)}
                    value={obsFile}
                    onChange={e => setObsFile(e.target.value)}
                    placeholder="C:\data\observed_discharge.csv"
                  />
                </label>
                <label className={labelCls}>
                  Simulated column
                  <input
                    type="text"
                    className={clsx('mt-1 w-full', inputCls)}
                    value={simCol}
                    onChange={e => setSimCol(e.target.value)}
                  />
                </label>
                <label className={labelCls}>
                  Observed column
                  <input
                    type="text"
                    className={clsx('mt-1 w-full', inputCls)}
                    value={obsCol}
                    onChange={e => setObsCol(e.target.value)}
                  />
                </label>
                <label className={clsx(labelCls, 'sm:col-span-2')}>
                  Indicators (comma-separated)
                  <input
                    type="text"
                    className={clsx('mt-1 w-full', inputCls)}
                    value={indicators}
                    onChange={e => setIndicators(e.target.value)}
                    placeholder="NSE,PBIAS,KGE,R2"
                  />
                </label>
              </div>

              <button
                onClick={computeMetrics}
                disabled={metricsLoading || !obsFile.trim()}
                className={primaryBtn}
              >
                {metricsLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <RefreshCw className="w-4 h-4" />
                )}
                Compute metrics
              </button>

              {metricsError && (
                <div className="flex items-start gap-2 rounded-lg border border-[var(--se-error)] bg-[var(--se-error-sf)] px-3 py-2 text-xs text-[var(--se-error)]">
                  <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
                  <span>{metricsError}</span>
                </div>
              )}

              {metricsResult && (
                <div className={clsx(cardCls, 'p-4')}>
                  <div className="flex items-center gap-1.5 text-[11px] text-[var(--se-text-mut)] mb-2">
                    <Table2 className="w-3.5 h-3.5" /> Indicators
                  </div>
                  <div className="grid gap-2 sm:grid-cols-3">
                    {Object.entries(metricsResult).map(([k, v]) => (
                      <div
                        key={k}
                        className="rounded-lg border border-[var(--se-border)] bg-[var(--se-rail)] px-3 py-2"
                      >
                        <div className="text-[10px] uppercase tracking-wide text-[var(--se-text-mut)]">{k}</div>
                        <div className="text-sm font-mono text-[var(--se-text)]">
                          {numberOrNull(v)?.toFixed(3) ?? String(v)}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
