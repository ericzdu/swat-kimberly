import { useCallback, useEffect, useState } from 'react';
import { Info, Plus, Trash2, Loader2, Save, Check, RefreshCw, Layers } from 'lucide-react';
import { swatEditor, type EditorSoil, type EditorSoilContent, type EditorColumn } from '@/lib/api';
import RecordForm from './RecordForm';

// SWAT+ Editor-style soils.sol editor: a soil-property form + an editable per-layer
// sub-grid (the file is nested soil → layers, so a flat table can't represent it).
export default function SoilEditor({ farmId }: { farmId: string }) {
  const [data, setData] = useState<EditorSoilContent | null>(null);
  const [soils, setSoils] = useState<EditorSoil[]>([]);
  const [sel, setSel] = useState(0);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError(''); setSaved(false);
    try {
      const d = await swatEditor.readSoil(farmId);
      if (!d.ok) { setError(d.error || 'Failed to load soils.sol'); setData(null); }
      else { setData(d); setSoils(d.soils.map(s => ({ ...s, layers: s.layers.map(l => ({ ...l })) }))); setSel(0); }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setLoading(false);
  }, [farmId]);
  useEffect(() => { void load(); }, [load]);

  const soil = soils[sel];

  const setSoilField = (col: string, value: string) =>
    setSoils(prev => prev.map((s, i) => (i === sel ? { ...s, [col]: value } : s)));

  const setLayerField = (li: number, col: string, value: string) =>
    setSoils(prev => prev.map((s, i) => i === sel
      ? { ...s, layers: s.layers.map((l, j) => (j === li ? { ...l, [col]: value } : l)) }
      : s));

  const addLayer = () => setSoils(prev => prev.map((s, i) => {
    if (i !== sel) return s;
    const last = s.layers[s.layers.length - 1];
    const blank: Record<string, string> = {};
    (data?.layer_cols || []).forEach(c => { blank[c.col] = last ? (last[c.col] ?? '0.00000') : '0.00000'; });
    return { ...s, layers: [...s.layers, blank] };
  }));

  const delLayer = (li: number) => setSoils(prev => prev.map((s, i) =>
    i === sel ? { ...s, layers: s.layers.filter((_, j) => j !== li) } : s));

  const save = async () => {
    setSaving(true); setError(''); setSaved(false);
    try {
      const payload = soils.map(s => ({ ...s, nly: String(s.layers.length) }));
      const res = await swatEditor.writeSoil(farmId, { soils: payload });
      if (!res.ok) setError('Save failed');
      else { setSaved(true); setTimeout(() => setSaved(false), 2500); }
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    setSaving(false);
  };

  if (loading) return <div className="flex items-center gap-2 text-sm text-[var(--se-text-mut)] py-6"><Loader2 className="w-4 h-4 animate-spin" /> Loading soils…</div>;
  if (error && !data) return (
    <div className="text-sm text-[var(--se-error)] py-4">
      {error}
      <button onClick={load} className="ml-3 inline-flex items-center gap-1 text-[var(--se-text-mut)] hover:text-[var(--se-text)]"><RefreshCw className="w-3.5 h-3.5" /> Retry</button>
    </div>
  );
  if (!data || !soil) return <div className="text-sm text-[var(--se-text-mut)] py-4">No soils found.</div>;

  // Soil-level fields shown in the form: skip nly (derived from layer count).
  const formCols: EditorColumn[] = (data.soil_cols || []).filter(c => c.col !== 'nly');
  const formHeader = formCols.map(c => c.col);
  const formValues = formCols.map(c => String(soil[c.col] ?? ''));

  const layerCols = data.layer_cols || [];
  const dpIdx = layerCols.findIndex(c => c.col === 'dp');

  const depthLabel = (li: number): string => {
    if (dpIdx < 0) return '';
    const top = li === 0 ? 0 : parseFloat(String(soil.layers[li - 1]?.dp ?? '0')) || 0;
    const bot = parseFloat(String(soil.layers[li]?.dp ?? '0')) || 0;
    return `${(top / 10).toFixed(0)}–${(bot / 10).toFixed(0)} cm`;
  };

  return (
    <div className="space-y-5">
      {/* soil selector + save bar */}
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <Layers className="w-4 h-4 text-[var(--se-accent)]" />
          {soils.length > 1 ? (
            <select
              value={sel}
              onChange={e => setSel(Number(e.target.value))}
              className="bg-[var(--se-card)] border border-[var(--se-border)] rounded-lg px-2.5 py-1.5 text-sm text-[var(--se-text)] focus:outline-none focus:border-[var(--se-accent)]"
            >
              {soils.map((s, i) => <option key={i} value={i}>{String(s.name)} · {s.layers.length} layers</option>)}
            </select>
          ) : (
            <span className="text-sm font-medium text-[var(--se-text)]">{String(soil.name)}</span>
          )}
          <span className="text-xs text-[var(--se-text-mut)]">{soil.layers.length} layer{soil.layers.length === 1 ? '' : 's'} · total depth {(parseFloat(String(soil.dp_tot ?? '0')) / 10).toFixed(0)} cm</span>
        </div>
        <div className="flex items-center gap-2">
          {error && <span className="text-xs text-[var(--se-error)]">{error}</span>}
          <button
            onClick={save}
            disabled={saving}
            className="inline-flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg bg-[var(--se-accent)] text-white hover:opacity-90 disabled:opacity-50"
          >
            {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : saved ? <Check className="w-4 h-4" /> : <Save className="w-4 h-4" />}
            {saved ? 'Saved' : 'Save soil'}
          </button>
        </div>
      </div>

      {/* soil-level properties */}
      <div>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--se-text-mut)] mb-2">Soil properties</h3>
        <RecordForm columns={formCols} header={formHeader} values={formValues} onChange={(i, v) => setSoilField(formCols[i].col, v)} />
      </div>

      {/* layers grid */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-[var(--se-text-mut)]">Layers (top → bottom)</h3>
          <button onClick={addLayer} className="inline-flex items-center gap-1 text-xs px-2 py-1 rounded-md border border-[var(--se-border)] text-[var(--se-text-mut)] hover:text-[var(--se-text)] hover:border-[var(--se-accent-bd)]">
            <Plus className="w-3.5 h-3.5" /> Add layer
          </button>
        </div>
        <div className="overflow-x-auto border border-[var(--se-border)] rounded-lg">
          <table className="text-sm border-collapse">
            <thead>
              <tr className="bg-[var(--se-rail)]">
                <th className="sticky left-0 bg-[var(--se-rail)] px-2 py-2 text-left text-[11px] font-medium text-[var(--se-text-mut)] border-b border-[var(--se-border)] z-10">#</th>
                <th className="px-2 py-2 text-left text-[11px] font-medium text-[var(--se-text-mut)] border-b border-[var(--se-border)] whitespace-nowrap">Depth</th>
                {layerCols.map(c => (
                  <th key={c.col} className="px-2 py-2 text-left text-[11px] font-medium text-[var(--se-text-mut)] border-b border-[var(--se-border)] whitespace-nowrap">
                    <span className="flex items-center gap-1">
                      {c.label}
                      {c.unit && <span className="text-[var(--se-text-fnt)] font-normal">({c.unit})</span>}
                      {c.desc && <span title={c.desc} className="cursor-help"><Info className="w-3 h-3 text-[var(--se-text-fnt)]" /></span>}
                    </span>
                  </th>
                ))}
                <th className="px-2 py-2 border-b border-[var(--se-border)]"></th>
              </tr>
            </thead>
            <tbody>
              {soil.layers.map((ly, li) => (
                <tr key={li} className="hover:bg-[var(--se-rail)]/40">
                  <td className="sticky left-0 bg-[var(--se-card)] px-2 py-1.5 text-[var(--se-text-mut)] border-b border-[var(--se-border)] z-10">{li + 1}</td>
                  <td className="px-2 py-1.5 text-[var(--se-text-mut)] tabular-nums whitespace-nowrap border-b border-[var(--se-border)]">{depthLabel(li)}</td>
                  {layerCols.map(c => (
                    <td key={c.col} className="px-1 py-1 border-b border-[var(--se-border)]">
                      <input
                        value={String(ly[c.col] ?? '')}
                        onChange={e => setLayerField(li, c.col, e.target.value)}
                        className="w-[92px] bg-transparent border border-transparent hover:border-[var(--se-border)] focus:border-[var(--se-accent)] rounded px-1.5 py-1 text-[var(--se-text)] tabular-nums focus:outline-none focus:bg-[var(--se-card)]"
                      />
                    </td>
                  ))}
                  <td className="px-1.5 py-1 border-b border-[var(--se-border)]">
                    <button
                      onClick={() => delLayer(li)}
                      disabled={soil.layers.length <= 1}
                      title="Remove layer"
                      className="p-1 rounded text-[var(--se-text-fnt)] hover:text-[var(--se-error)] disabled:opacity-30"
                    >
                      <Trash2 className="w-3.5 h-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-[11px] text-[var(--se-text-fnt)] mt-2">
          Depth is derived from each layer's depth-to-bottom. Layer count (nly) and total depth update automatically on save. A <span className="font-mono">.bak</span> backup is written before every save.
        </p>
      </div>
    </div>
  );
}
