import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { farms, data, scenarios, type Farm, type FarmReadiness } from '@/lib/api';
import DataChecklist from '@/components/DataChecklist';
import CropSettings from '@/components/CropSettings';
import SetupProgress from '@/components/SetupProgress';
import ErrorBanner from '@/components/ErrorBanner';
import RunProgress from '@/components/RunProgress';
import InsightCard from '@/components/InsightCard';
import {
  ArrowRight, ArrowLeft, Upload, Map, Loader2, CheckCircle, Droplets, Sprout, MapPin,
} from 'lucide-react';

const STEPS = ['Welcome', 'Data', 'Checklist', 'Run', 'Done'];

function pickResumeStep(farm: Farm, readiness: FarmReadiness | null): number {
  if (farm.setup_complete) return 4;
  if (!readiness) return 1;
  const hasModel = readiness.checks.some(c => c.id === 'txtinout' && c.status === 'ok');
  if (readiness.ready_to_simulate) {
    return readiness.last_run?.status === 'completed' ? 4 : 3;
  }
  if (hasModel) return 2;
  return 1;
}

export default function SetupWizard() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const resumeFarmId = searchParams.get('farm') || '';
  const [step, setStep] = useState(0);
  const [farm, setFarm] = useState<Farm | null>(null);
  const [form, setForm] = useState({ name: '', location: '', soil_type: '' });
  const [readiness, setReadiness] = useState<FarmReadiness | null>(null);
  const [loading, setLoading] = useState(false);
  const [bootstrapping, setBootstrapping] = useState(!!resumeFarmId);
  const [error, setError] = useState('');
  const [runProgress, setRunProgress] = useState(0);
  const [runAdvice, setRunAdvice] = useState('');
  const [dataStatus, setDataStatus] = useState<Awaited<ReturnType<typeof data.getStatus>> | null>(null);
  const [insights, setInsights] = useState<Awaited<ReturnType<typeof farms.insights>> | null>(null);

  useEffect(() => {
    if (!resumeFarmId) return;
    let cancelled = false;
    (async () => {
      setBootstrapping(true);
      setError('');
      try {
        const list = await farms.list();
        const existing = list.find(f => f.id === resumeFarmId);
        if (!existing) {
          if (!cancelled) setError('Farm not found. It may have been deleted.');
          return;
        }
        const r = await farms.readiness(existing.id);
        if (cancelled) return;
        setFarm(existing);
        setForm({
          name: existing.name || '',
          location: existing.location || '',
          soil_type: existing.soil_type || '',
        });
        setReadiness(r);
        setStep(pickResumeStep(existing, r));
        data.getStatus(existing.id).then(setDataStatus).catch(() => {});
        if (existing.setup_complete) {
          const ins = await farms.insights(existing.id);
          if (!cancelled) setInsights(ins);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Could not load farm');
        }
      } finally {
        if (!cancelled) setBootstrapping(false);
      }
    })();
    return () => { cancelled = true; };
  }, [resumeFarmId]);

  const createFarm = async () => {
    if (!form.name.trim()) { setError('Please enter a farm name'); return; }
    setLoading(true);
    setError('');
    try {
      const f = await farms.create(form);
      setFarm(f);
      setStep(1);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not create farm');
    } finally {
      setLoading(false);
    }
  };

  const uploadZip = async (file: File) => {
    if (!farm) return;
    setLoading(true);
    setError('');
    try {
      const res = await data.uploadTxtinout(farm.id, file);
      setReadiness(res.readiness);
      setStep(2);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Upload failed');
    } finally {
      setLoading(false);
    }
  };

  const refreshReadiness = async () => {
    if (!farm) return;
    const r = await farms.readiness(farm.id);
    setReadiness(r);
    data.getStatus(farm.id).then(setDataStatus).catch(() => setDataStatus(null));
  };

  const runFirstSim = async () => {
    if (!farm) return;
    setLoading(true);
    setRunProgress(10);
    setError('');
    try {
      setRunProgress(30);
      const result = await scenarios.run(farm.id, 'irrigation');
      setRunProgress(100);
      setRunAdvice(result.advice);
      await farms.update(farm.id, { setup_complete: true });
      const ins = await farms.insights(farm.id);
      setInsights(ins);
      setStep(4);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Simulation failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-8">
      <div>
        <h1 className="text-2xl font-bold text-white">Set Up Your Farm</h1>
        <p className="text-white/40 text-sm mt-1">Step {step + 1} of {STEPS.length}: {STEPS[step]}</p>
        <div className="flex gap-1 mt-4">
          {STEPS.map((_, i) => (
            <div key={i} className={`h-1 flex-1 rounded-full ${i <= step ? 'bg-moss-500' : 'bg-white/10'}`} />
          ))}
        </div>
      </div>

      {error && (
        <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20 text-red-300 text-sm">{error}</div>
      )}

      {bootstrapping ? (
        <div className="flex items-center gap-2 text-white/40 text-sm py-12 justify-center">
          <Loader2 className="w-5 h-5 animate-spin" /> Loading your farm...
        </div>
      ) : (
        <>
      {step === 0 && !resumeFarmId && (
        <div className="space-y-4">
          <p className="text-white/60 text-sm">Tell us about your farm. You can add field data in the next step.</p>
          <input
            className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm"
            placeholder="Farm name *"
            value={form.name}
            onChange={e => setForm(f => ({ ...f, name: e.target.value }))}
          />
          <input
            className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm"
            placeholder="Location (optional)"
            value={form.location}
            onChange={e => setForm(f => ({ ...f, location: e.target.value }))}
          />
          <input
            className="w-full bg-white/5 border border-white/10 rounded-lg px-4 py-3 text-sm"
            placeholder="Soil type (optional, e.g. Loam)"
            value={form.soil_type}
            onChange={e => setForm(f => ({ ...f, soil_type: e.target.value }))}
          />
          <button
            onClick={createFarm}
            disabled={loading}
            className="flex items-center gap-2 bg-moss-600 hover:bg-moss-700 disabled:opacity-50 rounded-lg px-6 py-3 text-sm font-medium"
          >
            {loading ? <Loader2 className="w-4 h-4 animate-spin" /> : <>Continue <ArrowRight className="w-4 h-4" /></>}
          </button>
        </div>
      )}

      {step === 1 && farm && (
        <div className="space-y-4">
          <div className="rounded-lg border border-white/10 bg-white/[0.02] px-4 py-3">
            <p className="text-sm font-medium text-white">{farm.name}</p>
            <p className="text-xs text-white/40 mt-0.5">
              {[farm.location, farm.soil_type].filter(Boolean).join(' · ') || 'Add field data below to continue'}
            </p>
          </div>
          <p className="text-white/60 text-sm">How do you want to add your field model?</p>
          <div className="grid gap-4">
            <label className="block border border-white/10 rounded-xl p-5 hover:border-moss-500/50 cursor-pointer transition-colors">
              <div className="flex items-center gap-3 mb-2">
                <Upload className="w-5 h-5 text-moss-400" />
                <span className="font-medium">Upload field model (zip)</span>
              </div>
              <p className="text-xs text-white/40 mb-3">If you already have a SWAT+ TxtInOut folder from another tool, zip it and upload here.</p>
              <input
                type="file"
                accept=".zip"
                className="text-sm text-white/60"
                onChange={e => e.target.files?.[0] && uploadZip(e.target.files[0])}
              />
            </label>
            <button
              onClick={() => navigate(farm ? `/gis?farm=${farm.id}` : '/gis')}
              className="text-left border border-white/10 rounded-xl p-5 hover:border-moss-500/50 transition-colors"
            >
              <div className="flex items-center gap-3 mb-2">
                <Map className="w-5 h-5 text-moss-400" />
                <span className="font-medium">Start from maps</span>
              </div>
              <p className="text-xs text-white/40">Draw your farm on the map and download elevation, soil, and weather automatically.</p>
            </button>
          </div>
          {resumeFarmId ? (
            <button onClick={() => navigate('/farms')} className="flex items-center gap-1 text-sm text-white/40 hover:text-white/70">
              <ArrowLeft className="w-4 h-4" /> Back to My Farms
            </button>
          ) : (
            <button onClick={() => setStep(0)} className="flex items-center gap-1 text-sm text-white/40 hover:text-white/70">
              <ArrowLeft className="w-4 h-4" /> Back
            </button>
          )}
        </div>
      )}

      {step === 2 && readiness && (
        <div className="space-y-4">
          <p className="text-white/60 text-sm">We checked your farm data. Fix any missing items before running.</p>
          {!readiness.ready_to_simulate && readiness.block_reason && (
            <ErrorBanner variant="error" message={readiness.block_reason} />
          )}
          {dataStatus?.setup ? (
            <SetupProgress
              progressPct={dataStatus.setup.progress_pct}
              steps={dataStatus.setup.steps}
            />
          ) : (
            <DataChecklist checks={readiness.checks} showProgress />
          )}
          {farm && (
            <CropSettings farmId={farm.id} onSaved={refreshReadiness} />
          )}
          {farm && (
            <Link to={`/data?farm=${farm.id}`} className="text-xs text-moss-400 hover:underline">
              View all files and run outputs →
            </Link>
          )}
          <div className="flex gap-3">
            <button onClick={() => setStep(1)} className="flex items-center gap-1 text-sm text-white/40 hover:text-white/70 px-4 py-2">
              <ArrowLeft className="w-4 h-4" /> Back
            </button>
            <button
              onClick={() => { refreshReadiness(); setStep(3); }}
              disabled={!readiness.ready_to_simulate}
              className="flex items-center gap-2 bg-moss-600 hover:bg-moss-700 disabled:opacity-40 rounded-lg px-6 py-2 text-sm font-medium"
            >
              Continue <ArrowRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      )}

      {step === 3 && (
        <div className="space-y-4">
          <p className="text-white/60 text-sm">
            We'll run your farm water model. This uses your project's weather and field settings automatically.
          </p>
          {readiness?.simulation_period && (
            <p className="text-xs text-white/40">
              Simulation period: {readiness.simulation_period.begin} to {readiness.simulation_period.end}
            </p>
          )}
          {loading ? (
            <RunProgress progress={runProgress} label="Running farm model..." />
          ) : (
            <button
              onClick={runFirstSim}
              className="flex items-center gap-2 bg-moss-600 hover:bg-moss-700 rounded-lg px-6 py-3 text-sm font-medium"
            >
              Run my farm model
            </button>
          )}
          <button onClick={() => setStep(2)} className="flex items-center gap-1 text-sm text-white/40 hover:text-white/70">
            <ArrowLeft className="w-4 h-4" /> Back
          </button>
        </div>
      )}

      {step === 4 && (
        <div className="space-y-6">
          <div className="flex items-center gap-3 text-moss-400">
            <CheckCircle className="w-8 h-8" />
            <div>
              <h2 className="text-lg font-semibold text-white">Your farm is ready!</h2>
              {runAdvice && <p className="text-sm text-white/60 mt-1">{runAdvice}</p>}
            </div>
          </div>
          {insights && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              <InsightCard icon={Droplets} label="Irrigation" insight={insights.irrigation} />
              <InsightCard icon={Sprout} label="Fertilizer" insight={insights.fertilizer} />
              <InsightCard icon={MapPin} label="Drought risk" insight={insights.drought_risk} />
            </div>
          )}
          <div className="flex gap-3">
            <button
              onClick={() => navigate('/')}
              className="bg-moss-600 hover:bg-moss-700 rounded-lg px-6 py-2 text-sm font-medium"
            >
              Go to Home
            </button>
            <button
              onClick={() => navigate('/chat')}
              className="border border-white/10 hover:bg-white/5 rounded-lg px-6 py-2 text-sm"
            >
              Ask the advisor
            </button>
          </div>
        </div>
      )}
        </>
      )}
    </div>
  );
}
