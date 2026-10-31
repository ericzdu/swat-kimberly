import { useMemo, useState } from 'react';
import { ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';
import type { Widget } from '@/lib/widgets';

// Data table for the canvas. Sortable by any column (numeric-aware) when payload.sortable.
export default function TableWidget({ widget }: { widget: Widget }) {
  const p = widget.payload as { columns?: string[]; rows?: (string | number)[][]; sortable?: boolean };
  const columns = p.columns || [];
  const rows = p.rows || [];
  const sortable = p.sortable !== false;
  const [sort, setSort] = useState<{ col: number; dir: 1 | -1 } | null>(null);

  const sorted = useMemo(() => {
    if (!sort) return rows;
    const { col, dir } = sort;
    return [...rows].sort((a, b) => {
      const av = a[col], bv = b[col];
      const an = typeof av === 'number' ? av : parseFloat(String(av));
      const bn = typeof bv === 'number' ? bv : parseFloat(String(bv));
      if (!Number.isNaN(an) && !Number.isNaN(bn)) return (an - bn) * dir;
      return String(av).localeCompare(String(bv)) * dir;
    });
  }, [rows, sort]);

  const toggle = (col: number) =>
    setSort(s => (s && s.col === col ? { col, dir: (s.dir === 1 ? -1 : 1) as 1 | -1 } : { col, dir: 1 }));

  return (
    <div className="rounded-lg border border-[var(--se-border)] bg-[var(--se-card)] overflow-hidden">
      {widget.title && <h3 className="text-sm font-semibold text-[var(--se-text)] px-3 pt-3 pb-2">{widget.title}</h3>}
      <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="border-b border-[var(--se-border)] bg-[var(--se-rail)]">
            {columns.map((c, i) => (
              <th key={i}
                onClick={sortable ? () => toggle(i) : undefined}
                className={`text-left px-3 py-2 text-[var(--se-text-mut)] font-semibold uppercase text-[11px] tracking-wide ${sortable ? 'cursor-pointer select-none hover:text-[var(--se-text)]' : ''}`}>
                <span className="inline-flex items-center gap-1">
                  {c}
                  {sortable && (sort?.col === i
                    ? (sort.dir === 1 ? <ArrowUp className="w-3 h-3" /> : <ArrowDown className="w-3 h-3" />)
                    : <ArrowUpDown className="w-3 h-3 opacity-30" />)}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, ri) => (
            <tr key={ri} className="border-b border-[var(--se-border-lt)] last:border-0 hover:bg-[var(--se-rail)]">
              {(Array.isArray(r) ? r : [r]).map((cell, ci) => (
                <td key={ci} className="px-3 py-1.5 text-[var(--se-text)] tabular-nums">
                  {typeof cell === 'number' ? cell.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      </div>
    </div>
  );
}
