import clsx from 'clsx';
import { AlertTriangle, XCircle, Info } from 'lucide-react';
import { Link } from 'react-router-dom';

type Variant = 'error' | 'warning' | 'info';

const styles: Record<Variant, string> = {
  error: 'border-red-500/40 bg-red-500/10 text-red-200',
  warning: 'border-earth-400/40 bg-earth-400/10 text-earth-200',
  info: 'border-blue-500/40 bg-blue-500/10 text-blue-200',
};

const icons = {
  error: XCircle,
  warning: AlertTriangle,
  info: Info,
};

interface Props {
  variant?: Variant;
  title?: string;
  message: string;
  action?: { label: string; to: string };
}

export default function ErrorBanner({ variant = 'error', title, message, action }: Props) {
  const Icon = icons[variant];
  return (
    <div className={clsx('rounded-xl border px-4 py-3 flex gap-3', styles[variant])}>
      <Icon className="w-5 h-5 shrink-0 mt-0.5 opacity-90" />
      <div className="min-w-0 flex-1">
        {title && <p className="text-sm font-semibold mb-0.5">{title}</p>}
        <p className="text-sm opacity-90 leading-relaxed">{message}</p>
        {action && (
          <Link to={action.to} className="inline-block mt-2 text-xs font-medium underline opacity-90 hover:opacity-100">
            {action.label}
          </Link>
        )}
      </div>
    </div>
  );
}
