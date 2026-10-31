import { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { system, type Provider, type SystemStatus } from '@/lib/api';
import {
  Loader2, CheckCircle, XCircle, Wifi, RefreshCw, Server,
  Cloud, HardDrive, KeyRound, Circle,
} from 'lucide-react';
import clsx from 'clsx';

const FALLBACK_PROVIDERS: Provider[] = [
  { id: 'ollama', label: 'Ollama (Local)', models: [], has_api_key: true, status: 'offline', kind: 'local' },
  { id: 'groq', label: 'Groq', models: ['llama-3.3-70b-versatile'], has_api_key: false, status: 'offline', kind: 'cloud', default_model: 'llama-3.3-70b-versatile' },
  { id: 'openai', label: 'OpenAI', models: ['gpt-4o-mini'], has_api_key: false, status: 'offline', kind: 'cloud', default_model: 'gpt-4o-mini' },
  { id: 'anthropic', label: 'Anthropic', models: ['claude-haiku-4-5-20251001'], has_api_key: false, status: 'offline', kind: 'cloud', default_model: 'claude-haiku-4-5-20251001' },
  { id: 'openrouter', label: 'OpenRouter', models: ['openrouter/auto'], has_api_key: false, status: 'offline', kind: 'cloud', default_model: 'openrouter/auto' },
  { id: 'minimax', label: 'MiniMax', models: ['MiniMax-M2.5'], has_api_key: false, status: 'offline', kind: 'cloud', default_model: 'MiniMax-M2.5' },
];

const CLOUD_HINTS: Record<string, string> = {
  groq: 'Get a free key at console.groq.com',
  openai: 'Get a key at platform.openai.com',
  anthropic: 'Get a key at console.anthropic.com',
  openrouter: 'Get a key at openrouter.ai',
  minimax: 'Get a key at minimax.chat',
};

function friendlyError(msg: string): string {
  if (!msg) return 'Something went wrong. Try again.';
  if (msg.includes('API key')) return 'Add your API key below, then click Test again.';
  if (msg.includes('Ollama')) return 'Start Ollama on your PC and pull a model (see Step 2).';
  if (msg.includes('fetch') || msg.includes('Failed')) return 'Cannot reach the server. Start the backend and click Refresh.';
  return msg;
}

function StepDot({ done, active, n }: { done: boolean; active: boolean; n: number }) {
  if (done) return <CheckCircle className="w-5 h-5 text-[var(--se-ok)] shrink-0" />;
  if (active) return <span className="w-5 h-5 rounded-full bg-[var(--se-accent)] text-white text-xs flex items-center justify-center shrink-0">{n}</span>;
  return <Circle className="w-5 h-5 text-[var(--se-text-fnt)] shrink-0" />;
}

export default function SettingsPage() {
  const [loading, setLoading] = useState(true);
  const [backendOk, setBackendOk] = useState(false);
  const [providers, setProviders] = useState<Provider[]>(FALLBACK_PROVIDERS);
  const [settings, setSettings] = useState({ provider: 'ollama', model: '' });
  const [aiMessage, setAiMessage] = useState('');
  const [aiConfigured, setAiConfigured] = useState(false);
  const [mode, setMode] = useState<'local' | 'cloud'>('local');
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string | null } | null>(null);
  const [saving, setSaving] = useState(false);
  const [toast, setToast] = useState<{ type: 'ok' | 'err'; text: string } | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [loadError, setLoadError] = useState('');

  const cloudProviders = useMemo(() => providers.filter(p => p.kind === 'cloud'), [providers]);
  const current = providers.find(p => p.id === settings.provider);
  const models = current?.models?.length ? current.models : (current?.id === 'ollama' ? [] : []);

  const effectiveModel = settings.model || current?.default_model || models[0] || '';

  const applyStatus = useCallback((data: SystemStatus) => {
    setBackendOk(data.backend?.ok ?? true);
    setProviders(data.providers?.length ? data.providers : FALLBACK_PROVIDERS);
    const saved = data.settings || { provider: 'ollama', model: '' };
    setSettings(saved);
    setAiMessage(data.ai?.message || '');
    setAiConfigured(!!data.ai?.configured);
    const p = data.providers?.find(x => x.id === saved.provider);
    setMode(p?.kind === 'cloud' ? 'cloud' : 'local');
    setLoadError('');
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    try {
      const data = await system.status();
      applyStatus(data);
    } catch (e) {
      setBackendOk(false);
      setProviders(FALLBACK_PROVIDERS);
      setLoadError(friendlyError(e instanceof Error ? e.message : 'Backend not reachable'));
    } finally {
      setLoading(false);
    }
  }, [applyStatus]);

  useEffect(() => { load(); }, [load]);

  const pickLocal = () => {
    setMode('local');
    const ollama = providers.find(p => p.id === 'ollama');
    setSettings({ provider: 'ollama', model: settings.provider === 'ollama' ? settings.model : '' });
    setTestResult(null);
    if (!ollama?.models?.length) setAiMessage('Install Ollama and pull a model to use local AI.');
  };

  const pickCloud = (id: string) => {
    setMode('cloud');
    const p = providers.find(x => x.id === id) || cloudProviders[0];
    if (!p) return;
    setSettings(s => ({
      provider: p.id,
      model: s.provider === p.id ? s.model : (p.default_model || p.models?.[0] || ''),
    }));
    setTestResult(null);
  };

  const testConnection = async () => {
    if (!backendOk) {
      setTestResult({ ok: false, error: 'Start the backend first (see Step 1).' });
      return;
    }
    setTesting(true);
    setTestResult(null);
    try {
      const res = await system.test(settings.provider, effectiveModel);
      setTestResult(res.ok ? res : { ok: false, error: friendlyError(res.error || 'Test failed') });
    } catch (e) {
      setTestResult({ ok: false, error: friendlyError(e instanceof Error ? e.message : 'Test failed') });
    } finally {
      setTesting(false);
    }
  };

  const saveAll = async () => {
    if (!backendOk) {
      setToast({ type: 'err', text: 'Start the backend before saving.' });
      return;
    }
    setSaving(true);
    setToast(null);
    try {
      await system.saveSettings({ provider: settings.provider, model: effectiveModel });
      if (apiKey.trim() && settings.provider !== 'ollama') {
        const keyRes = await system.saveKeys({ [settings.provider]: apiKey.trim() });
        if (keyRes && 'ok' in keyRes && !keyRes.ok) {
          setToast({ type: 'err', text: (keyRes as { error?: string }).error || 'Invalid API key.' });
          setSaving(false);
          return;
        }
        setApiKey('');
      }
      const data = await system.status();
      applyStatus(data);
      setToast({ type: 'ok', text: 'Saved! Open Farm Advisor to start chatting.' });
    } catch {
      setToast({ type: 'err', text: 'Could not save. Check the server is running.' });
    } finally {
      setSaving(false);
    }
  };

  const step1Done = backendOk;
  const step2Done = step1Done && (settings.provider === 'ollama'
    ? (current?.status === 'online' || (current?.models?.length ?? 0) > 0)
    : !!current?.has_api_key || apiKey.trim().length > 0);
  const step3Done = !!(aiConfigured || testResult?.ok);

  return (
    <div className="p-6 max-w-2xl mx-auto space-y-6">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-[var(--se-text)]">Connect AI</h1>
          <p className="text-sm text-[var(--se-text-mut)] mt-1">
            Three steps: start the server, pick how AI runs, then test and save.
          </p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs text-[var(--se-text-mut)] hover:text-[var(--se-text)] hover:bg-[var(--se-rail)] border border-[var(--se-border)] rounded-lg px-3 py-2"
        >
          <RefreshCw className={clsx('w-3.5 h-3.5', loading && 'animate-spin')} /> Refresh
        </button>
      </div>

      {/* Progress */}
      <div className="grid grid-cols-3 gap-2 text-xs">
        {[
          { n: 1, label: 'Server', done: step1Done, active: !step1Done },
          { n: 2, label: 'Choose AI', done: step2Done, active: step1Done && !step2Done },
          { n: 3, label: 'Test & save', done: step3Done, active: step2Done && !step3Done },
        ].map(s => (
          <div key={s.n} className={clsx('flex items-center gap-2 rounded-lg border px-3 py-2', s.done ? 'border-[var(--se-accent-bd)] bg-[var(--se-accent-sf)]' : s.active ? 'border-[var(--se-border)] bg-[var(--se-rail)]' : 'border-[var(--se-border)] opacity-60')}>
            <StepDot done={s.done} active={s.active} n={s.n} />
            <span className="text-[var(--se-text-mut)]">{s.label}</span>
          </div>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-[var(--se-text-fnt)] text-sm py-12 justify-center">
          <Loader2 className="w-5 h-5 animate-spin" /> Loading...
        </div>
      ) : (
        <>
          {/* Step 1 */}
          <section className={clsx('rounded-xl border bg-[var(--se-card)] shadow-sm p-4 space-y-2', backendOk ? 'border-[var(--se-accent-bd)]' : 'border-[var(--se-error)]')}>
            <div className="flex items-center gap-2">
              <Server className={clsx('w-4 h-4', backendOk ? 'text-[var(--se-accent)]' : 'text-[var(--se-error)]')} />
              <h2 className="text-sm font-semibold text-[var(--se-text)]">Step 1: Backend server</h2>
            </div>
            <p className="text-sm text-[var(--se-text-mut)]">
              {backendOk
                ? 'Server is running. You can configure AI below.'
                : 'The app cannot talk to the API yet. Start it in a terminal:'}
            </p>
            {!backendOk && (
              <pre className="text-[11px] text-[var(--se-text-mut)] bg-[var(--se-rail)] rounded-lg p-3 overflow-x-auto">
{`cd "G:\\AI-SWAT+ project\\ai-swat\\backend"
python run_server.py`}
              </pre>
            )}
            {loadError && <p className="text-xs text-[var(--se-error)]">{loadError}</p>}
          </section>

          {/* Step 2 */}
          <section className={clsx('rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] shadow-sm p-4 space-y-4', !backendOk && 'opacity-50 pointer-events-none')}>
            <div className="flex items-center gap-2">
              <HardDrive className="w-4 h-4 text-[var(--se-accent)]" />
              <h2 className="text-sm font-semibold text-[var(--se-text)]">Step 2: How should AI run?</h2>
            </div>

            <div className="flex gap-2">
              <button
                type="button"
                onClick={pickLocal}
                className={clsx(
                  'flex-1 rounded-lg border px-4 py-3 text-left text-sm transition-all',
                  mode === 'local' ? 'border-[var(--se-accent-bd)] bg-[var(--se-accent-sf)]' : 'border-[var(--se-border)] hover:border-[var(--se-accent-bd)]'
                )}
              >
                <div className="flex items-center gap-2 font-medium text-[var(--se-text)]">
                  <HardDrive className="w-4 h-4 text-[var(--se-accent)]" /> On this PC (Ollama)
                </div>
                <p className="text-xs text-[var(--se-text-fnt)] mt-1">Free, private, runs locally</p>
              </button>
              <button
                type="button"
                onClick={() => pickCloud(settings.provider !== 'ollama' ? settings.provider : (cloudProviders[0]?.id || 'groq'))}
                className={clsx(
                  'flex-1 rounded-lg border px-4 py-3 text-left text-sm transition-all',
                  mode === 'cloud' ? 'border-[var(--se-accent-bd)] bg-[var(--se-accent-sf)]' : 'border-[var(--se-border)] hover:border-[var(--se-accent-bd)]'
                )}
              >
                <div className="flex items-center gap-2 font-medium text-[var(--se-text)]">
                  <Cloud className="w-4 h-4 text-[var(--se-accent)]" /> Cloud API
                </div>
                <p className="text-xs text-[var(--se-text-fnt)] mt-1">Groq, OpenAI, MiniMax, etc.</p>
              </button>
            </div>

            {mode === 'local' && (
              <div className="space-y-3 bg-[var(--se-rail)] rounded-lg border border-[var(--se-border)] p-4">
                {(current?.models?.length ?? 0) > 0 ? (
                  <>
                    <p className="text-xs text-[var(--se-accent)]">Ollama is running ({current?.models?.length} model(s) found)</p>
                    <label className="text-xs text-[var(--se-text-mut)] block">Model</label>
                    <select
                      className="w-full bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm text-[var(--se-text)] focus:border-[var(--se-accent)] focus:outline-none"
                      value={settings.model}
                      onChange={e => setSettings(s => ({ ...s, model: e.target.value }))}
                    >
                      <option value="">Auto (first available)</option>
                      {current?.models?.map(m => <option key={m} value={m}>{m}</option>)}
                    </select>
                  </>
                ) : (
                  <div className="text-sm space-y-2">
                    <p className="text-[var(--se-warn)] font-medium">Ollama not detected</p>
                    <ol className="text-xs text-[var(--se-text-mut)] list-decimal list-inside space-y-1">
                      <li>Download from <a href="https://ollama.com" className="text-[var(--se-accent)] underline" target="_blank" rel="noreferrer">ollama.com</a></li>
                      <li>Open a terminal and run: <code className="bg-[var(--se-rail)] text-[var(--se-text-mut)] px-1 rounded">ollama pull llama3.2</code></li>
                      <li>Click <strong>Refresh</strong> at the top of this page</li>
                    </ol>
                  </div>
                )}
              </div>
            )}

            {mode === 'cloud' && (
              <div className="space-y-3 bg-[var(--se-rail)] rounded-lg border border-[var(--se-border)] p-4">
                <label className="text-xs text-[var(--se-text-mut)] block">Provider</label>
                <select
                  className="w-full bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm text-[var(--se-text)] focus:border-[var(--se-accent)] focus:outline-none"
                  value={settings.provider === 'ollama' ? (cloudProviders[0]?.id || 'groq') : settings.provider}
                  onChange={e => pickCloud(e.target.value)}
                >
                  {cloudProviders.map(p => (
                    <option key={p.id} value={p.id}>
                      {p.label}{p.has_api_key ? ' (key saved)' : ''}
                    </option>
                  ))}
                </select>

                <label className="text-xs text-[var(--se-text-mut)] block">Model</label>
                <select
                  className="w-full bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm text-[var(--se-text)] focus:border-[var(--se-accent)] focus:outline-none"
                  value={settings.model}
                  onChange={e => setSettings(s => ({ ...s, model: e.target.value }))}
                >
                  <option value="">Default (recommended)</option>
                  {(current?.models?.length ? current.models : FALLBACK_PROVIDERS.find(p => p.id === settings.provider)?.models || []).map(m => (
                    <option key={m} value={m}>{m}</option>
                  ))}
                </select>

                <div>
                  <div className="flex items-center gap-2 mb-1">
                    <KeyRound className="w-3.5 h-3.5 text-[var(--se-text-fnt)]" />
                    <label className="text-xs text-[var(--se-text-mut)]">API key</label>
                  </div>
                  <input
                    type="password"
                    className="w-full bg-white border border-[var(--se-border)] rounded-lg px-3 py-2 text-sm text-[var(--se-text)] focus:border-[var(--se-accent)] focus:outline-none"
                    placeholder={current?.has_api_key ? 'Key saved - paste new key to replace' : 'Paste your API key here'}
                    value={apiKey}
                    onChange={e => setApiKey(e.target.value)}
                  />
                  <p className="text-[10px] text-[var(--se-text-fnt)] mt-1">
                    {CLOUD_HINTS[settings.provider] || 'Keys are stored on your machine only.'}
                  </p>
                </div>
              </div>
            )}

            {aiMessage && !aiConfigured && (
              <p className="text-xs text-[var(--se-warn)] bg-[var(--se-warn-sf)] border border-[var(--se-warn)] rounded-lg px-3 py-2">
                {aiMessage}
              </p>
            )}
          </section>

          {/* Step 3 */}
          <section className={clsx('rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] shadow-sm p-4 space-y-4', !backendOk && 'opacity-50 pointer-events-none')}>
            <div className="flex items-center gap-2">
              <Wifi className="w-4 h-4 text-[var(--se-accent)]" />
              <h2 className="text-sm font-semibold text-[var(--se-text)]">Step 3: Test and save</h2>
            </div>

            <p className="text-xs text-[var(--se-text-mut)]">
              Using <strong className="text-[var(--se-text)]">{current?.label || settings.provider}</strong>
              {effectiveModel && <> with model <strong className="text-[var(--se-text)]">{effectiveModel}</strong></>}
            </p>

            <div className="flex flex-wrap items-center gap-3">
              <button
                onClick={testConnection}
                disabled={testing || !backendOk}
                className="flex items-center gap-2 bg-[var(--se-rail)] hover:bg-[var(--se-border-lt)] text-[var(--se-text)] border border-[var(--se-border)] disabled:opacity-40 rounded-lg px-4 py-2.5 text-sm"
              >
                {testing ? <Loader2 className="w-4 h-4 animate-spin" /> : <Wifi className="w-4 h-4" />}
                Test connection
              </button>
              <button
                onClick={saveAll}
                disabled={saving || !backendOk}
                className="flex items-center gap-2 bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40 rounded-lg px-5 py-2.5 text-sm font-medium"
              >
                {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
                Save settings
              </button>
            </div>

            {testResult && (
              <div className={clsx('flex items-start gap-2 text-sm rounded-lg px-3 py-2', testResult.ok ? 'bg-[var(--se-ok-sf)] text-[var(--se-ok)]' : 'bg-[var(--se-error-sf)] text-[var(--se-error)]')}>
                {testResult.ok ? <CheckCircle className="w-4 h-4 shrink-0 mt-0.5" /> : <XCircle className="w-4 h-4 shrink-0 mt-0.5" />}
                <span>{testResult.ok ? 'Connection works! Click Save settings, then open Farm Advisor.' : testResult.error}</span>
              </div>
            )}

            {aiConfigured && !testResult && (
              <p className="text-sm text-[var(--se-ok)] flex items-center gap-2">
                <CheckCircle className="w-4 h-4" /> AI is ready. Open <Link to="/chat" className="underline">Farm Advisor</Link> to chat.
              </p>
            )}
          </section>

          {toast && (
            <p className={clsx('text-sm', toast.type === 'ok' ? 'text-[var(--se-ok)]' : 'text-[var(--se-error)]')}>{toast.text}</p>
          )}
        </>
      )}
    </div>
  );
}
