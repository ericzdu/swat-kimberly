import { Info } from 'lucide-react';
import type { EditorColumn } from '@/lib/api';

// SWAT+ Editor-style structured record editor: one object edited via labeled fields
// (label + unit + description tooltip + typed input / coded dropdown), grouped in a grid.
export default function RecordForm({ columns, header, values, onChange, readOnlyFirst }: {
  columns?: EditorColumn[];
  header: string[];
  values: string[];
  onChange: (index: number, value: string) => void;
  readOnlyFirst?: boolean;   // first column is usually the object name/id
}) {
  const cols: EditorColumn[] = columns && columns.length === header.length
    ? columns
    : header.map(h => ({ col: h, label: h.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()), unit: '', desc: '', type: 'text' as const }));

  const inputCls =
    'mt-1 w-full bg-[var(--se-card)] border border-[var(--se-border)] rounded-lg px-2.5 py-1.5 text-sm ' +
    'text-[var(--se-text)] tabular-nums focus:outline-none focus:border-[var(--se-accent)] disabled:bg-[var(--se-rail)] disabled:text-[var(--se-text-mut)]';

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-x-4 gap-y-3">
      {cols.map((c, i) => (
        <label key={c.col} className="block min-w-0">
          <span className="flex items-center gap-1 text-[11px] font-medium text-[var(--se-text-mut)] truncate">
            {c.label}
            {c.unit && <span className="text-[var(--se-text-fnt)] font-normal">({c.unit})</span>}
            {c.desc && (
              <span title={c.desc} className="cursor-help shrink-0"><Info className="w-3 h-3 text-[var(--se-text-fnt)]" /></span>
            )}
          </span>
          {c.type === 'select' && c.options ? (
            <select className={inputCls} value={values[i] ?? ''} onChange={e => onChange(i, e.target.value)}>
              {!c.options.some(o => o.value === (values[i] ?? '')) && <option value={values[i] ?? ''}>{values[i] ?? '—'}</option>}
              {c.options.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
            </select>
          ) : (
            <input
              className={inputCls}
              type={c.type === 'number' ? 'number' : 'text'}
              step="any"
              value={values[i] ?? ''}
              disabled={readOnlyFirst && i === 0}
              onChange={e => onChange(i, e.target.value)}
            />
          )}
        </label>
      ))}
    </div>
  );
}
