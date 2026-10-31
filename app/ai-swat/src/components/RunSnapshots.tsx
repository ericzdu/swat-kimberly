import { useCallback, useEffect, useState } from 'react';
import { swatModel, type SimResult } from '@/lib/api';
import { Camera, Pencil, GitCompare, RefreshCw, RotateCw, Loader2 } from 'lucide-react';
import clsx from 'clsx';

// A list of a field's saved runs (snapshots). Click one to view its timeline,
// rename it, or tick two+ and compare them side by side.
export default function RunSnapshots({ farmId, activeRunId, onView, onCompare, reloadKey }: {
  farmId: string;
  activeRunId?: string;
  onView: (runId: string | undefined) => void;
  onCompare: (ids: string[]) => void;
  reloadKey?: number;
}) {
  const [runs, setRuns] = useState<SimResult[]>([]);
  const [loading, setLoading] = useState(true);
  const [sel, setSel] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    swatModel.listRuns(farmId)
      .then(rs => setRuns(rs.filter(r => r.status === 'completed')))
      .catch(() => setRuns([]))
      .finally(() => setLoading(false));
  }, [farmId]);
  useEffect(() => { load(); }, [load, reloadKey]);

  const rid = (r: SimResult) => r.run_id || '';
  const name = (r: SimResult) => r.label || r.scenario || 'baseline';
  const fmt = (s?: string) => s ? new Date(s).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '';
  const toggle = (id: string) => setSel(s => { const n = new Set(s); if (n.has(id)) n.delete(id); else n.add(id); return n; });
  const saveLabel = async (id: string) => {
    const label = draft.trim(); setEditing(null);
    if (label) { await swatModel.labelRun(id, label).catch(() => {}); load(); }
  };
  const doRerun = async (id: string) => {
    setBusy(true);
    try {
      const res = await swatModel.rerun(id);
      for (let i = 0; i < 40; i++) {                       // poll the new run to completion
        await new Promise(r => setTimeout(r, 3000));
        const st = await swatModel.runStatus(res.run_id).catch(() => null);
        if (st && (st.status === 'completed' || st.status === 'failed')) break;
      }
    } catch { /* leave list as-is on error */ }
    setBusy(false);
    load();
  };

  if (loading && !runs.length) return null;
  if (runs.length <= 1) return null;   // nothing to browse/compare until there are 2+ snapshots

  const currentId = activeRunId || rid(runs[0]);

  return (
    <div className="rounded-xl border border-[var(--se-border)] bg-[var(--se-card)] overflow-hidden">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-[var(--se-border-lt)]">
        <Camera className="w-4 h-4 text-[var(--se-accent)]" />
        <span className="text-xs font-semibold text-[var(--se-text)]">Run snapshots</span>
        <span className="text-[11px] text-[var(--se-text-fnt)]">{runs.length} saved</span>
        {busy && <span className="flex items-center gap-1 text-[11px] text-[var(--se-accent)]"><Loader2 className="w-3 h-3 animate-spin" /> re-running…</span>}
        <button onClick={load} title="Refresh" className="ml-auto p-1 rounded text-[var(--se-text-fnt)] hover:text-[var(--se-accent)]">
          <RefreshCw className="w-3.5 h-3.5" />
        </button>
      </div>

      <div className="max-h-56 overflow-y-auto divide-y divide-[var(--se-border-lt)]">
        {runs.map(r => {
          const id = rid(r); const active = id === currentId;
          return (
            <div key={id} className={clsx('flex items-center gap-2.5 px-3 py-2', active && 'bg-[var(--se-accent-sf)]')}>
              <input type="checkbox" checked={sel.has(id)} onChange={() => toggle(id)}
                className="accent-[var(--se-accent)] shrink-0" aria-label={`Select ${name(r)} to compare`} />
              <button onClick={() => onView(id)} className="flex-1 min-w-0 text-left">
                <div className="flex items-center gap-1.5">
                  {editing === id ? (
                    <input autoFocus value={draft}
                      onChange={e => setDraft(e.target.value)}
                      onBlur={() => saveLabel(id)}
                      onKeyDown={e => { if (e.key === 'Enter') saveLabel(id); if (e.key === 'Escape') setEditing(null); }}
                      onClick={e => e.stopPropagation()}
                      className="text-[13px] bg-[var(--se-bg)] border border-[var(--se-accent)] rounded px-1.5 py-0.5 w-44 focus:outline-none" />
                  ) : (
                    <span className={clsx('text-[13px] font-medium truncate', active ? 'text-[var(--se-accent)]' : 'text-[var(--se-text)]')}>{name(r)}</span>
                  )}
                  {active && <span className="text-[9px] uppercase tracking-wide text-[var(--se-accent)] shrink-0">viewing</span>}
                </div>
                <div className="text-[11px] text-[var(--se-text-fnt)] truncate">
                  {fmt(r.completed_at || r.created_at)}
                  {r.begin_date && r.end_date ? ` · ${r.begin_date.slice(-4)}–${r.end_date.slice(-4)}` : ''}
                </div>
              </button>
              <button onClick={() => doRerun(id)} disabled={busy} title="Re-run this setup as a new snapshot"
                className="p-1 rounded text-[var(--se-text-fnt)] hover:text-[var(--se-accent)] disabled:opacity-40 shrink-0">
                <RotateCw className="w-3.5 h-3.5" />
              </button>
              <button onClick={() => { setEditing(id); setDraft(name(r)); }} title="Rename snapshot"
                className="p-1 rounded text-[var(--se-text-fnt)] hover:text-[var(--se-accent)] shrink-0">
                <Pencil className="w-3.5 h-3.5" />
              </button>
            </div>
          );
        })}
      </div>

      {sel.size >= 1 && (
        <div className="flex items-center gap-2 px-3 py-2 border-t border-[var(--se-border-lt)] bg-[var(--se-bg)]">
          <span className="text-[11px] text-[var(--se-text-mut)]">{sel.size} selected</span>
          <button disabled={sel.size < 2} onClick={() => onCompare([...sel])}
            className="ml-auto flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-[var(--se-accent)] text-white hover:opacity-90 disabled:opacity-40">
            <GitCompare className="w-3.5 h-3.5" /> Compare{sel.size >= 2 ? ` (${sel.size})` : ''}
          </button>
          <button onClick={() => setSel(new Set())} className="text-xs text-[var(--se-text-fnt)] hover:text-[var(--se-text)]">Clear</button>
        </div>
      )}
    </div>
  );
}
