import { ChevronRight } from 'lucide-react';
import type { Widget } from '@/lib/widgets';

interface ChoicePayload {
  question: string;
  options: { id: string; label: string; detail?: string }[];
}

export default function ChoiceWidget({ widget, onSubmit, disabled }: {
  widget: Widget;
  onSubmit: (w: Widget, data: Record<string, unknown>) => void;
  disabled?: boolean;
}) {
  const p = widget.payload as ChoicePayload;
  return (
    <div className="space-y-3">
      {p.question && <p className="text-sm font-medium text-[var(--se-text)]">{p.question}</p>}
      <div className="flex flex-col gap-2">
        {p.options.map(o => (
          <button
            key={o.id}
            disabled={disabled}
            onClick={() => onSubmit(widget, { value: o.id, label: o.label })}
            className="group flex items-center gap-3 text-left px-4 py-3 rounded-lg bg-white border border-[var(--se-border)] shadow-sm hover:border-[var(--se-accent)] hover:bg-[var(--se-accent-sf)] disabled:opacity-40 text-sm text-[var(--se-text)] transition-colors"
          >
            <span className="flex-1 min-w-0">
              {o.label}
              {o.detail && <span className="block text-xs text-[var(--se-text-fnt)] mt-0.5">{o.detail}</span>}
            </span>
            <ChevronRight className="w-4 h-4 shrink-0 text-[var(--se-text-fnt)] group-hover:text-[var(--se-accent)] transition-colors" />
          </button>
        ))}
      </div>
    </div>
  );
}
