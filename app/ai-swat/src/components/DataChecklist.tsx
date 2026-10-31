import clsx from 'clsx';
import { CheckCircle, AlertCircle, Circle, HelpCircle } from 'lucide-react';
import type { ReadinessCheck } from '@/lib/api';

const statusIcon = {
  ok: CheckCircle,
  warning: AlertCircle,
  missing: Circle,
  optional: HelpCircle,
};

const statusColor = {
  ok: 'text-[var(--se-ok)]',
  warning: 'text-[var(--se-warn)]',
  missing: 'text-[var(--se-error)]',
  optional: 'text-[var(--se-text-fnt)]',
};

const statusBg = {
  ok: 'border-[var(--se-ok-bd)] bg-[var(--se-ok-sf)]',
  warning: 'border-[var(--se-warn-bd)] bg-[var(--se-warn-sf)]',
  missing: 'border-[var(--se-error-bd)] bg-[var(--se-error-sf)]',
  optional: 'border-[var(--se-border)] bg-[var(--se-card)]',
};

interface Props {
  checks: ReadinessCheck[];
  showProgress?: boolean;
}

export default function DataChecklist({ checks, showProgress }: Props) {
  const required = checks.filter(c => c.status !== 'optional');
  const done = required.filter(c => c.status === 'ok').length;
  const pct = required.length ? Math.round((done / required.length) * 100) : 0;

  return (
    <div className="space-y-3">
      {showProgress && (
        <div className="flex items-center justify-between text-xs text-[var(--se-text-mut)]">
          <span>{done} of {required.length} required items complete</span>
          <span className="font-medium text-[var(--se-text)]">{pct}%</span>
        </div>
      )}
      <ul className="space-y-2">
        {checks.map(c => {
          const Icon = statusIcon[c.status] || Circle;
          return (
            <li
              key={c.id}
              className={clsx(
                'flex items-start gap-3 p-3 rounded-lg border shadow-sm',
                statusBg[c.status],
              )}
            >
              <Icon className={clsx('w-5 h-5 shrink-0 mt-0.5', statusColor[c.status])} />
              <div className="min-w-0">
                <p className="text-sm font-medium text-[var(--se-text)]">{c.label}</p>
                <p className={clsx(
                  'text-xs mt-0.5',
                  c.status === 'missing' ? 'text-[var(--se-error)]' :
                  c.status === 'warning' ? 'text-[var(--se-warn)]' : 'text-[var(--se-text-mut)]',
                )}>
                  {c.detail}
                </p>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
