import { Loader2 } from 'lucide-react';

interface Props {
  progress: number;
  label: string;
}

export default function RunProgress({ progress, label }: Props) {
  return (
    <div className="space-y-3 rounded-lg border border-[var(--se-border)] bg-[var(--se-card)] p-4 shadow-sm">
      <div className="flex items-center gap-2 text-sm text-[var(--se-text)]">
        <Loader2 className="w-4 h-4 animate-spin text-[var(--se-accent)]" />
        {label}
      </div>
      <div className="h-2 bg-[var(--se-border-lt)] rounded-full overflow-hidden">
        <div
          className="h-full bg-[var(--se-accent)] transition-all duration-500 rounded-full"
          style={{ width: `${Math.min(100, progress)}%` }}
        />
      </div>
      <p className="text-xs text-[var(--se-text-mut)]">{progress}% — this may take a few minutes</p>
    </div>
  );
}
