import clsx from 'clsx';
import { Link } from 'react-router-dom';
import { CheckCircle, AlertCircle, Circle, HelpCircle } from 'lucide-react';

export interface SetupStep {
  id: string;
  label: string;
  status: string;
  detail: string;
  action?: string;
}

const statusIcon: Record<string, typeof CheckCircle> = {
  ok: CheckCircle,
  warning: AlertCircle,
  missing: Circle,
  optional: HelpCircle,
};

const statusColor: Record<string, string> = {
  ok: 'text-moss-400 border-moss-500/30 bg-moss-500/5',
  warning: 'text-earth-400 border-earth-400/30 bg-earth-400/5',
  missing: 'text-red-400 border-red-500/30 bg-red-500/5',
  optional: 'text-white/40 border-white/10 bg-white/5',
};

interface Props {
  progressPct: number;
  steps: SetupStep[];
  blockReason?: string;
}

export default function SetupProgress({ progressPct, steps, blockReason }: Props) {
  return (
    <div className="space-y-4">
      <div>
        <div className="flex justify-between text-xs text-white/50 mb-2">
          <span>Setup progress</span>
          <span className="font-medium text-white/70">{progressPct}%</span>
        </div>
        <div className="h-2 rounded-full bg-white/10 overflow-hidden">
          <div
            className={clsx(
              'h-full rounded-full transition-all duration-500',
              progressPct >= 100 ? 'bg-moss-500' : progressPct >= 50 ? 'bg-earth-400' : 'bg-red-500/80',
            )}
            style={{ width: `${progressPct}%` }}
          />
        </div>
      </div>

      {blockReason && (
        <p className="text-xs text-red-300/90 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
          {blockReason}
        </p>
      )}

      <ol className="space-y-2">
        {steps.map((step, i) => {
          const Icon = statusIcon[step.status] || Circle;
          const done = step.status === 'ok';
          const content = (
            <div
              className={clsx(
                'flex items-start gap-3 p-3 rounded-xl border transition-colors',
                statusColor[step.status] || statusColor.missing,
                step.action && !done && 'hover:brightness-110 cursor-pointer',
              )}
            >
              <div className="flex flex-col items-center gap-1 shrink-0">
                <span className="text-[10px] text-white/30 font-mono">{i + 1}</span>
                <Icon className="w-5 h-5" />
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-white/90">{step.label}</p>
                <p className="text-xs text-white/45 mt-0.5">{step.detail}</p>
              </div>
            </div>
          );
          if (step.action && !done) {
            return (
              <li key={step.id}>
                <Link to={step.action}>{content}</Link>
              </li>
            );
          }
          return <li key={step.id}>{content}</li>;
        })}
      </ol>
    </div>
  );
}
