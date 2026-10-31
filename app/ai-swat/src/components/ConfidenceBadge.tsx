import clsx from 'clsx';
import { ShieldCheck, Shield, TriangleAlert, HelpCircle } from 'lucide-react';
import { confidenceColor, confidenceLabel, type OutputConfidence } from '@/lib/api';

const ICONS = {
  high: ShieldCheck,
  moderate: Shield,
  low: TriangleAlert,
  directional: TriangleAlert,
  unavailable: HelpCircle,
} as const;

/** Small pill showing how much to trust a number. Renders nothing if no confidence given. */
export default function ConfidenceBadge({
  confidence,
  size = 'sm',
}: {
  confidence?: OutputConfidence | null;
  size?: 'sm' | 'xs';
}) {
  if (!confidence?.level) return null;
  const Icon = ICONS[confidence.level] ?? Shield;
  const label = confidence.label || confidenceLabel(confidence.level);
  return (
    <span
      title={confidence.note || label}
      className={clsx(
        'inline-flex items-center gap-1 rounded-full border font-medium whitespace-nowrap',
        confidenceColor(confidence.level),
        size === 'xs' ? 'text-[10px] px-2 py-0.5' : 'text-[11px] px-2.5 py-1',
      )}
    >
      <Icon className={size === 'xs' ? 'w-3 h-3' : 'w-3.5 h-3.5'} />
      {label}
    </span>
  );
}
