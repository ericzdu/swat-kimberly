import { useEffect, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { farms, data, type Farm, type FarmDataStatus } from '@/lib/api';
import SetupProgress from '@/components/SetupProgress';
import FileBrowser from '@/components/FileBrowser';
import DataChecklist from '@/components/DataChecklist';
import ErrorBanner from '@/components/ErrorBanner';
import { RefreshCw, Loader2, Database, FolderOpen, PlayCircle } from 'lucide-react';
import clsx from 'clsx';

export default function DataHub() {
  const [searchParams] = useSearchParams();
  const [farmsList, setFarmsList] = useState<Farm[]>([]);
  const [farmId, setFarmId] = useState(searchParams.get('farm') || '');
  const [status, setStatus] = useState<FarmDataStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [tab, setTab] = useState<'overview' | 'files' | 'runs'>('overview');

  useEffect(() => {
    farms.list().then(list => {
      setFarmsList(list);
      if (!farmId && list.length) setFarmId(list[0].id);
    }).catch(() => {});
  }, []);

  useEffect(() => {
    const q = searchParams.get('farm');
    if (q) setFarmId(q);
  }, [searchParams]);

  const load = async () => {
    if (!farmId) return;
    setLoading(true);
    try {
      setStatus(await data.getStatus(farmId));
    } catch {
      setStatus(null);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
  }, [farmId]);

  const setup = status?.setup;

  return (
    <div className="p-6 max-w-5xl mx-auto space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Database className="w-5 h-5 text-moss-400" />
            Farm Data
          </h1>
          <p className="text-sm text-white/40 mt-1">Setup progress, files, and simulation outputs</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            className="bg-white/5 border border-white/10 rounded-lg px-3 py-1.5 text-sm"
            value={farmId}
            onChange={e => setFarmId(e.target.value)}
          >
            <option value="">Select farm...</option>
            {farmsList.map(f => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
          <button
            type="button"
            onClick={load}
            disabled={loading || !farmId}
            className="p-2 rounded-lg border border-white/10 hover:bg-white/5 disabled:opacity-40"
            title="Refresh"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {!farmId && (
        <ErrorBanner variant="info" message="Select a farm to see data status and files." />
      )}

      {farmId && loading && !status && (
        <div className="flex justify-center py-12">
          <Loader2 className="w-8 h-8 animate-spin text-moss-400" />
        </div>
      )}

      {status && setup && (
        <>
          {!setup.ready_to_simulate && setup.block_reason && (
            <ErrorBanner
              variant="error"
              title="Cannot run simulations yet"
              message={setup.block_reason}
              action={{ label: 'Open Maps to fix', to: `/gis?farm=${farmId}` }}
            />
          )}

          <div className="flex gap-2 border-b border-white/10 pb-1">
            {(['overview', 'files', 'runs'] as const).map(t => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className={clsx(
                  'px-4 py-2 text-sm rounded-t-lg capitalize',
                  tab === t ? 'bg-white/10 text-white' : 'text-white/40 hover:text-white/70',
                )}
              >
                {t}
              </button>
            ))}
          </div>

          {tab === 'overview' && (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
              <SetupProgress
                progressPct={setup.progress_pct}
                steps={setup.steps}
                blockReason={setup.block_reason || undefined}
              />
              <div className="space-y-4">
                <DataChecklist checks={status.readiness.checks} showProgress />
                {status.manifest?.sources && (
                  <div className="rounded-xl border border-moss-500/20 bg-moss-500/5 p-4">
                    <p className="text-xs font-medium text-moss-400 mb-2">Verified data sources</p>
                    <ul className="text-xs text-white/60 space-y-1">
                      {(status.manifest.sources as string[]).map((s, i) => (
                        <li key={i}>• {s}</li>
                      ))}
                    </ul>
                  </div>
                )}
                <div className="rounded-xl border border-white/10 p-4 text-xs text-white/50 space-y-1">
                  <p><span className="text-white/30">Data source:</span> {status.data_source || 'none'}</p>
                  <p><span className="text-white/30">GIS folder:</span> <span className="font-mono">{status.gis_dir}</span></p>
                  <p><span className="text-white/30">TxtInOut:</span> <span className="font-mono">{status.txtinout_dir}</span></p>
                </div>
              </div>
            </div>
          )}

          {tab === 'files' && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-2">
                {status.gis_layers.map(layer => (
                  <div
                    key={layer.id}
                    className={clsx(
                      'rounded-lg border px-3 py-2 text-xs',
                      layer.exists ? 'border-moss-500/30 bg-moss-500/5' : 'border-red-500/30 bg-red-500/5',
                    )}
                  >
                    <p className="font-medium text-white/80 capitalize">{layer.id}</p>
                    <p className="text-white/40">{layer.exists ? layer.size_label : 'Missing'}</p>
                  </div>
                ))}
              </div>
              <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                <FileBrowser
                  farmId={farmId}
                  zone="gis"
                  title="Map download files (GIS)"
                  files={status.files.gis}
                  emptyMessage="No GIS files — download map data on Maps"
                />
                <FileBrowser
                  farmId={farmId}
                  zone="txtinout"
                  title="Field model (TxtInOut)"
                  files={status.files.txtinout}
                  emptyMessage="No TxtInOut yet — complete setup or upload zip"
                />
              </div>
            </div>
          )}

          {tab === 'runs' && (
            <div className="space-y-3">
              {status.runs.length === 0 && (
                <ErrorBanner variant="info" message="No simulation runs yet." action={{ label: 'Run in Results', to: '/visualizations' }} />
              )}
              {status.runs.map(run => (
                <div
                  key={run.run_id}
                  className={clsx(
                    'rounded-xl border p-4',
                    run.status === 'completed' ? 'border-moss-500/30 bg-moss-500/5' :
                    run.status === 'failed' ? 'border-red-500/30 bg-red-500/5' :
                    'border-white/10 bg-white/5',
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div>
                      <p className="text-sm font-medium text-white flex items-center gap-2">
                        <PlayCircle className="w-4 h-4" />
                        {run.sim_type || 'run'} · {run.status}
                      </p>
                      <p className="text-xs text-white/40 mt-1 font-mono truncate">{run.run_id}</p>
                      <p className="text-xs text-white/35">{run.completed_at?.slice(0, 19) || run.created_at?.slice(0, 19)}</p>
                    </div>
                    {run.output_count > 0 && (
                      <span className="text-xs text-white/40 flex items-center gap-1">
                        <FolderOpen className="w-3.5 h-3.5" />
                        {run.output_count} output files
                      </span>
                    )}
                  </div>
                  {run.error && (
                    <p className="mt-3 text-xs text-red-300 bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
                      {run.error}
                    </p>
                  )}
                  {run.output_files.length > 0 && (
                    <FileBrowser
                      farmId={farmId}
                      zone={`run:${run.run_id}`}
                      title="SWAT+ output files"
                      files={run.output_files.map(name => ({
                        name,
                        path: name,
                        kind: 'file' as const,
                        size: null,
                        size_label: '',
                        previewable: /\.(txt|dat|fin|log)$/i.test(name),
                      }))}
                    />
                  )}
                </div>
              ))}
            </div>
          )}

          <div className="flex flex-wrap gap-3 pt-2">
            <Link to={`/gis?farm=${farmId}`} className="text-sm text-moss-400 hover:underline">Maps</Link>
            <Link to={`/setup?farm=${farmId}`} className="text-sm text-moss-400 hover:underline">Setup</Link>
            <Link to="/visualizations" className="text-sm text-moss-400 hover:underline">Results charts</Link>
          </div>
        </>
      )}
    </div>
  );
}
