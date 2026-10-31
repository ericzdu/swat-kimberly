import { useState } from 'react';
import clsx from 'clsx';
import { File, Folder, Loader2, Eye } from 'lucide-react';
import { data, type FileEntry, type FilePreview } from '@/lib/api';

interface Props {
  farmId: string;
  zone: string;
  title: string;
  files: FileEntry[];
  emptyMessage?: string;
}

export default function FileBrowser({ farmId, zone, title, files, emptyMessage }: Props) {
  const [preview, setPreview] = useState<FilePreview | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');

  const openPreview = async (path: string) => {
    setLoading(true);
    setPreviewError('');
    try {
      const p = await data.previewFile(farmId, zone, path);
      setPreview(p);
    } catch (e) {
      setPreviewError(e instanceof Error ? e.message : 'Could not load file');
      setPreview(null);
    } finally {
      setLoading(false);
    }
  };

  if (!files.length) {
    return (
      <div className="rounded-xl border border-white/10 p-4">
        <h3 className="text-sm font-semibold text-white/80 mb-2">{title}</h3>
        <p className="text-xs text-white/35">{emptyMessage || 'No files yet'}</p>
      </div>
    );
  }

  return (
    <div className="rounded-xl border border-white/10 overflow-hidden">
      <div className="px-4 py-3 border-b border-white/10 bg-white/[0.02]">
        <h3 className="text-sm font-semibold text-white/80">{title}</h3>
        <p className="text-[10px] text-white/35 mt-0.5">{files.length} item(s) · click preview on text files</p>
      </div>
      <ul className="max-h-52 overflow-y-auto divide-y divide-white/5">
        {files.map(f => (
          <li key={f.path} className="flex items-center gap-2 px-3 py-2 text-xs hover:bg-white/5">
            {f.kind === 'dir' ? (
              <Folder className="w-3.5 h-3.5 text-earth-400 shrink-0" />
            ) : (
              <File className="w-3.5 h-3.5 text-white/40 shrink-0" />
            )}
            <span className={clsx('truncate flex-1 font-mono', f.kind === 'dir' ? 'text-white/50' : 'text-white/70')}>
              {f.path}
            </span>
            {f.size_label && <span className="text-white/30 shrink-0">{f.size_label}</span>}
            {f.previewable && (
              <button
                type="button"
                onClick={() => openPreview(f.path)}
                className="shrink-0 p-1 rounded hover:bg-white/10 text-moss-400"
                title="Preview"
              >
                <Eye className="w-3.5 h-3.5" />
              </button>
            )}
          </li>
        ))}
      </ul>
      {(loading || preview || previewError) && (
        <div className="border-t border-white/10 bg-black/30 p-3">
          {loading && <Loader2 className="w-4 h-4 animate-spin text-moss-400" />}
          {previewError && <p className="text-xs text-red-400">{previewError}</p>}
          {preview && (
            <div>
              <p className="text-[10px] text-white/40 mb-2 font-mono">{preview.path}</p>
              <pre className="text-[11px] text-white/70 max-h-48 overflow-auto whitespace-pre-wrap font-mono bg-black/40 rounded-lg p-3">
                {preview.lines.join('\n')}
                {preview.truncated && '\n… (truncated)'}
              </pre>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
