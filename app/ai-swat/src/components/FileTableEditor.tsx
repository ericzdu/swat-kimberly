import { useCallback, useEffect, useMemo, useState } from 'react';
import { swatEditor, type EditorFileContent, type EditorColumn } from '@/lib/api';
import {
  Loader2, Plus, Trash2, Save, RefreshCw, CheckCircle, XCircle, FileText, Table,
  Search, ChevronLeft, ChevronRight, X, Pencil, ArrowLeft,
} from 'lucide-react';
import clsx from 'clsx';
import RecordForm from '@/components/swateditor/RecordForm';

interface Props {
  farmId: string;
  name: string;
  onSaved?: () => void;
  light?: boolean;
}

const PAGE_SIZE = 50;
const ROW_COL_W = 62; // px width of the leading (edit/delete) column — frozen col offset

export default function FileTableEditor({ farmId, name, onSaved, light }: Props) {
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState('');
  const [title, setTitle] = useState('');
  const [desc, setDesc] = useState('');
  const [tabular, setTabular] = useState(true);
  const [header, setHeader] = useState<string[]>([]);
  const [columns, setColumns] = useState<EditorColumn[]>([]);
  const [rows, setRows] = useState<string[][]>([]);
  const [raw, setRaw] = useState('');
  const [editIdx, setEditIdx] = useState<number | null>(null);   // row open in the structured form
  const [saving, setSaving] = useState(false);
  const [saveOk, setSaveOk] = useState(false);
  const [saveError, setSaveError] = useState('');
  const [query, setQuery] = useState('');
  const [page, setPage] = useState(0);

  const applyContent = useCallback((content: EditorFileContent) => {
    if (!content.ok) {
      setLoadError(content.error || 'Could not load this file.');
      return;
    }
    setLoadError('');
    setTitle(content.title || '');
    setDesc(content.desc || '');
    setTabular(content.tabular);
    setHeader(content.header || []);
    setColumns(content.columns || []);
    setRows((content.rows || []).map(r => [...r]));
    setRaw(content.raw || '');
    setQuery('');
    setPage(0);
    setEditIdx(null);
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError('');
    setSaveOk(false);
    setSaveError('');
    try {
      const content = await swatEditor.readFile(farmId, name);
      applyContent(content);
    } catch (e) {
      setLoadError(e instanceof Error ? e.message : 'Could not load this file.');
    } finally {
      setLoading(false);
    }
  }, [farmId, name, applyContent]);

  useEffect(() => {
    load();
  }, [load]);

  const setCell = (rowIdx: number, colIdx: number, value: string) => {
    setRows(prev => {
      const next = prev.slice();
      const row = next[rowIdx].slice();
      row[colIdx] = value;
      next[rowIdx] = row;
      return next;
    });
    setSaveOk(false);
  };

  const addRow = () => {
    setRows(prev => [...prev, header.map(() => '')]);
    setQuery('');
    setPage(Math.floor(rows.length / PAGE_SIZE)); // jump to the page holding the new row
    setSaveOk(false);
  };

  const deleteRow = (rowIdx: number) => {
    setRows(prev => prev.filter((_, i) => i !== rowIdx));
    setSaveOk(false);
  };

  const save = async () => {
    setSaving(true);
    setSaveOk(false);
    setSaveError('');
    try {
      if (tabular) {
        await swatEditor.writeFile(farmId, { name, title, header, rows });
      } else {
        await swatEditor.writeFile(farmId, { name, raw });
      }
      setSaveOk(true);
      onSaved?.();
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : 'Could not save the file.');
    } finally {
      setSaving(false);
    }
  };

  // --- filtering + pagination over real row indices ---
  const q = query.trim().toLowerCase();
  const filteredIdx = useMemo(() => {
    const all = rows.map((_, i) => i);
    if (!q) return all;
    return all.filter(i => rows[i].some(c => (c ?? '').toLowerCase().includes(q)));
  }, [rows, q]);

  const pageCount = Math.max(1, Math.ceil(filteredIdx.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount - 1);
  const pageStart = safePage * PAGE_SIZE;
  const pageIdx = filteredIdx.slice(pageStart, pageStart + PAGE_SIZE);

  // --- theme tokens (light is the only active theme; dark kept for the prop contract) ---
  const railBg = light ? 'var(--se-rail)' : '#171b22';
  const cardBg = light ? 'var(--se-card)' : '#12151b';
  const freezeShadow = `1px 0 0 ${light ? 'var(--se-border)' : 'rgba(255,255,255,0.12)'}`;

  const iconBtn = clsx(
    'flex items-center gap-1.5 text-xs border rounded-lg px-3 py-2 disabled:opacity-40 shrink-0',
    light
      ? 'text-[var(--se-text-mut)] hover:text-[var(--se-accent)] border-[var(--se-border)] hover:border-[var(--se-accent-bd)]'
      : 'text-white/50 hover:text-white/80 border-white/10',
  );

  return (
    <div
      className={clsx(
        'p-4 space-y-4',
        light
          ? 'rounded-lg border border-[var(--se-border)] bg-[var(--se-card)] text-[var(--se-text)]'
          : 'rounded-xl border border-white/10 bg-white/[0.02]',
      )}
    >
      {/* Header */}
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className={clsx('font-mono text-sm font-medium truncate', light ? 'text-[var(--se-text)]' : 'text-white')}>
              {name}
            </span>
            <span
              className={clsx(
                'inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border shrink-0',
                light
                  ? 'bg-[var(--se-accent-sf)] text-[var(--se-accent)] border-[var(--se-accent-bd)]'
                  : tabular
                    ? 'bg-moss-500/15 text-moss-400 border-moss-500/30'
                    : 'bg-blue-500/15 text-blue-300 border-blue-500/30',
              )}
            >
              {tabular ? <Table className="w-3 h-3" /> : <FileText className="w-3 h-3" />}
              {tabular ? 'table' : 'text'}
            </span>
          </div>
          {desc && (
            <p className={clsx('text-xs mt-1', light ? 'text-[var(--se-text-mut)]' : 'text-white/40')}>{desc}</p>
          )}
        </div>
        <button type="button" onClick={load} disabled={loading || saving} className={iconBtn}>
          <RefreshCw className={clsx('w-3.5 h-3.5', loading && 'animate-spin')} /> Reload
        </button>
      </div>

      {loading ? (
        <div className={clsx('flex items-center gap-2 text-sm py-8 justify-center', light ? 'text-[var(--se-text-mut)]' : 'text-white/40')}>
          <Loader2 className="w-4 h-4 animate-spin" /> Loading file...
        </div>
      ) : loadError ? (
        <div className={clsx('flex items-start gap-2 text-sm rounded-lg px-3 py-2', light ? 'bg-[var(--se-error-sf)] text-[var(--se-error)]' : 'bg-red-500/10 text-red-400')}>
          <XCircle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{loadError}</span>
        </div>
      ) : (
        <>
          {tabular && editIdx !== null && rows[editIdx] ? (
            <div className="space-y-4">
              <button
                type="button"
                onClick={() => setEditIdx(null)}
                className={clsx('flex items-center gap-1 text-xs', light ? 'text-[var(--se-text-mut)] hover:text-[var(--se-accent)]' : 'text-white/50 hover:text-white/80')}
              >
                <ArrowLeft className="w-3.5 h-3.5" /> Back to list
              </button>
              <div className="flex items-baseline gap-2">
                <h3 className={clsx('text-sm font-semibold', light ? 'text-[var(--se-text)]' : 'text-white')}>
                  {rows[editIdx][0] || `Record ${editIdx + 1}`}
                </h3>
                <span className={clsx('text-[11px]', light ? 'text-[var(--se-text-fnt)]' : 'text-white/40')}>
                  editing record {editIdx + 1} of {rows.length}
                </span>
              </div>
              <RecordForm
                columns={columns}
                header={header}
                values={rows[editIdx]}
                onChange={(i, v) => setCell(editIdx, i, v)}
                readOnlyFirst
              />
            </div>
          ) : tabular ? (
            <div className="space-y-3">
              {/* Toolbar: search + counts + pagination */}
              <div className="flex flex-wrap items-center gap-3">
                <div className="relative flex-1 min-w-[180px] max-w-sm">
                  <Search className={clsx('absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5', light ? 'text-[var(--se-text-fnt)]' : 'text-white/30')} />
                  <input
                    type="text"
                    value={query}
                    onChange={e => { setQuery(e.target.value); setPage(0); }}
                    placeholder={`Search ${rows.length} rows…`}
                    className={clsx(
                      'w-full rounded-lg pl-8 pr-7 py-1.5 text-xs outline-none border',
                      light
                        ? 'bg-white border-[var(--se-border)] text-[var(--se-text)] focus:border-[var(--se-accent)] placeholder:text-[var(--se-text-fnt)]'
                        : 'bg-white/5 border-white/10 text-white/90 focus:border-moss-500/40',
                    )}
                  />
                  {query && (
                    <button
                      type="button"
                      onClick={() => { setQuery(''); setPage(0); }}
                      className={clsx('absolute right-2 top-1/2 -translate-y-1/2', light ? 'text-[var(--se-text-fnt)] hover:text-[var(--se-text)]' : 'text-white/30 hover:text-white/70')}
                      aria-label="Clear search"
                    >
                      <X className="w-3.5 h-3.5" />
                    </button>
                  )}
                </div>
                <span className={clsx('text-xs tabular-nums', light ? 'text-[var(--se-text-mut)]' : 'text-white/40')}>
                  {q
                    ? `${filteredIdx.length} of ${rows.length} rows`
                    : `${rows.length} row${rows.length === 1 ? '' : 's'}`}
                  {' · '}{header.length} cols
                </span>
                {pageCount > 1 && (
                  <div className="flex items-center gap-1 ml-auto">
                    <button type="button" onClick={() => setPage(p => Math.max(0, p - 1))} disabled={safePage === 0} className={clsx(iconBtn, 'px-2 py-1.5')} aria-label="Previous page">
                      <ChevronLeft className="w-3.5 h-3.5" />
                    </button>
                    <span className={clsx('text-xs tabular-nums px-1', light ? 'text-[var(--se-text-mut)]' : 'text-white/40')}>
                      {pageStart + 1}–{Math.min(pageStart + PAGE_SIZE, filteredIdx.length)} / {filteredIdx.length}
                    </span>
                    <button type="button" onClick={() => setPage(p => Math.min(pageCount - 1, p + 1))} disabled={safePage >= pageCount - 1} className={clsx(iconBtn, 'px-2 py-1.5')} aria-label="Next page">
                      <ChevronRight className="w-3.5 h-3.5" />
                    </button>
                  </div>
                )}
              </div>

              {/* Single scroll box: both axes scroll here, so sticky header + frozen column work */}
              <div
                className={clsx('overflow-auto rounded-lg border', light ? 'border-[var(--se-border)]' : 'border-white/10')}
                style={{ maxHeight: '62vh' }}
              >
                <table className="border-collapse text-xs font-mono">
                  <thead>
                    <tr>
                      <th
                        className={clsx('py-2 border-b', light ? 'border-[var(--se-border)]' : 'border-white/10')}
                        style={{ position: 'sticky', top: 0, left: 0, zIndex: 30, width: ROW_COL_W, minWidth: ROW_COL_W, backgroundColor: railBg }}
                      />
                      {header.map((col, c) => (
                        <th
                          key={c}
                          className={clsx(
                            'px-3 py-2 text-left whitespace-nowrap border-b',
                            light
                              ? 'border-[var(--se-border)] text-[var(--se-text-mut)] font-semibold uppercase text-[11px] tracking-wide'
                              : 'border-white/10 font-medium text-white/50',
                          )}
                          style={
                            c === 0
                              ? { position: 'sticky', top: 0, left: ROW_COL_W, zIndex: 30, backgroundColor: railBg, boxShadow: freezeShadow }
                              : { position: 'sticky', top: 0, zIndex: 20, backgroundColor: railBg }
                          }
                        >
                          {col}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {pageIdx.map(r => (
                      <tr key={r} className={clsx('border-b last:border-b-0', light ? 'border-[var(--se-border-lt)]' : 'border-white/5')}>
                        <td
                          className="px-1.5 py-1 align-middle"
                          style={{ position: 'sticky', left: 0, zIndex: 10, width: ROW_COL_W, minWidth: ROW_COL_W, backgroundColor: cardBg }}
                        >
                          <div className="flex items-center gap-1.5">
                            <button
                              type="button"
                              onClick={() => setEditIdx(r)}
                              title="Edit this record"
                              className={clsx('transition-colors', light ? 'text-[var(--se-text-fnt)] hover:text-[var(--se-accent)]' : 'text-white/30 hover:text-white/80')}
                            >
                              <Pencil className="w-3.5 h-3.5" />
                            </button>
                            <button
                              type="button"
                              onClick={() => deleteRow(r)}
                              title="Delete row"
                              className={clsx('transition-colors', light ? 'text-[var(--se-text-fnt)] hover:text-[var(--se-error)]' : 'text-white/30 hover:text-red-400')}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </td>
                        {header.map((_, c) => (
                          <td
                            key={c}
                            className="px-1 py-1"
                            style={c === 0 ? { position: 'sticky', left: ROW_COL_W, zIndex: 10, backgroundColor: cardBg, boxShadow: freezeShadow } : undefined}
                          >
                            <input
                              type="text"
                              value={rows[r][c] ?? ''}
                              onChange={e => setCell(r, c, e.target.value)}
                              className={clsx(
                                'w-full min-w-[84px] rounded px-2 py-1 text-xs outline-none border',
                                light
                                  ? 'bg-white border-[var(--se-border)] text-[var(--se-text)] focus:border-[var(--se-accent)] focus:ring-1 focus:ring-[var(--se-accent-bd)]'
                                  : 'bg-white/5 focus:bg-white/10 border-white/10 focus:border-moss-500/40 text-white/90',
                              )}
                            />
                          </td>
                        ))}
                      </tr>
                    ))}
                    {rows.length === 0 && (
                      <tr>
                        <td colSpan={header.length + 1} className={clsx('px-3 py-6 text-center text-xs', light ? 'text-[var(--se-text-fnt)]' : 'text-white/30')}>
                          No rows. Click “Add row” to start.
                        </td>
                      </tr>
                    )}
                    {rows.length > 0 && filteredIdx.length === 0 && (
                      <tr>
                        <td colSpan={header.length + 1} className={clsx('px-3 py-6 text-center text-xs', light ? 'text-[var(--se-text-fnt)]' : 'text-white/30')}>
                          No rows match “{query}”.
                        </td>
                      </tr>
                    )}
                  </tbody>
                </table>
              </div>
            </div>
          ) : (
            <textarea
              value={raw}
              onChange={e => { setRaw(e.target.value); setSaveOk(false); }}
              spellCheck={false}
              className={clsx(
                'w-full min-h-[420px] rounded-lg px-3 py-2 font-mono text-xs outline-none resize-y border',
                light
                  ? 'bg-white border-[var(--se-border)] text-[var(--se-text)] focus:border-[var(--se-accent)]'
                  : 'bg-white/5 border-white/10 focus:border-moss-500/40 text-white/90',
              )}
            />
          )}

          {/* Actions */}
          <div
            className={clsx(
              'flex flex-wrap items-center gap-3 pt-3 border-t',
              light ? 'border-[var(--se-border)]' : 'border-white/10',
            )}
          >
            {tabular && editIdx === null && (
              <button
                type="button"
                onClick={addRow}
                className={clsx(
                  'flex items-center gap-1.5 text-xs border rounded-lg px-3 py-2',
                  light
                    ? 'text-[var(--se-text-mut)] hover:text-[var(--se-accent)] border-[var(--se-border)] hover:border-[var(--se-accent-bd)]'
                    : 'text-white/60 hover:text-white/90 border-white/10 hover:border-white/20',
                )}
              >
                <Plus className="w-3.5 h-3.5" /> Add row
              </button>
            )}
            <button
              type="button"
              onClick={save}
              disabled={saving}
              className={clsx(
                'flex items-center gap-2 disabled:opacity-40 rounded-lg px-5 py-2.5 text-sm font-medium text-white',
                light ? 'bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)]' : 'bg-moss-600 hover:bg-moss-700',
              )}
            >
              {saving ? <Loader2 className="w-4 h-4 animate-spin" /> : <Save className="w-4 h-4" />}
              Save
            </button>
            {saveOk && (
              <span className={clsx('flex items-center gap-1.5 text-sm', light ? 'text-[var(--se-ok)]' : 'text-moss-400')}>
                <CheckCircle className="w-4 h-4" /> Saved — a .bak backup was written
              </span>
            )}
            {saveError && (
              <span className={clsx('flex items-center gap-1.5 text-sm', light ? 'text-[var(--se-error)]' : 'text-red-400')}>
                <XCircle className="w-4 h-4" /> {saveError}
              </span>
            )}
          </div>
        </>
      )}
    </div>
  );
}
