import type { Widget } from '@/lib/widgets';

interface ConfirmPayload {
  title: string;
  detail?: string;
  confirmLabel?: string;
  denyLabel?: string;
}

export default function ConfirmWidget({ widget, onSubmit, disabled }: {
  widget: Widget;
  onSubmit: (w: Widget, data: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const p = widget.payload as ConfirmPayload;
  return (
    <div className="space-y-3">
      <p className="text-sm font-medium text-[var(--se-text)]">{p.title}</p>
      {p.detail && <p className="text-xs text-[var(--se-text-mut)] leading-relaxed">{p.detail}</p>}
      <div className="flex gap-2">
        <button
          disabled={disabled}
          onClick={() => onSubmit(widget, { confirmed: true })}
          className="px-4 py-2 rounded-lg bg-[var(--se-accent)] hover:bg-[var(--se-accent-h)] text-white disabled:opacity-40 text-sm font-medium"
        >
          {p.confirmLabel || 'Yes'}
        </button>
        <button
          disabled={disabled}
          onClick={() => onSubmit(widget, { confirmed: false })}
          className="px-4 py-2 rounded-lg border border-[var(--se-border)] bg-white text-[var(--se-text)] hover:bg-[var(--se-rail)] disabled:opacity-40 text-sm"
        >
          {p.denyLabel || 'No'}
        </button>
      </div>
    </div>
  );
}
