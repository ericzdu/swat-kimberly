import { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Home, CloudRain, Share2, Mountain, Map as MapIcon, Sprout, ListTree, Sliders,
  FlaskConical, Droplets, Layers, Database, Wrench, Play, Pencil,
  Waves, Network, Grid3x3, Droplet, Radio, Tractor, Leaf,
  ChevronDown, ChevronRight, Info, RefreshCw, Loader2,
  type LucideIcon,
} from 'lucide-react';
import clsx from 'clsx';
import { swatEditor, type EditorFileList } from '@/lib/api';
import { useField } from '@/context/FieldContext';
import FileTableEditor from '@/components/FileTableEditor';
import SoilEditor from '@/components/swateditor/SoilEditor';
import RunPanel from '@/components/swateditor/RunPanel';
import { SWAT_NAV, type NavLeaf } from './swatEditorNav';

const TOKENS: React.CSSProperties = {
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

const ICONS: Record<string, LucideIcon> = {
  Home, CloudRain, Share2, Mountain, Map: MapIcon, Sprout, ListTree, Sliders,
  FlaskConical, Droplets, Layers, Database, Wrench, Play,
  Waves, Network, Grid3x3, Droplet, Radio, Tractor, Leaf,
};

interface SelectedLeaf { sectionId: string; leafIdx: number; }

const RUN_SECTION = SWAT_NAV.find(s => s.id === 'run');
const RUN_LEAF: SelectedLeaf | null = RUN_SECTION
  ? { sectionId: 'run', leafIdx: RUN_SECTION.leaves.findIndex(l => l.special === 'run') }
  : null;

export default function SwatEditor() {
  const { farms: farmList, selectedFarmId: farmId } = useField();
  const [selected, setSelected] = useState<SelectedLeaf>({ sectionId: 'home', leafIdx: 0 });
  const [openGroups, setOpenGroups] = useState<Set<string>>(
    () => new Set(SWAT_NAV.filter(s => s.defaultOpen).map(s => s.id)),
  );

  const [fileList, setFileList] = useState<EditorFileList | null>(null);
  const [filesLoading, setFilesLoading] = useState(false);
  const [filesError, setFilesError] = useState('');

  const loadFiles = useCallback(() => {
    if (!farmId) {
      setFileList(null);
      return;
    }
    let alive = true;
    setFilesLoading(true);
    setFilesError('');
    swatEditor
      .listFiles(farmId)
      .then(list => {
        if (!alive) return;
        setFileList(list);
        if (!list.ok) setFilesError(list.error || 'This field has no SWAT+ model files yet.');
      })
      .catch(e => {
        if (alive) setFilesError(e instanceof Error ? e.message : 'Could not load model files.');
      })
      .finally(() => {
        if (alive) setFilesLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [farmId]);

  useEffect(() => loadFiles(), [loadFiles]);

  const availableFiles = useMemo(
    () => new Set((fileList?.categories ?? []).flatMap(c => c.files.map(f => f.name))),
    [fileList],
  );

  const fileDescs = useMemo(() => {
    const map = new Map<string, string>();
    for (const c of fileList?.categories ?? []) {
      for (const f of c.files) if (f.desc) map.set(f.name, f.desc);
    }
    return map;
  }, [fileList]);

  const totalFiles = availableFiles.size;

  const toggleGroup = (id: string) =>
    setOpenGroups(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  const selectRun = () => {
    if (RUN_LEAF) {
      setSelected(RUN_LEAF);
      setOpenGroups(prev => new Set(prev).add('run'));
    }
  };

  const section = SWAT_NAV.find(s => s.id === selected.sectionId) ?? SWAT_NAV[0];
  const leaf: NavLeaf | undefined = section.leaves[selected.leafIdx];
  const isRunActive = selected.sectionId === 'run' && leaf?.special === 'run';
  const selectedFarm = farmList.find(f => f.id === farmId);
  const fieldName = selectedFarm?.name ?? '';
  const breadcrumbFile = leaf?.file;

  return (
    <div
      className="swateditor-root flex flex-col h-full bg-[var(--se-bg)] text-[var(--se-text)]"
      style={TOKENS}
    >
      {/* Top bar */}
      <div className="h-14 shrink-0 bg-[var(--se-card)] border-b border-[var(--se-border)] flex items-center px-4 gap-3">
        <Pencil className="w-4 h-4 text-[var(--se-accent)] shrink-0" />
        {fieldName ? (
          <span className="text-sm font-medium">{fieldName}</span>
        ) : (
          <span className="text-sm text-[var(--se-text-mut)]">Select a field in the bar above</span>
        )}
        <div className="flex-1" />
        <button
          onClick={selectRun}
          className="flex items-center gap-1.5 bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white rounded-lg px-4 py-1.5 text-sm font-medium transition-colors"
        >
          <Play className="w-4 h-4" /> Run SWAT+
        </button>
      </div>

      {/* Body */}
      <div className="flex-1 flex min-h-0">
        {/* Icon rail */}
        <div className="w-14 shrink-0 bg-[var(--se-rail)] border-r border-[var(--se-border)] flex flex-col items-center py-3 gap-2">
          <button
            onClick={() => setSelected({ sectionId: 'home', leafIdx: 0 })}
            className={clsx(
              'w-10 h-10 flex items-center justify-center rounded-lg transition-colors',
              !isRunActive ? 'text-[var(--se-accent)] bg-[var(--se-accent-sf)]' : 'text-[var(--se-text-mut)] hover:text-[var(--se-text)]',
            )}
            title="Edit inputs"
            aria-label="Edit inputs"
          >
            <Pencil className="w-5 h-5" />
          </button>
          <button
            onClick={selectRun}
            className={clsx(
              'w-10 h-10 flex items-center justify-center rounded-lg transition-colors',
              isRunActive ? 'text-[var(--se-accent)] bg-[var(--se-accent-sf)]' : 'text-[var(--se-text-mut)] hover:text-[var(--se-text)]',
            )}
            title="Run SWAT+"
            aria-label="Run SWAT+"
          >
            <Play className="w-5 h-5" />
          </button>
        </div>

        {/* Section nav */}
        <div className="w-64 shrink-0 bg-[var(--se-rail)] border-r border-[var(--se-border)] overflow-y-auto py-2">
          {SWAT_NAV.map(sec => {
            const Icon = ICONS[sec.icon] ?? Home;
            const open = openGroups.has(sec.id);
            return (
              <div key={sec.id} className="mb-0.5">
                <button
                  onClick={() => toggleGroup(sec.id)}
                  className="w-full flex items-center gap-1.5 px-3 py-2 text-left text-[var(--se-text-mut)] hover:text-[var(--se-text)] transition-colors"
                >
                  {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                  <Icon className="w-4 h-4" />
                  <span className="uppercase text-[11px] tracking-wide font-semibold">{sec.label}</span>
                </button>
                {open && (
                  <div className="pb-1">
                    {sec.leaves.map((lf, idx) => {
                      const active = selected.sectionId === sec.id && selected.leafIdx === idx;
                      const missing = !lf.special && !!lf.file && !availableFiles.has(lf.file);
                      return (
                        <button
                          key={lf.label}
                          onClick={() => setSelected({ sectionId: sec.id, leafIdx: idx })}
                          className={clsx(
                            'w-full flex items-center justify-between gap-2 pl-9 pr-3 py-1.5 text-left text-sm transition-colors',
                            active
                              ? 'bg-[var(--se-accent-sf)] text-[var(--se-accent)] border-l-2 border-[var(--se-accent-bd)]'
                              : missing
                                ? 'text-[var(--se-text-fnt)] hover:bg-[var(--se-border-lt)] border-l-2 border-transparent'
                                : 'text-[var(--se-text)] hover:bg-[var(--se-border-lt)] border-l-2 border-transparent',
                          )}
                        >
                          <span className="truncate">{lf.label}</span>
                          {missing && <span className="text-[var(--se-text-fnt)] shrink-0">—</span>}
                        </button>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Main */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Breadcrumb */}
          <div className="px-6 py-3 border-b border-[var(--se-border)] bg-[var(--se-card)] flex items-center gap-2 text-sm">
            <span className="text-[var(--se-text-mut)]">{section.label}</span>
            {leaf && (
              <>
                <ChevronRight className="w-3.5 h-3.5 text-[var(--se-text-fnt)]" />
                <span className="font-medium">{leaf.label}</span>
              </>
            )}
            {breadcrumbFile && (
              <span className="font-mono text-xs bg-[var(--se-rail)] text-[var(--se-text-mut)] px-2 py-0.5 rounded">
                {breadcrumbFile}
              </span>
            )}
          </div>

          {/* Section page */}
          <div className="flex-1 overflow-y-auto p-6">
            {!farmId ? (
              <div className="bg-[var(--se-card)] border border-[var(--se-border)] rounded-lg p-6 text-sm text-[var(--se-text-mut)]">
                Select a field to browse and edit its SWAT+ model.
              </div>
            ) : !leaf ? (
              <div className="bg-[var(--se-card)] border border-[var(--se-border)] rounded-lg p-6 text-sm text-[var(--se-text-mut)]">
                Select a section from the left.
              </div>
            ) : leaf.special === 'run' ? (
              <RunPanel farmId={farmId} />
            ) : leaf.special === 'dashboard' ? (
              <div className="bg-[var(--se-card)] border border-[var(--se-border)] rounded-lg p-6 space-y-3 max-w-2xl">
                <h2 className="text-lg font-semibold">{fieldName || 'Project'}</h2>
                <dl className="space-y-2 text-sm">
                  <div className="flex justify-between gap-4">
                    <dt className="text-[var(--se-text-mut)]">TxtInOut path</dt>
                    <dd className="font-mono text-xs text-[var(--se-text)] truncate">{fileList?.txtinout || '—'}</dd>
                  </div>
                  <div className="flex justify-between gap-4">
                    <dt className="text-[var(--se-text-mut)]">Model files</dt>
                    <dd className="font-medium">{totalFiles}</dd>
                  </div>
                </dl>
                <p className="text-xs text-[var(--se-text-mut)] pt-2 border-t border-[var(--se-border-lt)]">
                  Pick a section from the left to edit input files, or run the model.
                </p>
              </div>
            ) : leaf.file && availableFiles.has(leaf.file) ? (
              <div className="bg-[var(--se-card)] border border-[var(--se-border)] rounded-lg p-5">
                <h2 className="text-lg font-semibold">{leaf.label}</h2>
                {fileDescs.get(leaf.file) && (
                  <p className="text-sm text-[var(--se-text-mut)] mt-1">{fileDescs.get(leaf.file)}</p>
                )}
                <div className="mt-4">
                  {leaf.file === 'soils.sol'
                    ? <SoilEditor farmId={farmId} />
                    : <FileTableEditor farmId={farmId} name={leaf.file} light />}
                </div>
              </div>
            ) : (
              <div className="bg-[var(--se-card)] border border-[var(--se-border)] rounded-lg p-6 max-w-xl">
                <div className="flex items-start gap-3">
                  <Info className="w-5 h-5 shrink-0 text-[var(--se-text-mut)] mt-0.5" />
                  <div className="space-y-3">
                    <p className="text-sm text-[var(--se-text)]">
                      <span className="font-mono">{leaf.file}</span> isn&apos;t in this field&apos;s model yet.
                      It appears here once it exists in the model files.
                    </p>
                    {filesError && <p className="text-xs text-[var(--se-error)]">{filesError}</p>}
                    <button
                      onClick={loadFiles}
                      disabled={filesLoading}
                      className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-[var(--se-border)] text-[var(--se-text-mut)] hover:text-[var(--se-text)] hover:border-[var(--se-accent-bd)] disabled:opacity-40"
                    >
                      {filesLoading ? <Loader2 className="w-4 h-4 animate-spin" /> : <RefreshCw className="w-4 h-4" />}
                      Refresh files
                    </button>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
